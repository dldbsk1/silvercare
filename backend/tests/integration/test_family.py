"""가족 (A-3): 초대 · 미리보기 · 수락 · 구성원 · 역할 · 내보내기 · 마지막 관리자"""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.services import family_service
from tests.integration.conftest import (
    PARENT,
    agree_all,
    create_auth_user,
    join_family,
    run_sql,
    sql_scalar,
)


SHARE_VERSION = "test-share-1"


@pytest.fixture
def share_doc(db, consent_docs):
    """가족 공유 동의 문서 (이 트랜잭션 안에서만)

    consent_docs 다음 실행 고정 (consent_docs가 유효 문서 전부 폐기)
    """
    run_sql(db, "UPDATE consent_documents SET retired_at = now() WHERE type = 'family_share' AND retired_at IS NULL")
    run_sql(
        db,
        """
            INSERT INTO consent_documents (type, doc_version, title, content, required, published_at)
            VALUES ('family_share', :v, '가족 공유', '공유 문구', false, now() - interval '1 minute')
        """,
        v=SHARE_VERSION
    )
    return SHARE_VERSION


@pytest.fixture
def admin_id(user_id, parent_id):
    return user_id


def invite(client, parent_id, role="writer", **extra):
    return client.post(
        f"/v1/parents/{parent_id}/invites",
        json={"role": role, "share_confirmed": True, **extra}
    )


def new_token(client, parent_id, role="writer"):
    return invite(client, parent_id, role).json()["data"]["token"]


def preview(client, token):
    return client.post("/v1/invites/preview", json={"token": token})


def accept(client, token, version=SHARE_VERSION):
    return client.post("/v1/invites/accept", json={"token": token, "share_doc_version": version})


def new_user(db, client, consent_docs, consented=True):
    user = create_auth_user(db)
    client.login(user)
    if consented:
        agree_all(client, consent_docs)
    return user


def members(client, parent_id):
    return client.get(f"/v1/parents/{parent_id}/family").json()["data"]


def member_id_of(client, parent_id, user):
    return next(m["member_id"] for m in members(client, parent_id) if m["user_id"] == user)


def error_code(response):
    return response.json()["error"]["code"]


def join_by_invite(db, client, consent_docs, parent_id, admin, role="writer"):
    """관리자로 초대 → 새 사용자 수락. 새 사용자로 로그인된 상태"""
    client.login(admin)
    token = new_token(client, parent_id, role)
    user = new_user(db, client, consent_docs)
    assert accept(client, token).status_code == 200
    return user


# ── 초대 만들기 ──

def test_create_invite(client, db, admin_id, parent_id):
    response = invite(client, parent_id, "viewer")

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["role"] == "viewer"
    assert data["invite_url"].endswith(f"#t={data['token']}")
    assert "?" not in data["invite_url"]
    # DB엔 해시만
    assert sql_scalar(db, "SELECT count(*) FROM family_invites WHERE token_hash = :t", t=data["token"]) == 0
    assert sql_scalar(
        db, "SELECT count(*) FROM family_invites WHERE token_hash = :h",
        h=family_service.hash_token(data["token"])
    ) == 1


@pytest.mark.parametrize("body", [
    {"role": "admin", "share_confirmed": True},
    {"role": "writer"},
    {"role": "writer", "share_confirmed": False},
    {"role": "writer", "share_confirmed": True, "extra": 1},
])
def test_create_invite_validation(client, parent_id, body):
    assert client.post(f"/v1/parents/{parent_id}/invites", json=body).status_code == 422


def test_only_admin_creates_invite(client, db, consent_docs, parent_id):
    join_family(db, client, consent_docs, parent_id, "writer")
    assert invite(client, parent_id).status_code == 403


