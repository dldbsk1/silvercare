"""내 정보 (A-5): 알림 설정 · 기기 토큰 · 동의 철회 삭제 예약 · 탈퇴 · 삭제 실행"""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.db import auth_admin, storage
from app.services import deletion_service
from tests.integration.conftest import (
    PARENT,
    agree_all,
    join_family,
    run_sql,
    sql_scalar,
)
from tests.integration.test_voice_records import FakeStorage, new_voice_record


def error_code(response):
    return response.json()["error"]["code"]


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def text_record(client, parent_id, text="밥을 혼자 드셨어요"):
    response = client.post(f"/v1/parents/{parent_id}/records/text", json={"text": text})
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def record_exists(db, record_id) -> bool:
    return sql_scalar(db, "SELECT count(*) FROM records WHERE id = :id", id=record_id) == 1


def member_id(db, parent_id, user):
    return str(sql_scalar(
        db, "SELECT id FROM family_members WHERE parent_id = :p AND user_id = :u", p=parent_id, u=user
    ))


def role_of(db, parent_id, user):
    rows = run_sql(
        db, "SELECT role::text FROM family_members WHERE parent_id = :p AND user_id = :u", p=parent_id, u=user
    )
    return rows[0][0] if rows else None


def withdraw(client, **body):
    return client.post("/v1/users/me/withdrawal", json={"confirm": True, **body})


# ── 알림 설정 ──

def test_notification_settings(client, user_id, consent_docs):
    agree_all(client, consent_docs, noti=False)

    default = client.get("/v1/settings/notifications").json()["data"]
    assert default == {
        "condition_enabled": True, "tasks_enabled": True, "briefing_enabled": True,
        "noti_consented": False,
    }

    body = {"condition_enabled": False, "tasks_enabled": True, "briefing_enabled": False}
    saved = client.put("/v1/settings/notifications", json=body)
    assert saved.status_code == 200
    assert saved.json()["data"] == {**body, "noti_consented": False}

    agree_all(client, consent_docs, noti=True)
    assert client.get("/v1/settings/notifications").json()["data"] == {**body, "noti_consented": True}


@pytest.mark.parametrize("body", [
    {"condition_enabled": True, "tasks_enabled": True},
    {"condition_enabled": True, "tasks_enabled": True, "briefing_enabled": True, "x": 1},
    {"condition_enabled": "on", "tasks_enabled": True, "briefing_enabled": True},
])
def test_notification_settings_validation(client, user_id, body):
    assert client.put("/v1/settings/notifications", json=body).status_code == 422


def test_devices(client, db, user_id, other_user_id):
    body = {"platform": "android", "push_token": "fcm-token-1"}
    first = client.post("/v1/devices", json=body).json()["data"]
    again = client.post("/v1/devices", json=body).json()["data"]
    assert first["device_id"] == again["device_id"]

    # 같은 휴대폰에서 다른 계정 로그인 → 토큰이 그 사람에게 옮겨감
    client.login(other_user_id)
    moved = client.post("/v1/devices", json={"platform": "ios", "push_token": "fcm-token-1"}).json()["data"]
    assert moved["device_id"] == first["device_id"]
    assert sql_scalar(db, "SELECT user_id FROM devices WHERE push_token = 'fcm-token-1'") is not None
    assert str(sql_scalar(db, "SELECT user_id FROM devices WHERE push_token = 'fcm-token-1'")) == other_user_id

    client.login(user_id)
    assert client.delete(f"/v1/devices/{first['device_id']}").status_code == 404

    client.login(other_user_id)
    assert client.delete(f"/v1/devices/{first['device_id']}").status_code == 204
    assert client.delete(f"/v1/devices/{first['device_id']}").status_code == 204
    assert sql_scalar(db, "SELECT revoked_at IS NOT NULL FROM devices WHERE push_token = 'fcm-token-1'")

    # 다시 등록 → 다시 켜짐
    client.post("/v1/devices", json={"platform": "ios", "push_token": "fcm-token-1"})
    assert sql_scalar(db, "SELECT revoked_at IS NULL FROM devices WHERE push_token = 'fcm-token-1'")


@pytest.mark.parametrize("body", [
    {"platform": "web", "push_token": "t"},
    {"platform": "android", "push_token": ""},
    {"platform": "android"},
])
def test_device_validation(client, user_id, body):
    assert client.post("/v1/devices", json=body).status_code == 422


# ── 동의 철회 → 삭제 예약 ──

