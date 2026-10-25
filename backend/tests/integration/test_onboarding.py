"""1단계 가입 흐름: 동의 → 부모님 등록 (A-ON-002, A-ON-003, A-SET-001)"""
from tests.integration.conftest import agree_all, run_sql, sql_scalar


PARENT = {"nickname": "엄마", "age_band": "80s", "apply_stage": "waiting", "cohabiting": False}


def error_code(response):
    return response.json()["error"]["code"]


# ── /auth/me ──

def test_new_user_onboarding_state(client, user_id, consent_docs):
    response = client.get("/v1/auth/me")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["user"] == {"id": user_id, "login_type": "email"}
    assert data["onboarding"] == {
        "consents_completed": False,
        "missing_consents": ["health", "privacy", "service"],
        "parent_registered": False,
    }
    assert data["parent_ids"] == []


# ── 동의 ──

def test_required_documents(client, user_id, consent_docs):
    response = client.get("/v1/consents/required")

    docs = {d["type"]: d for d in response.json()["data"]}
    assert set(docs) == {"service", "privacy", "health", "noti"}
    assert docs["health"]["required"] is True
    assert docs["noti"]["required"] is False
    assert docs["service"]["doc_version"] == consent_docs


def test_agree_all_completes_onboarding_step(client, user_id, consent_docs):
    response = agree_all(client, consent_docs)

    assert response.status_code == 200
    assert response.json()["data"]["completed"] is True
    me = client.get("/v1/auth/me").json()["data"]
    assert me["onboarding"]["consents_completed"] is True


def test_resubmitting_same_consent_does_not_duplicate(client, user_id, consent_docs, db):
    agree_all(client, consent_docs)
    agree_all(client, consent_docs)

    count = sql_scalar(db, "SELECT count(*) FROM consents WHERE user_id = :u", u=user_id)
    assert count == 4


def test_unknown_doc_version_rejected(client, user_id, consent_docs):
    response = client.post("/v1/consents", json={"items": [
        {"type": "service", "doc_version": "made-up", "agreed": True}
    ]})

    assert response.status_code == 400


def test_required_disagree_rejected(client, user_id, consent_docs):
    response = client.post("/v1/consents", json={"items": [
        {"type": "health", "doc_version": consent_docs, "agreed": False}
    ]})

    assert response.status_code == 403
    assert error_code(response) == "CONSENT_REQUIRED"


def test_duplicate_type_is_validation_error(client, user_id, consent_docs):
    item = {"type": "noti", "doc_version": consent_docs, "agreed": True}

    response = client.post("/v1/consents", json={"items": [item, item]})

    assert response.status_code == 422


def test_optional_disagree_revokes(client, user_id, consent_docs):
    agree_all(client, consent_docs, noti=True)

    client.post("/v1/consents", json={"items": [
        {"type": "noti", "doc_version": consent_docs, "agreed": False}
    ]})

    data = client.get("/v1/consents/me").json()["data"]
    assert "noti" not in {c["type"] for c in data["current"]}
    assert data["completed"] is True
    noti_history = [h for h in data["history"] if h["type"] == "noti"]
    assert noti_history[0]["revoked_at"] is not None


def test_revoke_required_blocks_parent_access(client, user_id, consent_docs):
    agree_all(client, consent_docs)
    parent_id = client.post("/v1/parents", json=PARENT).json()["data"]["id"]

    response = client.post("/v1/consents/health/revoke")
    assert response.status_code == 200
    assert response.json()["data"]["missing_required"] == ["health"]

    response = client.get(f"/v1/parents/{parent_id}")
    assert response.status_code == 403
    assert error_code(response) == "CONSENT_REQUIRED"

    # 이미 철회한 동의를 또 철회
    assert client.post("/v1/consents/health/revoke").status_code == 404


def test_new_document_version_requires_reconsent(client, user_id, consent_docs, db):
    agree_all(client, consent_docs)

    run_sql(db, """
        INSERT INTO consent_documents (type, doc_version, title, content, published_at)
        VALUES ('health', 'test-2', '바뀐 문구', '바뀐 문구', now() - interval '30 seconds')
    """)

    data = client.get("/v1/consents/me").json()["data"]
    assert data["completed"] is False
    assert data["missing_required"] == ["health"]
    health = next(c for c in data["current"] if c["type"] == "health")
    assert health["is_latest"] is False

    client.post("/v1/consents", json={"items": [
        {"type": "health", "doc_version": "test-2", "agreed": True}
    ]})
    assert client.get("/v1/consents/me").json()["data"]["completed"] is True