def test_active_invite_limit(client, db, parent_id):
    for _ in range(10):
        assert invite(client, parent_id).status_code == 201

    response = invite(client, parent_id)
    assert response.status_code == 409 and error_code(response) == "INVITE_LIMIT"

    # 만료된 초대는 개수에서 제외
    run_sql(
        db,
        """
            UPDATE family_invites
            SET created_at = now() - interval '8 days', expires_at = now() - interval '1 day'
            WHERE parent_id = :p
        """,
        p=parent_id
    )
    assert invite(client, parent_id).status_code == 201


def test_list_and_revoke(client, db, admin_id, parent_id):
    invite_id = invite(client, parent_id).json()["data"]["invite_id"]
    listed = client.get(f"/v1/parents/{parent_id}/invites").json()["data"]
    assert [i["invite_id"] for i in listed] == [invite_id]
    assert "token" not in listed[0]

    assert client.delete(f"/v1/invites/{invite_id}").status_code == 204
    # 이미 취소 → 그대로
    assert client.delete(f"/v1/invites/{invite_id}").status_code == 204
    assert client.get(f"/v1/parents/{parent_id}/invites").json()["data"] == []


def test_revoke_rules(client, db, consent_docs, share_doc, admin_id, parent_id):
    token = new_token(client, parent_id)
    used_id = client.get(f"/v1/parents/{parent_id}/invites").json()["data"][0]["invite_id"]
    new_user(db, client, consent_docs)
    accept(client, token)

    client.login(admin_id)
    response = client.delete(f"/v1/invites/{used_id}")
    assert response.status_code == 409 and error_code(response) == "INVITE_USED"

    open_id = invite(client, parent_id).json()["data"]["invite_id"]
    # 다른 가족 → 404, 쓰기 권한 가족 → 403
    new_user(db, client, consent_docs)
    assert client.delete(f"/v1/invites/{open_id}").status_code == 404
    join_family(db, client, consent_docs, parent_id, "writer")
    assert client.delete(f"/v1/invites/{open_id}").status_code == 403


# ── 미리보기 ──

def test_preview_fields_only(client, db, consent_docs, share_doc, admin_id, parent_id):
    client.patch("/v1/auth/me", json={"display_name": "홍길동"})
    token = new_token(client, parent_id)

    # 동의 전에도 가능 (로그인만)
    new_user(db, client, consent_docs, consented=False)
    response = preview(client, token)

    assert response.status_code == 200
    data = response.json()["data"]
    assert set(data) == {
        "inviter_name", "parent_nickname", "role", "expires_at", "already_member", "share_document"
    }
    assert data["inviter_name"] == "홍길동" and data["parent_nickname"] == PARENT["nickname"]
    assert data["role"] == "writer" and data["already_member"] is False
    assert data["share_document"]["doc_version"] == SHARE_VERSION


def test_preview_states(client, db, consent_docs, share_doc, admin_id, parent_id):
    assert error_code(preview(client, "nope")) == "INVITE_NOT_FOUND"

    # 관리자 본인 → 이미 가족
    token = new_token(client, parent_id)
    assert preview(client, token).json()["data"]["already_member"] is True

    revoked = invite(client, parent_id).json()["data"]
    client.delete(f"/v1/invites/{revoked['invite_id']}")
    response = preview(client, revoked["token"])
    assert response.status_code == 410 and error_code(response) == "INVITE_REVOKED"

    expired = new_token(client, parent_id)
    run_sql(
        db,
        """
            UPDATE family_invites
            SET created_at = now() - interval '8 days', expires_at = now() - interval '1 day'
            WHERE token_hash = :h
        """,
        h=family_service.hash_token(expired)
    )
    response = preview(client, expired)
    assert response.status_code == 410 and error_code(response) == "INVITE_EXPIRED"


def test_preview_without_share_document(client, db, admin_id, parent_id):
    token = new_token(client, parent_id)
    run_sql(db, "UPDATE consent_documents SET retired_at = now() WHERE type = 'family_share'")

    response = preview(client, token)
    assert response.status_code == 503