def open_requests(db, user, request_type):
    return sql_scalar(
        db,
        """
            SELECT count(*) FROM deletion_requests
            WHERE requester_id = :u AND request_type = :t AND status IN ('requested', 'approved')
        """,
        u=user, t=request_type
    )


def test_required_revoke_schedules_deletion(client, db, user_id, consent_docs):
    agree_all(client, consent_docs)

    revoked = client.post("/v1/consents/health/revoke").json()["data"]
    scheduled = parse(revoked["deletion_scheduled_for"])
    expected = datetime.now(timezone.utc) + timedelta(days=deletion_service.GRACE_DAYS)
    assert abs(scheduled - expected) < timedelta(minutes=5)

    # 다른 필수 동의도 철회 → 예약 그대로 1건
    again = client.post("/v1/consents/privacy/revoke").json()["data"]
    assert again["deletion_scheduled_for"] == revoked["deletion_scheduled_for"]
    assert open_requests(db, user_id, "consent_withdrawal") == 1

    # 기록 기능 중지
    assert client.get("/v1/parents").status_code == 403

    # 다시 동의 → 예약 취소
    restored = agree_all(client, consent_docs).json()["data"]
    assert restored["completed"] is True
    assert restored["deletion_scheduled_for"] is None
    assert open_requests(db, user_id, "consent_withdrawal") == 0
    assert sql_scalar(
        db, "SELECT status::text FROM deletion_requests WHERE requester_id = :u", u=user_id
    ) == "cancelled"


def test_noti_revoke_no_deletion(client, db, user_id, consent_docs):
    agree_all(client, consent_docs, noti=True)
    revoked = client.post("/v1/consents/noti/revoke").json()["data"]
    assert revoked["deletion_scheduled_for"] is None
    assert open_requests(db, user_id, "consent_withdrawal") == 0


# ── 탈퇴 ──

@pytest.fixture
def three_parents(client, db, user_id, consent_docs, parent_id):
    """나 = 관리자 (가족 B writer) / 혼자 쓰는 부모님 / 다른 사람 공간의 writer"""
    shared = parent_id
    sole = client.post("/v1/parents", json={**PARENT, "nickname": "아빠"}).json()["data"]["id"]

    writer = join_family(db, client, consent_docs, shared, "writer")
    other_space = client.post("/v1/parents", json={**PARENT, "nickname": "이모"}).json()["data"]["id"]
    run_sql(
        db,
        "INSERT INTO family_members (parent_id, user_id, role) VALUES (:p, :u, 'writer')",
        p=other_space, u=user_id
    )
    client.login(user_id)
    return {"shared": shared, "sole": sole, "other_space": other_space, "writer": writer}


def test_withdrawal_check(client, db, user_id, three_parents):
    p = three_parents
    data = client.get("/v1/users/me/withdrawal-check").json()["data"]["parents"]
    by_id = {item["parent_id"]: item for item in data}

    assert by_id[p["shared"]]["status"] == "transfer_required"
    assert [c["member_id"] for c in by_id[p["shared"]]["candidates"]] == [
        member_id(db, p["shared"], p["writer"])
    ]
    assert by_id[p["sole"]]["status"] == "sole_member"
    assert by_id[p["other_space"]]["status"] == "ok"
    assert by_id[p["other_space"]]["my_role"] == "writer"
    # 잠금 순서와 같은 id 순
    assert [item["parent_id"] for item in data] == sorted(by_id)


def test_withdraw_needs_transfer_and_confirm(client, db, user_id, three_parents):
    p = three_parents
    target = member_id(db, p["shared"], p["writer"])

    missing = withdraw(client, delete_sole_parents=True)
    assert missing.status_code == 409
    assert error_code(missing) == "ADMIN_TRANSFER_REQUIRED"
    assert missing.json()["error"]["details"]["parent_ids"] == [p["shared"]]

    # 다른 부모님 가족을 받을 사람으로 → 409
    wrong = withdraw(
        client, delete_sole_parents=True,
        admin_transfers=[{"parent_id": p["shared"], "member_id": member_id(db, p["other_space"], user_id)}]
    )
    assert error_code(wrong) == "ADMIN_TRANSFER_REQUIRED"

    unconfirmed = withdraw(client, admin_transfers=[{"parent_id": p["shared"], "member_id": target}])
    assert error_code(unconfirmed) == "SOLE_MEMBER_CONFIRM_REQUIRED"
    assert unconfirmed.json()["error"]["details"]["parent_ids"] == [p["sole"]]

    # 실패 → 아무것도 안 바뀜
    assert role_of(db, p["shared"], user_id) == "admin"
    assert role_of(db, p["shared"], p["writer"]) == "writer"
    assert sql_scalar(db, "SELECT withdrawn_at IS NULL FROM users WHERE id = :u", u=user_id)


