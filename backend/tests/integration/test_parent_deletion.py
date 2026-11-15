"""부모님 기록 공간 삭제 (관리자 전원 동의 → 유예 → 실행)"""
from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.services import parent_deletion_service
from tests.integration.conftest import claim_job, join_family, run_sql, sql_scalar
from tests.integration.test_voice_records import fake_storage, new_voice_record  # noqa: F401


def create_text(client, parent_id, text="밤에 현관문을 열려고 하심"):
    return client.post(f"/v1/parents/{parent_id}/records/text", json={
        "text": text, "recorded_at": datetime.now(timezone.utc).isoformat(),
    })


def status_of(client, parent_id):
    return client.get(f"/v1/parents/{parent_id}/deletion").json()["data"]


def request(client, parent_id):
    return client.post(f"/v1/parents/{parent_id}/deletion")


def error_code(response):
    return response.json()["error"]["code"]


def member_id(client, parent_id, user):
    return next(m["member_id"] for m in client.get(f"/v1/parents/{parent_id}/family").json()["data"]
                if m["user_id"] == user)


def make_due(db, parent_id):
    run_sql(
        db,
        "UPDATE parent_deletions SET scheduled_for = now() - interval '1 minute' WHERE target_parent_id = :p",
        p=parent_id
    )


# ── 요청 · 동의 · 취소 ──

def test_sole_admin_schedules_and_locks(client, db, user_id, parent_id):
    response = request(client, parent_id)
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["status"] == "scheduled"
    assert (data["admins_total"], data["admins_approved"]) == (1, 1)
    assert data["scheduled_for"] is not None

    # 읽기 전용: 기록 작성 · 부모님 정보 수정 · 초대 X / 조회 O
    assert error_code(create_text(client, parent_id)) == "PARENT_DELETION_SCHEDULED"
    response = client.patch(f"/v1/parents/{parent_id}", json={"nickname": "어머니"})
    assert error_code(response) == "PARENT_DELETION_SCHEDULED"
    assert client.get(f"/v1/parents/{parent_id}/records").status_code == 200

    # 이미 있음 → 409
    assert error_code(request(client, parent_id)) == "PARENT_DELETION_EXISTS"

    # 취소 → 다시 쓰기 가능
    assert client.delete(f"/v1/parents/{parent_id}/deletion").status_code == 204
    assert status_of(client, parent_id) is None
    assert create_text(client, parent_id).status_code == 201


def test_two_admins_need_both(client, db, consent_docs, user_id, parent_id):
    other = join_family(db, client, consent_docs, parent_id, "admin")

    client.login(user_id)
    data = request(client, parent_id).json()["data"]
    assert data["status"] == "pending"
    assert (data["admins_total"], data["admins_approved"]) == (2, 1)

    # 동의 대기 중: 기록은 가능, 가족 구성 변경 X
    assert create_text(client, parent_id).status_code == 201
    response = client.patch(f"/v1/family/{member_id(client, parent_id, other)}/role", json={"role": "writer"})
    assert error_code(response) == "PARENT_DELETION_PENDING"
    response = client.post(f"/v1/parents/{parent_id}/invites", json={"share_confirmed": True})
    assert error_code(response) == "PARENT_DELETION_PENDING"

    client.login(other)
    other_view = status_of(client, parent_id)
    assert other_view["approved_by_me"] is False
    data = client.post(f"/v1/parents/{parent_id}/deletion/approve").json()["data"]
    assert data["status"] == "scheduled"
    assert data["admins_approved"] == 2


def test_other_admin_cancels(client, db, consent_docs, user_id, parent_id):
    other = join_family(db, client, consent_docs, parent_id, "admin")
    client.login(user_id)
    request(client, parent_id)

    # 동의 대신 취소 (거절)
    client.login(other)
    assert client.delete(f"/v1/parents/{parent_id}/deletion").status_code == 204
    assert status_of(client, parent_id) is None


def test_non_admin_rules(client, db, consent_docs, user_id, parent_id):
    writer = join_family(db, client, consent_docs, parent_id, "writer")
    assert request(client, parent_id).status_code == 403
    assert status_of(client, parent_id) is None

    client.login(user_id)
    request(client, parent_id)
    client.login(writer)
    # 가족 누구나 유예 안내 조회
    assert status_of(client, parent_id)["status"] == "scheduled"
    assert client.delete(f"/v1/parents/{parent_id}/deletion").status_code == 403
    assert client.post(f"/v1/parents/{parent_id}/deletion/approve").status_code == 403


def test_pending_expires(client, db, consent_docs, user_id, parent_id):
    join_family(db, client, consent_docs, parent_id, "admin")
    client.login(user_id)
    request(client, parent_id)
    run_sql(
        db,
        "UPDATE parent_deletions SET approval_deadline = now() - interval '1 minute' WHERE target_parent_id = :p",
        p=parent_id
    )
    assert status_of(client, parent_id) is None
    assert request(client, parent_id).status_code == 201