def test_preview_rate_limited(client, share_doc, admin_id, parent_id):
    token = new_token(client, parent_id)

    for _ in range(20):
        assert preview(client, token).status_code == 200
    response = preview(client, token)

    assert response.status_code == 429 and error_code(response) == "RATE_LIMITED"
    assert int(response.headers["Retry-After"]) >= 1
    # 수락도 같은 제한
    assert accept(client, token).status_code == 429


# ── 수락 ──

def test_accept_shares_same_records(client, db, consent_docs, share_doc, admin_id, parent_id):
    record_id = client.post(
        f"/v1/parents/{parent_id}/records/text", json={"text": "밥 드셨어요"}
    ).json()["data"]["id"]
    token = new_token(client, parent_id, "viewer")

    user = new_user(db, client, consent_docs)
    response = accept(client, token)

    assert response.status_code == 200
    assert response.json()["data"] == {"parent_id": parent_id, "role": "viewer"}
    # 같은 parent_id → 같은 기록
    assert [r["id"] for r in client.get(f"/v1/parents/{parent_id}/records").json()["data"]] == [record_id]
    assert client.get(f"/v1/records/{record_id}").status_code == 200
    me = client.get("/v1/auth/me").json()["data"]
    assert me["parent_ids"] == [parent_id] and me["onboarding"]["parent_registered"] is True

    row = run_sql(
        db,
        "SELECT share_doc_version, share_agreed_at FROM family_members WHERE parent_id = :p AND user_id = :u",
        p=parent_id, u=user
    )[0]
    assert row[0] == SHARE_VERSION and row[1] is not None


def test_role_comes_from_invite(client, db, consent_docs, share_doc, admin_id, parent_id):
    join_by_invite(db, client, consent_docs, parent_id, admin_id, "viewer")
    assert client.post(f"/v1/parents/{parent_id}/records/text", json={"text": "밥"}).status_code == 403

    join_by_invite(db, client, consent_docs, parent_id, admin_id, "writer")
    assert client.post(f"/v1/parents/{parent_id}/records/text", json={"text": "밥"}).status_code == 201


def test_accept_retry_returns_same(client, db, consent_docs, share_doc, admin_id, parent_id):
    token = new_token(client, parent_id)
    new_user(db, client, consent_docs)

    first = accept(client, token)
    # 응답 유실 → 같은 토큰 재요청
    again = accept(client, token)

    assert again.status_code == 200 and again.json() == first.json()
    assert len(members(client, parent_id)) == 2


def test_accept_used_by_other(client, db, consent_docs, share_doc, admin_id, parent_id):
    token = new_token(client, parent_id)
    new_user(db, client, consent_docs)
    accept(client, token)

    new_user(db, client, consent_docs)
    response = accept(client, token)
    assert response.status_code == 409 and error_code(response) == "INVITE_USED"


def test_accept_already_member(client, db, consent_docs, share_doc, admin_id, parent_id):
    first, second = new_token(client, parent_id), new_token(client, parent_id)
    new_user(db, client, consent_docs)
    accept(client, first)

    response = accept(client, second)
    assert response.status_code == 409 and error_code(response) == "ALREADY_MEMBER"
    # 두 번째 초대는 쓰지 않은 상태
    client.login(admin_id)
    assert len(client.get(f"/v1/parents/{parent_id}/invites").json()["data"]) == 1


def test_accept_requirements(client, db, consent_docs, share_doc, admin_id, parent_id):
    token = new_token(client, parent_id)

    new_user(db, client, consent_docs, consented=False)
    assert accept(client, token).status_code == 403

    agree_all(client, consent_docs)
    response = accept(client, token, version="old-version")
    assert response.status_code == 400 and error_code(response) == "CONSENT_REQUIRED"
    assert response.json()["error"]["details"]["doc_version"] == SHARE_VERSION

    assert accept(client, token).status_code == 200


