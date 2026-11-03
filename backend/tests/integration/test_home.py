"""A-1: 부모님 정보 수정·D-day·홈·기록지 제외·수정 이력·표시 이름"""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.services import dday
from tests.integration.conftest import join_family, run_sql


def today():
    return dday.today_kst()


def patch_parent(client, parent_id, body):
    return client.patch(f"/v1/parents/{parent_id}", json=body)


def create_text(client, parent_id, text="밥 드셨어요", **extra):
    response = client.post(f"/v1/parents/{parent_id}/records/text", json={"text": text, **extra})
    assert response.status_code == 201
    return response.json()["data"]["id"]


def home(client, parent_id):
    response = client.get(f"/v1/parents/{parent_id}/home")
    assert response.status_code == 200
    return response.json()["data"]


# ── 부모님 정보 수정 ──

def test_admin_updates_survey_date_and_dday(client, parent_id):
    survey = today() + timedelta(days=17)

    response = patch_parent(client, parent_id, {"survey_date": survey.isoformat(), "apply_stage": "waiting"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["survey_date"] == survey.isoformat()
    assert data["dday"] == {"survey_date": survey.isoformat(), "days_left": 17, "status": "upcoming"}


def test_postpone_and_cancel_keep_judged_date(client, parent_id):
    judged = today() - timedelta(days=30)
    patch_parent(client, parent_id, {"apply_stage": "renewal", "judged_date": judged.isoformat()})

    patch_parent(client, parent_id, {"survey_date": (today() + timedelta(days=10)).isoformat()})
    data = patch_parent(client, parent_id, {"survey_date": (today() + timedelta(days=17)).isoformat()}).json()["data"]
    assert data["dday"]["days_left"] == 17
    assert data["judged_date"] == judged.isoformat()

    data = patch_parent(client, parent_id, {"survey_date": None}).json()["data"]
    assert data["dday"]["status"] == "not_set"
    assert data["judged_date"] == judged.isoformat()
    assert data["apply_stage"] == "renewal"


def test_only_sent_fields_change(client, parent_id):
    data = patch_parent(client, parent_id, {"nickname": "  할머니  "}).json()["data"]

    assert data["nickname"] == "할머니"
    assert data["apply_stage"] == "waiting" and data["age_band"] == "80s"


@pytest.mark.parametrize("body, status, code", [
    ({}, 400, "INVALID_REQUEST"),
    ({"id": "x"}, 400, "IMMUTABLE_FIELD"),
    ({"survey_scheduled_at": None}, 400, "IMMUTABLE_FIELD"),
    ({"my_role": "admin"}, 400, "IMMUTABLE_FIELD"),
    ({"unknown": 1}, 422, "VALIDATION_ERROR"),
    ({"nickname": None}, 422, "VALIDATION_ERROR"),
    ({"apply_stage": None}, 422, "VALIDATION_ERROR"),
    ({"nickname": ""}, 422, "VALIDATION_ERROR"),
    ({"survey_date": "2026-13-01"}, 422, "VALIDATION_ERROR"),
    ({"survey_date": "2026-11-20T10:00:00"}, 422, "VALIDATION_ERROR"),
    ({"apply_stage": "survey_waiting"}, 422, "VALIDATION_ERROR"),
])
def test_update_validation(client, parent_id, body, status, code):
    response = patch_parent(client, parent_id, body)

    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_date_rules(client, parent_id):
    def iso(days):
        return (today() + timedelta(days=days)).isoformat()

    # 미래 판정일
    assert patch_parent(client, parent_id, {"judged_date": iso(1)}).status_code == 400
    # 1년 넘는 미래 조사일
    assert patch_parent(client, parent_id, {"survey_date": iso(400)}).status_code == 400
    # 판정일 < 조사일 (최종 상태 기준)
    assert patch_parent(client, parent_id, {"survey_date": iso(-5)}).status_code == 200
    response = patch_parent(client, parent_id, {"judged_date": iso(-10)})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    # 갱신 준비 → 이전 판정일 + 새 조사일 허용
    assert patch_parent(client, parent_id, {"apply_stage": "renewal", "judged_date": iso(-10)}).status_code == 200
    # 지난 조사일 허용
    assert patch_parent(client, parent_id, {"survey_date": iso(-1)}).json()["data"]["dday"]["status"] == "past"


def test_only_admin_updates(client, db, consent_docs, parent_id):
    for role in ("writer", "viewer"):
        join_family(db, client, consent_docs, parent_id, role)
        response = patch_parent(client, parent_id, {"nickname": "엄마"})
        assert response.status_code == 403


def test_other_family_parent_404(client, db, consent_docs, parent_id):
    from tests.integration.conftest import agree_all, create_auth_user

    client.login(create_auth_user(db))
    agree_all(client, consent_docs)

    assert patch_parent(client, parent_id, {"nickname": "엄마"}).status_code == 404
    assert client.get(f"/v1/parents/{parent_id}/home").status_code == 404


# ── 홈 ──

def test_home(client, db, consent_docs, parent_id):
    patch_parent(client, parent_id, {"survey_date": today().isoformat()})
    base = datetime.now(timezone.utc) - timedelta(hours=5)
    ids = [
        create_text(client, parent_id, f"기록 {i}", recorded_at=(base + timedelta(minutes=i)).isoformat())
        for i in range(5)
    ]
    client.post(f"/v1/records/{ids[4]}/exclude")
    run_sql(
        db,
        "UPDATE records SET processing_status = 'failed', processing_error = 'CLASSIFY_FAILED' WHERE id = :id",
        id=ids[3]
    )

    # 보기 전용도 조회
    join_family(db, client, consent_docs, parent_id, "viewer")
    data = home(client, parent_id)

    assert data["today"] == today().isoformat()
    assert data["parent"]["nickname"] == "엄마" and data["parent"]["my_role"] == "viewer"
    assert data["dday"]["status"] == "today"
    # 제외 X, 실패 기록 표시, 최신순
    assert [r["id"] for r in data["recent_records"]] == [ids[3], ids[2], ids[1]]
    failed = data["recent_records"][0]
    assert failed["processing_status"] == "failed"
    assert failed["processing_error"] == "CLASSIFY_FAILED"
    assert failed["stage"] == "classification"


def test_home_same_recorded_at_stable_order(client, parent_id):
    same = datetime.now(timezone.utc).isoformat()
    ids = [create_text(client, parent_id, f"같은 시각 {i}", recorded_at=same) for i in range(4)]

    first = [r["id"] for r in home(client, parent_id)["recent_records"]]
    second = [r["id"] for r in home(client, parent_id)["recent_records"]]

    assert first == second == sorted(ids, reverse=True)[:3]


def test_home_without_survey_date(client, parent_id):
    data = home(client, parent_id)

    assert data["dday"] == {"survey_date": None, "days_left": None, "status": "not_set"}
    assert data["recent_records"] == []


# ── 기록지에서 제외 ──

def test_exclude_and_include(client, parent_id):
    record_id = create_text(client, parent_id)

    for _ in range(2):
        response = client.post(f"/v1/records/{record_id}/exclude")
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "excluded"
    assert home(client, parent_id)["recent_records"] == []
    # 원문·분류 그대로
    assert client.get(f"/v1/records/{record_id}").json()["data"]["original_text"] == "밥 드셨어요"

    response = client.post(f"/v1/records/{record_id}/include")
    assert response.json()["data"]["status"] == "normal"
    assert [r["id"] for r in home(client, parent_id)["recent_records"]] == [record_id]


def test_only_author_excludes(client, db, consent_docs, parent_id):
    record_id = create_text(client, parent_id)

    join_family(db, client, consent_docs, parent_id, "writer")
    assert client.post(f"/v1/records/{record_id}/exclude").status_code == 403
    join_family(db, client, consent_docs, parent_id, "viewer")
    assert client.post(f"/v1/records/{record_id}/exclude").status_code == 403


def test_exclude_failed_record(client, db, parent_id):
    record_id = create_text(client, parent_id)
    run_sql(
        db,
        "UPDATE records SET processing_status = 'failed', processing_error = 'CLASSIFY_FAILED' WHERE id = :id",
        id=record_id
    )

    assert client.post(f"/v1/records/{record_id}/exclude").status_code == 200


# ── 수정 이력 ──

def test_versions_three_edits(client, db, parent_id):
    record_id = create_text(client, parent_id, "오늘 식사를 혼자 하셨어요.")
    run_sql(
        db,
        """
            INSERT INTO record_items (record_id, item_code, confidence, set_by)
            VALUES (:id, 'phys_eating', 0.9, 'ai')
        """,
        id=record_id
    )
    run_sql(
        db,
        """
            UPDATE records SET classification_status = 'classified', classified_by = 'ai',
                processing_status = 'completed'
            WHERE id = :id
        """,
        id=record_id
    )

    url = f"/v1/records/{record_id}"
    client.patch(url, json={"current_text": "오늘 식사를 도움받아 하셨어요."})
    client.patch(url, json={"source": "call"})
    client.patch(url, json={"item_codes": ["phys_eating", "phys_toilet_use"]})
    # 바뀐 것 없음 → 이력 X
    client.patch(url, json={"source": "call"})

    data = client.get(f"{url}/versions").json()["data"]

    assert data["original_text"] == "오늘 식사를 혼자 하셨어요."
    assert data["current"]["source"] == "call"
    assert data["current"]["classified_by"] == "user"
    assert [(h["version"], h["changed"]) for h in data["history"]] == [
        (3, ["item_codes"]), (2, ["source"]), (1, ["text"])
    ]
    v1, v2, v3 = data["history"][2], data["history"][1], data["history"][0]
    assert v1["before"]["text"] == "오늘 식사를 혼자 하셨어요."
    assert v1["before"]["classified_by"] == "ai" and v1["before"]["item_codes"] == ["phys_eating"]
    # 글 수정 → AI 분류 비움 (분류 전)
    assert v2["before"]["source"] == "direct" and v2["before"]["classified_by"] is None
    assert v3["before"]["source"] == "call" and v3["before"]["item_codes"] == []
    assert all(h["is_mine"] for h in data["history"])


def test_versions_multiple_fields_one_edit(client, parent_id):
    record_id = create_text(client, parent_id)

    client.patch(f"/v1/records/{record_id}", json={
        "current_text": "고침", "source": "call", "item_codes": []
    })

    history = client.get(f"/v1/records/{record_id}/versions").json()["data"]["history"]
    assert len(history) == 1
    assert sorted(history[0]["changed"]) == ["item_codes", "source", "text"]


def test_versions_visible_to_family_viewer(client, db, consent_docs, parent_id):
    record_id = create_text(client, parent_id)
    client.patch(f"/v1/records/{record_id}", json={"current_text": "고침"})

    join_family(db, client, consent_docs, parent_id, "viewer")
    history = client.get(f"/v1/records/{record_id}/versions").json()["data"]["history"]

    assert history[0]["is_mine"] is False


def test_version_number_unique_in_db(client, db, user_id, parent_id):
    from sqlalchemy.exc import DBAPIError

    record_id = create_text(client, parent_id)
    client.patch(f"/v1/records/{record_id}", json={"current_text": "고침"})

    with pytest.raises(DBAPIError):
        run_sql(
            db,
            """
                INSERT INTO record_versions (record_id, version, changed_fields, text, edited_by)
                VALUES (:id, 1, ARRAY['text'], 'x', :u)
            """,
            id=record_id, u=user_id
        )
    db.rollback()


# ── 표시 이름 ──

def test_display_name_and_author_name(client, db, consent_docs, parent_id):
    me = client.get("/v1/auth/me").json()["data"]
    assert me["user"]["display_name"] is None and me["onboarding"]["name_set"] is False

    record_id = create_text(client, parent_id)
    assert client.get(f"/v1/records/{record_id}").json()["data"]["author_name"] is None

    response = client.patch("/v1/auth/me", json={"display_name": "  홍길동 "})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["user"]["display_name"] == "홍길동" and data["onboarding"]["name_set"] is True

    client.patch(f"/v1/records/{record_id}", json={"current_text": "고침"})

    # 다른 가족이 볼 때 이름 표시, 이름 변경 → 과거 기록도 반영
    author_id = data["user"]["id"]
    join_family(db, client, consent_docs, parent_id, "viewer")
    assert home(client, parent_id)["recent_records"][0]["author_name"] == "홍길동"
    assert client.get(f"/v1/records/{record_id}/versions").json()["data"]["history"][0]["edited_by_name"] == "홍길동"

    client.login(author_id)
    client.patch("/v1/auth/me", json={"display_name": "길동"})
    assert client.get(f"/v1/records/{record_id}").json()["data"]["author_name"] == "길동"


@pytest.mark.parametrize("body, status", [
    ({}, 400),
    ({"display_name": None}, 422),
    ({"display_name": "   "}, 422),
    ({"display_name": "가" * 21}, 422),
    ({"phone": "010"}, 400),
    ({"nickname": "x"}, 422),
])
def test_display_name_validation(client, parent_id, body, status):
    assert client.patch("/v1/auth/me", json=body).status_code == status