def test_request_revokes_invites(client, db, user_id, parent_id):
    token = client.post(f"/v1/parents/{parent_id}/invites", json={"share_confirmed": True}).json()["data"]["token"]
    request(client, parent_id)
    assert client.post("/v1/invites/preview", json={"token": token}).status_code == 410


# ── 실행 ──

@pytest.fixture
def executor(fake_storage, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "DELETION_EXECUTE_ENABLED", True)
    return fake_storage


def count(db, query, **params):
    return sql_scalar(db, query, **params)


def test_execute_deletes_everything(client, db, consent_docs, user_id, parent_id, executor):
    text_id = create_text(client, parent_id).json()["data"]["id"]
    # 글 고침 → 수정 이력
    assert client.patch(f"/v1/records/{text_id}", json={"current_text": "고친 글"}).status_code == 200
    assert count(db, "SELECT count(*) FROM record_versions WHERE record_id = :a", a=text_id) > 0
    voice_id = new_voice_record(client, executor, parent_id)
    # DB 에 없는 고아 파일 (업로드만 하고 저장 안 함)
    executor.put(f"{parent_id}/{user_id}/orphan.m4a", b"x")
    other_space = client.post("/v1/parents", json={"nickname": "아버지"}).json()["data"]["id"]
    executor.put(f"{other_space}/{user_id}/keep.m4a", b"x")

    request(client, parent_id)
    make_due(db, parent_id)
    # 대기 중 받아쓰기 작업 → 워커가 안 꺼냄 (삭제 예정 공간)
    assert parent_deletion_service.run(db) == 1

    assert count(db, "SELECT count(*) FROM parents WHERE id = :p", p=parent_id) == 0
    assert count(db, "SELECT count(*) FROM records WHERE id IN (:a, :b)", a=text_id, b=voice_id) == 0
    assert count(db, "SELECT count(*) FROM record_versions WHERE record_id = :a", a=text_id) == 0
    assert count(db, "SELECT count(*) FROM jobs WHERE target_id IN (:a, :b)", a=text_id, b=voice_id) == 0
    assert count(db, "SELECT count(*) FROM audio_uploads WHERE parent_id = :p", p=parent_id) == 0
    assert count(
        db, "SELECT count(*) FROM idempotency_keys WHERE response_body -> 'data' ->> 'parent_id' = :p", p=parent_id
    ) == 0
    # 파일: 공간 폴더 전부 (고아 포함) / 다른 공간 그대로
    assert not [p for p in executor.files if p.startswith(f"{parent_id}/")]
    assert f"{other_space}/{user_id}/keep.m4a" in executor.files
    # 감사 기록: 건수만
    row = run_sql(
        db, "SELECT status, parent_id, deleted_counts FROM parent_deletions WHERE target_parent_id = :p", p=parent_id
    )[0]
    assert row.status == "completed" and row.parent_id is None
    assert row.deleted_counts["records"] == 2
    # 다른 공간·계정 그대로
    assert client.get(f"/v1/parents/{other_space}").status_code == 200


def test_execute_waits_for_running_ai_job(client, db, user_id, parent_id, executor):
    voice_id = new_voice_record(client, executor, parent_id)
    request(client, parent_id)
    make_due(db, parent_id)
    # 유예 전에 이미 실행 중이던 받아쓰기
    claim_job(db, voice_id, "transcribe_record")

    assert parent_deletion_service.run(db) == 0
    assert count(db, "SELECT count(*) FROM parents WHERE id = :p", p=parent_id) == 1
    assert count(db, "SELECT status FROM parent_deletions WHERE target_parent_id = :p", p=parent_id) == "executing"

    # 작업 끝 → 다음 실행에서 삭제
    run_sql(db, "UPDATE jobs SET status = 'completed' WHERE target_id = :id", id=voice_id)
    assert parent_deletion_service.run(db) == 1
    assert count(db, "SELECT count(*) FROM parents WHERE id = :p", p=parent_id) == 0


def test_execute_retries_after_storage_failure(client, db, user_id, parent_id, executor):
    new_voice_record(client, executor, parent_id)
    request(client, parent_id)
    make_due(db, parent_id)

    executor.fail_remove = True
    assert parent_deletion_service.run(db) == 0
    assert count(db, "SELECT count(*) FROM parents WHERE id = :p", p=parent_id) == 1

    executor.fail_remove = False
    assert parent_deletion_service.run(db) == 1
    assert count(db, "SELECT count(*) FROM parents WHERE id = :p", p=parent_id) == 0


def test_execute_disabled(client, db, user_id, parent_id, monkeypatch):
    monkeypatch.setattr(settings, "DELETION_EXECUTE_ENABLED", False)
    request(client, parent_id)
    make_due(db, parent_id)
    assert parent_deletion_service.run(db) == 0