def test_withdraw_unknown_parent_400(client, db, user_id, three_parents, other_user_id):
    response = withdraw(
        client, delete_sole_parents=True,
        admin_transfers=[{"parent_id": "00000000-0000-0000-0000-000000000000",
                          "member_id": "00000000-0000-0000-0000-000000000000"}]
    )
    assert response.status_code == 400


def test_withdraw(client, db, user_id, three_parents):
    p = three_parents
    target = member_id(db, p["shared"], p["writer"])
    client.post(f"/v1/parents/{p['shared']}/invites", json={"role": "viewer", "share_confirmed": True})
    client.post(f"/v1/parents/{p['sole']}/invites", json={"role": "viewer", "share_confirmed": True})
    client.post("/v1/devices", json={"platform": "android", "push_token": "withdraw-token"})

    response = withdraw(
        client, delete_sole_parents=True,
        admin_transfers=[{"parent_id": p["shared"], "member_id": target}]
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "requested"

    # 관리자 넘김 → 나감
    assert role_of(db, p["shared"], p["writer"]) == "admin"
    assert role_of(db, p["shared"], user_id) is None
    assert role_of(db, p["other_space"], user_id) is None
    # 혼자 쓰던 공간: 실행 때까지 관계 유지 (관리자 0명 공간 X)
    assert role_of(db, p["sole"], user_id) == "admin"

    assert sql_scalar(
        db, "SELECT count(*) FROM family_invites WHERE invited_by = :u AND revoked_at IS NULL", u=user_id
    ) == 0
    assert sql_scalar(db, "SELECT revoked_at IS NOT NULL FROM devices WHERE push_token = 'withdraw-token'")

    request = run_sql(
        db,
        "SELECT request_type, parent_ids::text[] FROM deletion_requests WHERE id = :id",
        id=data["request_id"]
    )[0]
    assert request[0] == "account"
    assert request[1] == [p["sole"]]

    # 다시 요청 → 같은 결과
    again = withdraw(client)
    assert again.status_code == 200
    assert again.json()["data"] == data


def test_withdrawn_account_blocked(client, db, user_id, consent_docs, parent_id):
    response = withdraw(client, delete_sole_parents=True)
    assert response.status_code == 200

    for blocked in (
        client.get("/v1/parents"),
        client.get("/v1/consents/me"),
        client.get("/v1/settings/notifications"),
        client.get("/v1/users/me/withdrawal-check"),
    ):
        assert blocked.status_code == 403
        assert error_code(blocked) == "ACCOUNT_WITHDRAWN"

    me = client.get("/v1/auth/me").json()["data"]
    assert me["account"] == {
        "status": "withdrawn",
        "deletion_scheduled_for": response.json()["data"]["scheduled_for"],
    }


def test_simple_member_withdraws(client, db, user_id, consent_docs, parent_id):
    writer = join_family(db, client, consent_docs, parent_id, "writer")
    record_id = text_record(client, parent_id)

    assert client.get("/v1/users/me/withdrawal-check").json()["data"]["parents"][0]["status"] == "ok"
    assert withdraw(client).status_code == 200
    assert role_of(db, parent_id, writer) is None

    # 남은 기록 (삭제 실행 전) → 다른 가족에게 "탈퇴한 가족"
    client.login(user_id)
    record = client.get(f"/v1/records/{record_id}").json()["data"]
    assert record["author_name"] == "탈퇴한 가족"


def test_active_account(client, user_id, consent_docs):
    me = client.get("/v1/auth/me").json()["data"]
    assert me["account"] == {"status": "active", "deletion_scheduled_for": None}


# ── 삭제 실행 ──

@pytest.fixture
def executor(monkeypatch):
    fake = FakeStorage()
    deleted_auth = []
    monkeypatch.setattr(storage, "create_signed_upload_url", fake.sign_upload)
    monkeypatch.setattr(storage, "object_info", fake.info)
    monkeypatch.setattr(storage, "remove_objects", fake.remove)
    monkeypatch.setattr(auth_admin, "delete_user", deleted_auth.append)
    monkeypatch.setattr(settings, "DELETION_EXECUTE_ENABLED", True)
    fake.deleted_auth = deleted_auth
    return fake


def make_due(db, user):
    run_sql(
        db,
        "UPDATE deletion_requests SET scheduled_for = now() - interval '1 minute' WHERE requester_id = :u",
        u=user
    )


def request_status(db, user, request_type):
    return sql_scalar(
        db,
        """
            SELECT status::text FROM deletion_requests
            WHERE requester_id = :u AND request_type = :t
            ORDER BY requested_at DESC LIMIT 1
        """,
        u=user, t=request_type
    )


def test_execution_disabled(client, db, user_id, parent_id, monkeypatch):
    monkeypatch.setattr(settings, "DELETION_EXECUTE_ENABLED", False)
    withdraw(client, delete_sole_parents=True)
    make_due(db, user_id)

    assert deletion_service.run(db) == 0
    assert request_status(db, user_id, "account") == "requested"


def test_not_due_yet(client, db, user_id, parent_id, executor):
    withdraw(client, delete_sole_parents=True)
    assert deletion_service.run(db) == 0
    assert request_status(db, user_id, "account") == "requested"


def test_execute_account_deletion(client, db, user_id, consent_docs, three_parents, executor):
    p = three_parents
    mine = text_record(client, p["shared"], "내가 쓴 기록")
    my_voice = new_voice_record(client, executor, p["shared"])
    my_voice_path = sql_scalar(db, "SELECT audio_path FROM records WHERE id = :id", id=my_voice)
    in_sole = text_record(client, p["sole"], "혼자 쓰던 공간 기록")

    client.login(p["writer"])
    others = text_record(client, p["shared"], "다른 가족 기록")
    client.login(user_id)

    target = member_id(db, p["shared"], p["writer"])
    withdraw(client, delete_sole_parents=True, admin_transfers=[{"parent_id": p["shared"], "member_id": target}])
    make_due(db, user_id)

    assert deletion_service.run(db) == 1

    assert not record_exists(db, mine)
    assert not record_exists(db, my_voice)
    assert not record_exists(db, in_sole)
    assert record_exists(db, others)
    assert my_voice_path in executor.removed
    assert sql_scalar(db, "SELECT count(*) FROM parents WHERE id = :p", p=p["sole"]) == 0
    assert sql_scalar(db, "SELECT count(*) FROM parents WHERE id = :p", p=p["shared"]) == 1
    assert sql_scalar(db, "SELECT count(*) FROM audio_uploads WHERE user_id = :u AND record_id IS NOT NULL", u=user_id) == 0

    assert executor.deleted_auth == [user_id]
    assert sql_scalar(db, "SELECT display_name IS NULL AND phone IS NULL FROM users WHERE id = :u", u=user_id)
    # 동의 이력 유지
    assert sql_scalar(db, "SELECT count(*) FROM consents WHERE user_id = :u", u=user_id) > 0
    assert request_status(db, user_id, "account") == "completed"

    # 다시 실행 → 할 일 없음
    assert deletion_service.run(db) == 0


def test_execution_retries_after_storage_failure(client, db, user_id, parent_id, executor):
    voice = new_voice_record(client, executor, parent_id)
    withdraw(client, delete_sole_parents=True)
    make_due(db, user_id)

    executor.fail_remove = True
    assert deletion_service.run(db) == 0
    assert request_status(db, user_id, "account") == "approved"
    assert record_exists(db, voice)
    assert executor.deleted_auth == []

    executor.fail_remove = False
    assert deletion_service.run(db) == 1
    assert request_status(db, user_id, "account") == "completed"
    assert not record_exists(db, voice)


def test_execute_consent_withdrawal(client, db, user_id, consent_docs, parent_id, executor):
    writer = join_family(db, client, consent_docs, parent_id, "writer")
    writers_record = text_record(client, parent_id)
    client.login(user_id)
    mine = text_record(client, parent_id)

    client.login(writer)
    client.post("/v1/consents/health/revoke")
    make_due(db, writer)

    assert deletion_service.run(db) == 1
    assert not record_exists(db, writers_record)
    assert record_exists(db, mine)
    # 계정·가족 관계 유지 (기록만 삭제)
    assert role_of(db, parent_id, writer) == "writer"
    assert executor.deleted_auth == []
    assert request_status(db, writer, "consent_withdrawal") == "completed"


def test_approved_request_not_cancelled_by_reagree(client, db, user_id, consent_docs, parent_id, executor):
    client.post("/v1/consents/health/revoke")
    make_due(db, user_id)
    run_sql(db, "UPDATE deletion_requests SET status = 'approved' WHERE requester_id = :u", u=user_id)

    agree_all(client, consent_docs)
    assert request_status(db, user_id, "consent_withdrawal") == "approved"
