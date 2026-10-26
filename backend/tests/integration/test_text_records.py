"""2단계 텍스트 기록 (A-HOME-002~005, A-HOME-009, A-DET-001/002)"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import DBAPIError

from app.ai.interfaces import ItemClassification
from app.workers.tasks import JobSuperseded
from app.workers.tasks import records as record_tasks
from tests.integration.conftest import join_family, run_sql, sql_scalar


def create(client, parent_id, text="식사: 반찬을 작게 잘라 드려야 드셨어요.", **extra):
    return client.post(
        f"/v1/parents/{parent_id}/records/text", json={"text": text, **extra}
    )


def jobs_of(db, record_id):
    return run_sql(
        db,
        """
            SELECT status, payload->>'text_version' AS version
            FROM jobs WHERE target_type = 'record' AND target_id = :id
            ORDER BY (payload->>'text_version')::int, created_at
        """,
        id=record_id
    )


def payload(record_id, version):
    return {"record_id": record_id, "text_version": version}


def run_classify(db, record_id, version):
    record_tasks.classify_record(db, payload(record_id, version))


def processing(client, record_id):
    return client.get(f"/v1/records/{record_id}/processing").json()["data"]


def iso(dt):
    return dt.isoformat()


# ── 작성 ──

def test_create_saves_original_and_queues_job(client, db, parent_id):
    response = create(client, parent_id)

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["original_text"] == data["current_text"] == "식사: 반찬을 작게 잘라 드려야 드셨어요."
    assert data["source"] == "direct"
    assert data["processing_status"] == "pending"
    assert data["classification_status"] is None
    assert data["text_version"] == 1
    assert data["is_mine"] is True and data["items"] == []
    assert [tuple(j) for j in jobs_of(db, data["id"])] == [("queued", "1")]


@pytest.mark.parametrize("text, status", [
    ("   ", 422),
    ("", 422),
    ("가" * 1001, 422),
    ("가" * 1000, 201),
    ("  앞뒤 공백  ", 201),
])
def test_text_length(client, parent_id, text, status):
    response = create(client, parent_id, text)

    assert response.status_code == status
    if status == 201:
        assert response.json()["data"]["current_text"] == text.strip()


@pytest.mark.parametrize("source, status", [
    ("call", 201), ("direct", 201), ("kakao", 422), ("phone", 422),
])
def test_source(client, parent_id, source, status):
    assert create(client, parent_id, source=source).status_code == status


def test_time_rules(client, parent_id):
    now = datetime.now(timezone.utc)

    assert create(client, parent_id, recorded_at="2026-10-25T10:20:00").status_code == 422
    assert create(client, parent_id, recorded_at=iso(now + timedelta(hours=1))).status_code == 400
    assert create(
        client, parent_id,
        recorded_at=iso(now), occurred_at=iso(now + timedelta(hours=1))
    ).status_code == 400
    # 오프라인 기록: 과거 시각 허용
    response = create(
        client, parent_id,
        recorded_at=iso(now - timedelta(days=3)),
        occurred_at=iso(now - timedelta(days=3, hours=2))
    )
    assert response.status_code == 201


def test_permissions(client, db, consent_docs, parent_id):
    join_family(db, client, consent_docs, parent_id, "viewer")
    response = create(client, parent_id)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"

    join_family(db, client, consent_docs, parent_id, "writer")
    assert create(client, parent_id).status_code == 201


def test_other_family_and_consent(client, db, user_id, other_user_id, consent_docs, parent_id):
    client.post("/v1/consents/health/revoke")
    response = create(client, parent_id)
    assert response.json()["error"]["code"] == "CONSENT_REQUIRED"

    client.login(other_user_id)
    from tests.integration.conftest import agree_all
    agree_all(client, consent_docs)
    assert create(client, parent_id).status_code == 404


# ── Idempotency-Key ──

def test_idempotent_create(client, db, parent_id):
    headers = {"Idempotency-Key": "offline-1"}
    body = {"text": "밥을 반 공기 드셨어요."}
    url = f"/v1/parents/{parent_id}/records/text"

    first = client.post(url, json=body, headers=headers)
    second = client.post(url, json=body, headers=headers)

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert sql_scalar(db, "SELECT count(*) FROM records WHERE parent_id = :p", p=parent_id) == 1
    assert sql_scalar(db, "SELECT count(*) FROM jobs WHERE type = 'classify_record' AND target_id = :id",
                      id=first.json()["data"]["id"]) == 1

    conflict = client.post(url, json={"text": "다른 내용"}, headers=headers)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_concurrent_same_key_is_409(client, db, user_id, parent_id):
    """첫 요청 처리 중(processing) 상태에서 같은 키 도착 → 409, 기록 생성 안 함"""
    run_sql(
        db,
        """
            INSERT INTO idempotency_keys (user_id, endpoint, key, request_hash, expires_at)
            VALUES (:u, 'POST /v1/parents/{parent_id}/records/text', 'k-busy', 'x', now() + interval '1 day')
        """,
        u=user_id
    )

    response = client.post(
        f"/v1/parents/{parent_id}/records/text",
        json={"text": "밥"}, headers={"Idempotency-Key": "k-busy"}
    )

    assert response.status_code == 409
    assert sql_scalar(db, "SELECT count(*) FROM records WHERE parent_id = :p", p=parent_id) == 0


# ── AI 분류 (Mock) ──

def test_mock_codes_exist_in_db(db):
    from app.ai.mock import KEYWORDS
    from app.repositories import survey_repo

    codes = set(KEYWORDS)
    assert codes <= survey_repo.all_codes(db)


def test_classify_with_mock(client, db, parent_id):
    record_id = create(client, parent_id, "식사는 혼자 하셨는데 화장실에서 넘어질 뻔").json()["data"]["id"]

    run_classify(db, record_id, 1)

    data = processing(client, record_id)
    assert data["processing_status"] == "completed"
    assert data["classification_status"] == "classified"
    assert data["classified_by"] == "ai"
    assert [(i["area"], i["item_code"], i["label"]) for i in data["items"]] == [
        ("physical", "phys_eating", "식사하기"),
        ("physical", "phys_toilet_use", "화장실 사용하기"),
    ]


@pytest.mark.parametrize("text", ["오늘 날씨가 좋네요", "[ai-low] 밥", "[ai-invalid] 밥"])
def test_unclassified_results(client, db, parent_id, text):
    record_id = create(client, parent_id, text).json()["data"]["id"]

    run_classify(db, record_id, 1)

    data = processing(client, record_id)
    assert data["processing_status"] == "completed"
    assert data["classification_status"] == "unclassified"
    assert data["items"] == []


def test_duplicate_job_run_no_duplicates(client, db, parent_id):
    record_id = create(client, parent_id, "밥 드시고 양치").json()["data"]["id"]

    run_classify(db, record_id, 1)
    run_classify(db, record_id, 1)

    assert sql_scalar(db, "SELECT count(*) FROM record_items WHERE record_id = :id", id=record_id) == 2


def test_ai_failure_keeps_original_then_reclassify(client, db, parent_id):
    record_id = create(client, parent_id, "[ai-fail] 밥").json()["data"]["id"]

    with pytest.raises(RuntimeError):
        run_classify(db, record_id, 1)
    assert processing(client, record_id)["processing_status"] == "processing"

    # 재시도 소진 → on_failure
    record_tasks.mark_record_failed(db, payload(record_id, 1))
    data = processing(client, record_id)
    assert data["processing_status"] == "failed"
    assert data["original_text"] == "[ai-fail] 밥"

    response = client.post(f"/v1/records/{record_id}/reclassify")
    assert response.status_code == 202
    assert response.json()["data"]["processing_status"] == "pending"
    assert len(jobs_of(db, record_id)) == 2

    # 분석 중 재요청 → 409
    assert client.post(f"/v1/records/{record_id}/reclassify").status_code == 409


# ── 버전 (text_version) ──

def test_text_version_only_by_trigger(client, db, parent_id):
    record_id = create(client, parent_id).json()["data"]["id"]

    run_sql(db, "UPDATE records SET text_version = 99 WHERE id = :id", id=record_id)
    assert sql_scalar(db, "SELECT text_version FROM records WHERE id = :id", id=record_id) == 1

    run_sql(db, "UPDATE records SET processing_status = 'processing' WHERE id = :id", id=record_id)
    assert sql_scalar(db, "SELECT text_version FROM records WHERE id = :id", id=record_id) == 1

    run_sql(db, "UPDATE records SET current_text = '바뀜' WHERE id = :id", id=record_id)
    assert sql_scalar(db, "SELECT text_version FROM records WHERE id = :id", id=record_id) == 2


def test_edit_during_classification_supersedes_old_job(client, db, parent_id):
    record_id = create(client, parent_id, "밥 드셨어요").json()["data"]["id"]
    run_classify(db, record_id, 1)

    response = client.patch(f"/v1/records/{record_id}", json={"current_text": "현관문을 열려고 하셨어요"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["text_version"] == 2
    assert data["processing_status"] == "pending"
    # 이전 버전 분류 → 최신처럼 표시 금지
    assert data["items"] == [] and data["classification_status"] is None
    assert [j.version for j in jobs_of(db, record_id)] == ["1", "2"]

    # 이전 버전 작업이 늦게 실행/실패 → 결과 버림, 상태 변경 없음
    with pytest.raises(JobSuperseded):
        run_classify(db, record_id, 1)
    record_tasks.mark_record_failed(db, payload(record_id, 1))
    assert processing(client, record_id)["processing_status"] == "pending"

    run_classify(db, record_id, 2)
    data = processing(client, record_id)
    assert data["processing_status"] == "completed"
    assert [i["item_code"] for i in data["items"]] == ["beh_going_out"]


def test_stale_result_discarded_when_text_changes_mid_ai_call(client, db, parent_id, monkeypatch):
    """AI 호출 도중 글이 바뀜 → 저장 단계에서 버전 불일치 → superseded"""
    record_id = create(client, parent_id, "밥").json()["data"]["id"]

    class EditingClassifier:
        def classify(self, text):
            run_sql(db, "UPDATE records SET current_text = '수정됨' WHERE id = :id", id=record_id)
            return [ItemClassification(item_code="phys_eating", confidence=0.9)]

    monkeypatch.setattr(record_tasks, "get_record_classifier", lambda: EditingClassifier())

    with pytest.raises(JobSuperseded):
        run_classify(db, record_id, 1)
    assert sql_scalar(db, "SELECT count(*) FROM record_items WHERE record_id = :id", id=record_id) == 0


# ── 수정 (작성자·사용자 분류) ──

def test_edit_keeps_original_and_history(client, db, parent_id):
    record_id = create(client, parent_id, "원래 글").json()["data"]["id"]

    data = client.patch(f"/v1/records/{record_id}", json={"current_text": "고친 글", "source": "call"}).json()["data"]

    assert data["original_text"] == "원래 글"
    assert data["current_text"] == "고친 글"
    assert data["source"] == "call"
    assert data["is_edited"] is True
    history = run_sql(db, "SELECT text, source_snapshot::text FROM record_versions WHERE record_id = :id", id=record_id)
    assert [tuple(h) for h in history] == [("원래 글", "direct")]


def test_user_classification_priority(client, db, parent_id):
    record_id = create(client, parent_id, "밥 드셨어요").json()["data"]["id"]
    run_classify(db, record_id, 1)

    data = client.patch(f"/v1/records/{record_id}", json={"item_codes": ["cog_short_memory", "phys_eating"]}).json()["data"]
    assert data["classified_by"] == "user"
    assert data["processing_status"] == "completed"
    assert {(i["item_code"], i["set_by"]) for i in data["items"]} == {
        ("cog_short_memory", "user"), ("phys_eating", "user")
    }

    # 글을 고쳐도 사용자 분류 유지, AI 작업 없음
    data = client.patch(f"/v1/records/{record_id}", json={"current_text": "현관"}).json()["data"]
    assert data["classified_by"] == "user" and len(data["items"]) == 2
    assert len(jobs_of(db, record_id)) == 1

    # 남아 있던 AI 작업 → 사용자 분류 덮어쓰기 금지
    with pytest.raises(JobSuperseded):
        run_classify(db, record_id, 2)

    response = client.post(f"/v1/records/{record_id}/reclassify")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "USER_CLASSIFIED"


def test_user_can_choose_unclassified(client, parent_id):
    record_id = create(client, parent_id).json()["data"]["id"]

    data = client.patch(f"/v1/records/{record_id}", json={"item_codes": []}).json()["data"]

    assert data["classification_status"] == "unclassified"
    assert data["classified_by"] == "user"


def test_user_classification_only_from_52_items(client, parent_id):
    record_id = create(client, parent_id).json()["data"]["id"]

    response = client.patch(f"/v1/records/{record_id}", json={"item_codes": ["phys_eating", "감정"]})

    assert response.status_code == 400
    assert response.json()["error"]["details"] == {"unknown_codes": ["감정"]}


@pytest.mark.parametrize("body, status, code", [
    ({"original_text": "조작"}, 400, "IMMUTABLE_FIELD"),
    ({"recorded_at": "2026-10-01T00:00:00+09:00"}, 400, "IMMUTABLE_FIELD"),
    ({"text_version": 5}, 400, "IMMUTABLE_FIELD"),
    ({"unknown": 1}, 422, "VALIDATION_ERROR"),
    ({}, 400, "INVALID_REQUEST"),
    ({"current_text": None}, 422, "VALIDATION_ERROR"),
    ({"current_text": "   "}, 422, "VALIDATION_ERROR"),
])
def test_update_validation(client, parent_id, body, status, code):
    record_id = create(client, parent_id).json()["data"]["id"]

    response = client.patch(f"/v1/records/{record_id}", json=body)

    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_only_author_can_edit_or_reclassify(client, db, consent_docs, parent_id):
    record_id = create(client, parent_id).json()["data"]["id"]

    join_family(db, client, consent_docs, parent_id, "admin")

    assert client.get(f"/v1/records/{record_id}").status_code == 200
    assert client.patch(f"/v1/records/{record_id}", json={"current_text": "남이 고침"}).status_code == 403
    record_tasks.mark_record_failed(db, payload(record_id, 1))
    assert client.post(f"/v1/records/{record_id}/reclassify").status_code == 403


def test_original_text_protected_by_db(client, db, parent_id):
    record_id = create(client, parent_id).json()["data"]["id"]

    with pytest.raises(DBAPIError):
        run_sql(db, "UPDATE records SET original_text = '조작' WHERE id = :id", id=record_id)
    db.rollback()

    assert sql_scalar(db, "SELECT original_text FROM records WHERE id = :id", id=record_id) \
        == "식사: 반찬을 작게 잘라 드려야 드셨어요."


# ── 조회 ──

def test_recent_three_normal_only(client, db, parent_id):
    base = datetime.now(timezone.utc) - timedelta(hours=10)
    ids = [
        create(client, parent_id, f"기록 {n}", recorded_at=iso(base + timedelta(hours=n))).json()["data"]["id"]
        for n in range(5)
    ]
    run_sql(db, "UPDATE records SET status = 'excluded' WHERE id = :id", id=ids[4])

    data = client.get(f"/v1/parents/{parent_id}/records?status=normal&limit=3").json()["data"]

    assert [r["current_text"] for r in data] == ["기록 3", "기록 2", "기록 1"]
    assert all(r["status"] == "normal" for r in data)

    all_records = client.get(f"/v1/parents/{parent_id}/records").json()["data"]
    assert len(all_records) == 5


def test_list_areas_and_empty(client, db, parent_id):
    assert client.get(f"/v1/parents/{parent_id}/records?limit=3").json()["data"] == []

    record_id = create(client, parent_id, "기억을 못 하시고 밥도 안 드심").json()["data"]["id"]
    run_classify(db, record_id, 1)

    item = client.get(f"/v1/parents/{parent_id}/records?limit=3").json()["data"][0]
    assert item["areas"] == ["physical", "cognitive"]

    for limit in (0, 101):
        assert client.get(f"/v1/parents/{parent_id}/records?limit={limit}").status_code == 422


def test_detail_hidden_from_other_family(client, db, other_user_id, consent_docs, parent_id):
    record_id = create(client, parent_id).json()["data"]["id"]

    assert client.get("/v1/records/00000000-0000-0000-0000-000000000000").status_code == 404

    client.login(other_user_id)
    from tests.integration.conftest import agree_all
    agree_all(client, consent_docs)
    assert client.get(f"/v1/records/{record_id}").status_code == 404
    assert client.get(f"/v1/records/{record_id}/processing").status_code == 404