def test_user_with_own_parent_gets_new_relation(client, db, consent_docs, share_doc, admin_id, parent_id):
    token = new_token(client, parent_id)

    new_user(db, client, consent_docs)
    own_parent = client.post("/v1/parents", json={**PARENT, "nickname": "아빠"}).json()["data"]["id"]
    accept(client, token)

    parents = {p["id"]: p["my_role"] for p in client.get("/v1/parents").json()["data"]}
    assert parents == {own_parent: "admin", parent_id: "writer"}
    assert client.get(f"/v1/parents/{own_parent}").json()["data"]["nickname"] == "아빠"


def test_removed_user_cannot_reuse_old_invite(client, db, consent_docs, share_doc, admin_id, parent_id):
    token = new_token(client, parent_id)
    user = new_user(db, client, consent_docs)
    accept(client, token)

    client.login(admin_id)
    client.delete(f"/v1/family/{member_id_of(client, parent_id, user)}")

    client.login(user)
    response = accept(client, token)
    assert response.status_code == 409 and error_code(response) == "INVITE_USED"
    assert preview(client, token).status_code == 409


# ── 구성원 ──

def test_member_list(client, db, consent_docs, share_doc, admin_id, parent_id):
    viewer = join_by_invite(db, client, consent_docs, parent_id, admin_id, "viewer")
    writer = join_by_invite(db, client, consent_docs, parent_id, admin_id, "writer")

    client.login(viewer)
    data = members(client, parent_id)

    assert [(m["user_id"], m["role"]) for m in data] == [
        (admin_id, "admin"), (writer, "writer"), (viewer, "viewer")
    ]
    assert [m["is_me"] for m in data] == [False, False, True]
    assert set(data[0]) == {"member_id", "user_id", "display_name", "role", "joined_at", "is_me"}

    new_user(db, client, consent_docs)
    assert client.get(f"/v1/parents/{parent_id}/family").status_code == 404


# ── 역할 ──

def patch_role(client, member_id, role):
    return client.patch(f"/v1/family/{member_id}/role", json={"role": role})


def test_role_changes(client, db, consent_docs, share_doc, admin_id, parent_id):
    other = join_by_invite(db, client, consent_docs, parent_id, admin_id)
    client.login(admin_id)
    other_member = member_id_of(client, parent_id, other)
    my_member = member_id_of(client, parent_id, admin_id)

    # 마지막 관리자 자기 강등 → 409
    response = patch_role(client, my_member, "writer")
    assert response.status_code == 409 and error_code(response) == "LAST_ADMIN"

    assert patch_role(client, other_member, "admin").json()["data"]["role"] == "admin"
    # 같은 역할 → 그대로
    assert patch_role(client, other_member, "admin").status_code == 200
    # 관리자 둘 → 자기 강등 가능
    assert patch_role(client, my_member, "viewer").json()["data"]["role"] == "viewer"

    # 이제 보기 전용 → 역할 변경 403
    assert patch_role(client, other_member, "writer").status_code == 403
    assert patch_role(client, other_member, "nope").status_code == 422


def test_demoted_admin_invites_revoked(client, db, consent_docs, share_doc, admin_id, parent_id):
    other = join_by_invite(db, client, consent_docs, parent_id, admin_id)
    client.login(admin_id)
    patch_role(client, member_id_of(client, parent_id, other), "admin")

    client.login(other)
    other_token = new_token(client, parent_id)
    client.login(admin_id)
    my_token = new_token(client, parent_id)

    patch_role(client, member_id_of(client, parent_id, other), "writer")

    assert preview(client, other_token).status_code == 410
    assert preview(client, my_token).status_code == 200


def test_role_change_other_family_404(client, db, consent_docs, admin_id, parent_id):
    my_member = member_id_of(client, parent_id, admin_id)
    new_user(db, client, consent_docs)
    client.post("/v1/parents", json=PARENT)

    assert patch_role(client, my_member, "viewer").status_code == 404
    assert client.delete(f"/v1/family/{my_member}").status_code == 404


# ── 내보내기 · 나가기 ──

