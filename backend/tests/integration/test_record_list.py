"""기록함 목록 (A-2): 커서 · 필터 · 검색 · is_edited · 분류 상태 일치"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.schemas.records import RecordListItemOut
from app.workers.tasks import records as record_tasks
from tests.integration.conftest import (
    PARENT,
    claim_job,
    fail_final,
    join_family,
    run_sql,
)


BASE = datetime.now(timezone.utc) - timedelta(days=30)


def create(client, parent_id, text="오늘 날씨가 좋네요", minutes=0, **extra):
    return client.post(f"/v1/parents/{parent_id}/records/text", json={
        "text": text, "recorded_at": (BASE + timedelta(minutes=minutes)).isoformat(), **extra
    }).json()["data"]["id"]


def classify(db, record_id, version=1):
    record_tasks.classify_record(db, claim_job(db, record_id, "classify_record", version))


def records(client, parent_id, query=""):
    return client.get(f"/v1/parents/{parent_id}/records?{query}")


def ids(response):
    return [r["id"] for r in response.json()["data"]]


# ── 페이지 넘기기 ──

def test_pages_without_duplicates_or_gaps(client, parent_id):
    created = [create(client, parent_id, f"기록 {n}", minutes=n) for n in range(25)]

    first = records(client, parent_id, "limit=10").json()
    assert first["meta"]["total"] == 25 and first["meta"]["has_more"] is True

    seen = [r["id"] for r in first["data"]]
    cursor = first["meta"]["next_cursor"]
    while cursor:
        page = records(client, parent_id, f"limit=10&cursor={cursor}").json()
        assert page["meta"]["total"] is None
        seen += [r["id"] for r in page["data"]]
        cursor = page["meta"]["next_cursor"]

    assert seen == list(reversed(created))
    assert page["meta"]["has_more"] is False and len(page["data"]) == 5


def test_same_recorded_at_order_fixed(client, parent_id):
    created = {create(client, parent_id, f"같은 시각 {n}") for n in range(3)}

    seen, cursor = [], None
    for _ in range(3):
        query = "limit=1" + (f"&cursor={cursor}" if cursor else "")
        body = records(client, parent_id, query).json()
        seen += [r["id"] for r in body["data"]]
        cursor = body["meta"]["next_cursor"]

    assert set(seen) == created and len(seen) == 3
    assert seen == sorted(seen, reverse=True)


def test_edit_and_exclude_while_paging(client, parent_id):
    created = [create(client, parent_id, f"기록 {n}", minutes=n) for n in range(5)]
    first = records(client, parent_id, "limit=2").json()
    assert ids_of(first) == [created[4], created[3]]

    # 다음 페이지 보기 전: 받은 기록 수정, 아직 안 본 기록 제외
    client.patch(f"/v1/records/{created[4]}", json={"current_text": "고침"})
    client.post(f"/v1/records/{created[2]}/exclude")

    rest = records(client, parent_id, f"limit=10&cursor={first['meta']['next_cursor']}").json()
    assert ids_of(rest) == [created[1], created[0]]


def ids_of(body):
    return [r["id"] for r in body["data"]]


# ── 커서 검증 ──

def test_cursor_rejected_when_filters_change(client, parent_id):
    for n in range(3):
        create(client, parent_id, f"밥 {n}", minutes=n)
    cursor = records(client, parent_id, "limit=1&q=밥").json()["meta"]["next_cursor"]

    assert records(client, parent_id, f"limit=1&q=밥&cursor={cursor}").status_code == 200
    # 페이지 크기만 바꿈 → 허용
    assert records(client, parent_id, f"limit=5&q=밥&cursor={cursor}").status_code == 200
    # 앞뒤 공백 → 같은 조건
    assert records(client, parent_id, f"limit=1&q=%20밥%20&cursor={cursor}").status_code == 200

    for changed in ["q=국", "", "q=밥&source=call", "q=밥&status=all", "q=밥&area=physical"]:
        response = records(client, parent_id, f"limit=1&{changed}&cursor={cursor}")
        assert response.status_code == 400, changed
        assert response.json()["error"]["code"] == "INVALID_CURSOR"


def test_cursor_tampered_or_garbage(client, parent_id):
    for n in range(2):
        create(client, parent_id, minutes=n)
    cursor = records(client, parent_id, "limit=1").json()["meta"]["next_cursor"]
    body, signature = cursor.split(".")

    tampered = ("A" if body[0] != "A" else "B") + body[1:]
    for bad in [f"{tampered}.{signature}", f"{body}.{signature[:-2]}", "abc", "a.b.c", ""]:
        response = records(client, parent_id, f"limit=1&cursor={bad}")
        if bad == "":
            # 빈 커서 → 커서 없음 (첫 페이지)
            assert response.status_code == 200
            continue
        assert response.status_code == 400, bad
        assert response.json()["error"]["code"] == "INVALID_CURSOR"


def test_cursor_from_other_parent(client, parent_id):
    other_parent = client.post("/v1/parents", json={**PARENT, "nickname": "아빠"}).json()["data"]["id"]
    for n in range(2):
        create(client, parent_id, minutes=n)
        create(client, other_parent, minutes=n)

    cursor = records(client, parent_id, "limit=1").json()["meta"]["next_cursor"]
    response = records(client, other_parent, f"limit=1&cursor={cursor}")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CURSOR"


# ── 검색 ──

def test_search_current_text_only(client, parent_id):
    record_id = create(client, parent_id, "점심에 국수 드셨어요")
    client.patch(f"/v1/records/{record_id}", json={"current_text": "점심에 죽 드셨어요"})

    assert ids(records(client, parent_id, "q=국수")) == []
    assert ids(records(client, parent_id, "q=죽")) == [record_id]


def test_search_literal_pattern_chars_and_blank(client, parent_id):
    percent = create(client, parent_id, "약 100% 드심", minutes=1)
    underscore = create(client, parent_id, "메모_확인", minutes=2)
    create(client, parent_id, "약 1000 드심", minutes=3)

    assert ids(records(client, parent_id, "q=100%25")) == [percent]
    assert ids(records(client, parent_id, "q=_")) == [underscore]
    # 공백만 → 검색 없음
    assert records(client, parent_id, "q=%20%20").json()["meta"]["total"] == 3
    assert records(client, parent_id, "q=" + "가" * 51).status_code == 422


def test_search_skips_voice_before_transcription(client, db, user_id, parent_id):
    run_sql(
        db,
        """
            INSERT INTO records (parent_id, author_id, input_type, source,
                                 audio_path, audio_duration_seconds)
            VALUES (:p, :u, 'voice', 'direct', :path, 3)
        """,
        p=parent_id, u=user_id, path=f"{parent_id}/test.m4a"
    )

    assert records(client, parent_id).json()["meta"]["total"] == 1
    assert records(client, parent_id, "q=밥").json()["data"] == []


# ── 필터 ──

def test_area_filter_no_duplicates(client, db, parent_id):
    # phys_eating + phys_toilet_use (둘 다 신체)
    two_items = create(client, parent_id, "밥 드시고 화장실", minutes=1)
    memory = create(client, parent_id, "기억을 깜빡", minutes=2)
    classify(db, two_items)
    classify(db, memory)

    assert ids(records(client, parent_id, "area=physical")) == [two_items]
    assert ids(records(client, parent_id, "area=cognitive")) == [memory]
    assert records(client, parent_id, "area=physical").json()["meta"]["total"] == 1
    assert records(client, parent_id, "area=uncat").status_code == 422


def test_processing_and_classification_filters(client, db, parent_id):
    pending = create(client, parent_id, "밥", minutes=1)
    classified = create(client, parent_id, "밥 드셨어요", minutes=2)
    unclassified = create(client, parent_id, "오늘 날씨가 좋네요", minutes=3)
    failed = create(client, parent_id, "[ai-fail] 밥", minutes=4)
    classify(db, classified)
    classify(db, unclassified)
    fail_final(db, claim_job(db, failed, "classify_record", 1))

    # 분석 중·실패도 전체 목록에 표시
    assert set(ids(records(client, parent_id))) == {pending, classified, unclassified, failed}
    assert ids(records(client, parent_id, "processing_status=pending")) == [pending]
    assert ids(records(client, parent_id, "processing_status=failed")) == [failed]
    assert ids(records(client, parent_id, "classification_status=unclassified")) == [unclassified]
    assert ids(records(client, parent_id, "classification_status=classified")) == [classified]
    # 영역 + 미분류 → 항상 빈 결과 (오류 X)
    assert ids(records(client, parent_id, "area=physical&classification_status=unclassified")) == []


def test_user_cleared_classification_is_unclassified(client, db, parent_id):
    record_id = create(client, parent_id, "밥 드셨어요")
    classify(db, record_id)

    client.patch(f"/v1/records/{record_id}", json={"item_codes": []})

    assert ids(records(client, parent_id, "classification_status=unclassified")) == [record_id]


def test_status_author_source_input_type(client, db, consent_docs, user_id, parent_id):
    mine = create(client, parent_id, minutes=1)
    call = create(client, parent_id, minutes=2, source="call")
    client.post(f"/v1/records/{call}/exclude")

    writer = join_family(db, client, consent_docs, parent_id, "writer")
    theirs = create(client, parent_id, minutes=3)

    assert ids(records(client, parent_id)) == [theirs, mine]
    assert ids(records(client, parent_id, "status=excluded")) == [call]
    assert ids(records(client, parent_id, "status=all")) == [theirs, call, mine]
    assert ids(records(client, parent_id, f"author_id={writer}")) == [theirs]
    assert ids(records(client, parent_id, f"author_id={user_id}&status=all")) == [call, mine]
    assert ids(records(client, parent_id, "source=call&status=all")) == [call]
    assert ids(records(client, parent_id, "input_type=voice")) == []
    # 가족 아닌 작성자 → 빈 결과
    assert ids(records(client, parent_id, "author_id=00000000-0000-0000-0000-000000000000")) == []


def test_date_range_kst_boundaries(client, parent_id):
    kst = timezone(timedelta(hours=9))
    day = (datetime.now(kst) - timedelta(days=10)).date()
    midnight = datetime(day.year, day.month, day.day, tzinfo=kst)

    def at(dt, text):
        return client.post(f"/v1/parents/{parent_id}/records/text", json={
            "text": text, "recorded_at": dt.isoformat()
        }).json()["data"]["id"]

    before = at(midnight - timedelta(seconds=1), "전날 끝")
    start = at(midnight, "당일 시작")
    end = at(midnight + timedelta(days=1, seconds=-1), "당일 끝")
    at(midnight + timedelta(days=1), "다음날 시작")

    assert ids(records(client, parent_id, f"from={day}&to={day}")) == [end, start]
    assert ids(records(client, parent_id, f"to={day - timedelta(days=1)}")) == [before]

    response = records(client, parent_id, f"from={day}&to={day - timedelta(days=1)}")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize("query", [
    "status=deleted", "source=letter", "input_type=photo", "author_id=nope",
    "from=2026-13-01", "unknown=1", "limit=0", "limit=101",
])
def test_invalid_query_422(client, parent_id, query):
    assert records(client, parent_id, query).status_code == 422


def test_viewer_can_list(client, db, consent_docs, parent_id):
    record_id = create(client, parent_id)
    join_family(db, client, consent_docs, parent_id, "viewer")

    assert ids(records(client, parent_id)) == [record_id]


# ── is_edited ──

def test_is_edited_only_by_user_edits(client, db, parent_id):
    record_id = create(client, parent_id, "밥 드셨어요")

    def is_edited():
        return records(client, parent_id, "status=all").json()["data"][0]["is_edited"]

    # 최초 저장 · AI 분류 · 제외/복원 → false
    classify(db, record_id)
    client.post(f"/v1/records/{record_id}/exclude")
    client.post(f"/v1/records/{record_id}/include")
    assert is_edited() is False

    # AI 분류 그대로 확정 → 분류 주체만 user, 이력 X
    response = client.patch(f"/v1/records/{record_id}", json={"item_codes": ["phys_eating"]})
    assert response.json()["data"]["classified_by"] == "user"
    assert client.get(f"/v1/records/{record_id}/versions").json()["data"]["history"] == []
    assert is_edited() is False

    client.patch(f"/v1/records/{record_id}", json={"source": "call"})
    assert is_edited() is True
    assert client.get(f"/v1/records/{record_id}").json()["data"]["is_edited"] is True


@pytest.mark.parametrize("body", [
    {"current_text": "고침"},
    {"item_codes": ["phys_toilet_use"]},
])
def test_is_edited_text_or_classification(client, db, parent_id, body):
    record_id = create(client, parent_id, "밥 드셨어요")
    classify(db, record_id)

    client.patch(f"/v1/records/{record_id}", json=body)

    assert records(client, parent_id).json()["data"][0]["is_edited"] is True


# ── 홈 ──

def test_home_recent_records_shape_unchanged(client, db, parent_id):
    created = [create(client, parent_id, f"기록 {n}", minutes=n) for n in range(5)]
    client.post(f"/v1/records/{created[4]}/exclude")

    recent = client.get(f"/v1/parents/{parent_id}/home").json()["data"]["recent_records"]

    assert [r["id"] for r in recent] == [created[3], created[2], created[1]]
    assert all(set(r) == set(RecordListItemOut.model_fields) for r in recent)


# ── 분류 상태 ↔ 항목 일치 (DB 검사) ──

def test_reclassify_clears_previous_classification(client, db, parent_id):
    record_id = create(client, parent_id, "밥 드셨어요")
    classify(db, record_id)

    data = client.post(f"/v1/records/{record_id}/reclassify").json()["data"]

    assert data["processing_status"] == "pending"
    assert data["classification_status"] is None and data["items"] == []
    assert ids(records(client, parent_id, "area=physical")) == []


@pytest.mark.parametrize("update", [
    # completed인데 항목 없이 classified
    "UPDATE records SET processing_status = 'completed', classification_status = 'classified', "
    "classified_by = 'ai' WHERE id = :id",
    # 분석 중인데 unclassified
    "UPDATE records SET classification_status = 'unclassified', classified_by = 'ai' WHERE id = :id",
])
def test_db_rejects_inconsistent_classification(client, db, parent_id, update):
    record_id = create(client, parent_id, "밥 드셨어요")
    connection = db.connection()

    savepoint = connection.begin_nested()
    connection.execute(text(update), {"id": record_id})
    with pytest.raises(DBAPIError, match="분류 상태 불일치"):
        connection.execute(text(
            "SET CONSTRAINTS records_classification_consistent IMMEDIATE"
        ))
    savepoint.rollback()
    db.commit()


def test_db_rejects_items_without_completed(client, db, parent_id):
    record_id = create(client, parent_id, "밥 드셨어요")
    connection = db.connection()

    savepoint = connection.begin_nested()
    connection.execute(text(
        "INSERT INTO record_items (record_id, item_code, set_by) VALUES (:id, 'phys_eating', 'ai')"
    ), {"id": record_id})
    with pytest.raises(DBAPIError, match="분류 상태 불일치"):
        connection.execute(text(
            "SET CONSTRAINTS record_items_classification_consistent IMMEDIATE"
        ))
    savepoint.rollback()
    db.commit()