# ── 부모님 등록 ──

def test_parent_requires_consent(client, user_id, consent_docs):
    response = client.post("/v1/parents", json=PARENT)

    assert response.status_code == 403
    assert error_code(response) == "CONSENT_REQUIRED"


def test_create_parent_makes_admin(client, user_id, consent_docs):
    agree_all(client, consent_docs)

    response = client.post("/v1/parents", json=PARENT)

    assert response.status_code == 201
    parent = response.json()["data"]
    assert parent["my_role"] == "admin"
    assert parent["nickname"] == "엄마"
    assert parent["apply_stage"] == "waiting"

    assert client.get(f"/v1/parents/{parent['id']}").status_code == 200
    assert [p["id"] for p in client.get("/v1/parents").json()["data"]] == [parent["id"]]

    me = client.get("/v1/auth/me").json()["data"]
    assert me["onboarding"]["parent_registered"] is True
    assert me["parent_ids"] == [parent["id"]]


def test_create_parent_idempotent(client, user_id, consent_docs, db):
    agree_all(client, consent_docs)
    headers = {"Idempotency-Key": "onboarding-1"}

    first = client.post("/v1/parents", json=PARENT, headers=headers)
    second = client.post("/v1/parents", json=PARENT, headers=headers)

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    count = sql_scalar(
        db, "SELECT count(*) FROM family_members WHERE user_id = :u", u=user_id
    )
    assert count == 1


def test_parent_validation(client, user_id, consent_docs):
    agree_all(client, consent_docs)

    for body in [
        {**PARENT, "nickname": "   "},
        {**PARENT, "nickname": "가" * 21},
        {**PARENT, "age_band": "50s"},
        {**PARENT, "apply_stage": "survey_waiting"},
    ]:
        response = client.post("/v1/parents", json=body)
        assert response.status_code == 422, body


def test_identity_fields_are_not_stored(client, user_id, consent_docs, db):
    """POL-07: 이름·주민번호를 보내도 저장하지 않는다"""
    agree_all(client, consent_docs)

    response = client.post(
        "/v1/parents",
        json={**PARENT, "name": "홍길동", "resident_number": "400101-2000000"}
    )

    assert response.status_code == 201
    row = sql_scalar(
        db, "SELECT to_jsonb(p)::text FROM parents p WHERE id = :id",
        id=response.json()["data"]["id"]
    )
    assert "홍길동" not in row and "400101" not in row


def test_other_family_cannot_see_parent(client, user_id, other_user_id, consent_docs):
    agree_all(client, consent_docs)
    parent_id = client.post("/v1/parents", json=PARENT).json()["data"]["id"]

    client.login(other_user_id)
    agree_all(client, consent_docs)

    response = client.get(f"/v1/parents/{parent_id}")
    assert response.status_code == 404
    assert client.get("/v1/parents").json()["data"] == []


# ── 운영 환경에서 개발용 문구 차단 ──

def test_production_ignores_dev_documents(client, user_id, db, monkeypatch):
    from app.core.config import settings

    run_sql(db, "UPDATE consent_documents SET retired_at = now() WHERE retired_at IS NULL")
    run_sql(db, """
        INSERT INTO consent_documents (type, doc_version, title, content, published_at)
        VALUES ('service', 'dev-9', '개발용', '개발용', now() - interval '1 minute')
    """)
    monkeypatch.setattr(settings, "ENV", "production")

    assert client.get("/v1/consents/required").json()["data"] == []

    response = client.post("/v1/consents", json={"items": [
        {"type": "service", "doc_version": "dev-9", "agreed": True}
    ]})
    assert response.status_code == 400

    # 필수 문구가 발행되지 않았으면 누구도 동의 완료가 아니다
    me = client.get("/v1/auth/me").json()["data"]
    assert me["onboarding"]["consents_completed"] is False