def test_remove_member_keeps_records(client, db, consent_docs, share_doc, admin_id, parent_id):
    writer = join_by_invite(db, client, consent_docs, parent_id, admin_id)
    record_id = client.post(
        f"/v1/parents/{parent_id}/records/text", json={"text": "밥"}
    ).json()["data"]["id"]

    client.login(admin_id)
    assert client.delete(f"/v1/family/{member_id_of(client, parent_id, writer)}").status_code == 204
    # 기록 유지
    assert client.get(f"/v1/records/{record_id}").json()["data"]["author_id"] == writer

    # 내보낸 사람: 같은 로그인으로 모든 API 404
    client.login(writer)
    assert client.get(f"/v1/parents/{parent_id}").status_code == 404
    assert client.get(f"/v1/records/{record_id}").status_code == 404
    assert client.get(f"/v1/records/{record_id}/audio").status_code == 404
    assert client.post(
        f"/v1/parents/{parent_id}/records/audio/upload-url", json={"content_type": "audio/mp4"}
    ).status_code == 404
    assert client.get("/v1/auth/me").json()["data"]["onboarding"]["parent_registered"] is False


def test_leave_and_last_admin(client, db, consent_docs, share_doc, admin_id, parent_id):
    viewer = join_by_invite(db, client, consent_docs, parent_id, admin_id, "viewer")
    writer = join_by_invite(db, client, consent_docs, parent_id, admin_id, "writer")

    # 보기 전용: 다른 사람 내보내기 403, 나가기 가능
    client.login(viewer)
    assert client.delete(f"/v1/family/{member_id_of(client, parent_id, writer)}").status_code == 403
    assert client.delete(f"/v1/family/{member_id_of(client, parent_id, viewer)}").status_code == 204

    # 마지막 관리자: 나가기·내보내기 409
    client.login(admin_id)
    response = client.delete(f"/v1/family/{member_id_of(client, parent_id, admin_id)}")
    assert response.status_code == 409 and error_code(response) == "LAST_ADMIN"


def test_remove_other_admin_revokes_invites(client, db, consent_docs, share_doc, admin_id, parent_id):
    other = join_by_invite(db, client, consent_docs, parent_id, admin_id)
    client.login(admin_id)
    other_member = member_id_of(client, parent_id, other)
    patch_role(client, other_member, "admin")

    client.login(other)
    token = new_token(client, parent_id)

    client.login(admin_id)
    assert client.delete(f"/v1/family/{other_member}").status_code == 204
    assert preview(client, token).status_code == 410


# ── 마지막 관리자 (DB 검사) ──

def check_now(db, name):
    db.connection().execute(text(f"SET CONSTRAINTS {name} IMMEDIATE"))


def test_db_rejects_no_admin(client, db, parent_id):
    connection = db.connection()
    savepoint = connection.begin_nested()
    connection.execute(
        text("UPDATE family_members SET role = 'writer' WHERE parent_id = :p"), {"p": parent_id}
    )
    with pytest.raises(DBAPIError, match="관리자 없음"):
        check_now(db, "family_members_last_admin")
    savepoint.rollback()
    db.commit()


def test_db_rejects_parent_without_admin(db):
    connection = db.connection()
    savepoint = connection.begin_nested()
    connection.execute(text(
        "INSERT INTO parents (nickname, apply_stage, cohabiting) VALUES ('관리자 없음', 'before', false)"
    ))
    with pytest.raises(DBAPIError, match="관리자 없음"):
        check_now(db, "parents_has_admin")
    savepoint.rollback()
    db.commit()


def test_db_allows_parent_creation_and_deletion(client, db, parent_id):
    # 생성: 부모님 + 관리자 같은 트랜잭션 → 통과 (parent_id 픽스처)
    check_now(db, "parents_has_admin, family_members_last_admin")
    # 공간 삭제 (연쇄 삭제) → 통과
    run_sql(db, "DELETE FROM parents WHERE id = :p", p=parent_id)
    check_now(db, "parents_has_admin, family_members_last_admin")
    db.commit()
