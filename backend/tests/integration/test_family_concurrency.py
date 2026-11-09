"""가족 구성 변경 동시 요청 (실제 커밋, 연결 2개)

    pytest -m concurrency

테스트 트랜잭션 롤백 방식으로는 다른 연결이 데이터를 못 봄 → 실제로 커밋하고 끝에 삭제
순서 고정: A가 부모님 잠금 + 변경 (커밋 전) → B 시작 (잠금 대기) → A 커밋 → B 결과 확인
"""
import threading
import time
import uuid

import pytest
from sqlalchemy import text

from app.core.errors import AppError
from app.db.session import engine, new_session
from app.schemas.account import WithdrawalIn
from app.schemas.family import InviteCreateIn, RoleUpdateIn
from app.services import account_service, family_service
from app.services.access import ParentAccess


pytestmark = pytest.mark.concurrency

WAIT_SECONDS = 1.0


@pytest.fixture
def family():
    """부모님 1 + 관리자 2 (X, Y). 끝나면 삭제"""
    users = [str(uuid.uuid4()) for _ in range(2)]
    with engine.begin() as conn:
        for user in users:
            conn.execute(
                text("""
                    INSERT INTO auth.users (id, aud, role, email)
                    VALUES (:id, 'authenticated', 'authenticated', :email)
                """),
                {"id": user, "email": f"{user}@test.invalid"}
            )
            conn.execute(
                text("INSERT INTO users (id, login_type) VALUES (:id, 'email') ON CONFLICT (id) DO NOTHING"),
                {"id": user}
            )
        parent_id = str(conn.execute(text("""
            INSERT INTO parents (nickname, apply_stage, cohabiting)
            VALUES ('동시성', 'before', false) RETURNING id
        """)).scalar_one())
        for user in users:
            conn.execute(
                text("INSERT INTO family_members (parent_id, user_id, role) VALUES (:p, :u, 'admin')"),
                {"p": parent_id, "u": user}
            )
        members = {
            str(row.user_id): str(row.id)
            for row in conn.execute(
                text("SELECT id, user_id FROM family_members WHERE parent_id = :p"), {"p": parent_id}
            )
        }

    yield {"parent_id": parent_id, "x": users[0], "y": users[1], "members": members}

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM deletion_requests WHERE requester_id = ANY(:ids)"), {"ids": users})
        conn.execute(text("DELETE FROM parents WHERE id = :p"), {"p": parent_id})
        conn.execute(text("DELETE FROM auth.users WHERE id = ANY(:ids)"), {"ids": users})


def run_blocked(func):
    """다른 연결에서 실행 (잠금 대기). 결과·오류는 dict로"""
    result = {}

    def target():
        with new_session() as db:
            try:
                with db.begin():
                    result["value"] = func(db)
            except AppError as e:
                result["error"] = e

    thread = threading.Thread(target=target)
    thread.start()
    return thread, result


def race(first, second):
    """first 커밋 전 second 시작 → second가 잠금에서 기다리는지 확인 → first 커밋"""
    with new_session() as db_a:
        with db_a.begin():
            first(db_a)
            thread, result = run_blocked(second)
            time.sleep(WAIT_SECONDS)
            assert thread.is_alive(), "두 번째 요청이 부모님 잠금에서 기다리지 않음"
    thread.join(timeout=10)
    assert not thread.is_alive()
    return result


def admin_count(parent_id):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM family_members WHERE parent_id = :p AND role = 'admin'"),
            {"p": parent_id}
        ).scalar_one()


def test_invite_limit_with_two_requests(family):
    parent_id, x = family["parent_id"], family["x"]
    access = ParentAccess(parent_id=parent_id, user_id=x, role="admin")
    body = InviteCreateIn(role="writer", share_confirmed=True)

    with new_session() as db:
        with db.begin():
            for _ in range(9):
                family_service.create_invite(db, access, body)

    result = race(
        lambda db: family_service.create_invite(db, access, body),
        lambda db: family_service.create_invite(db, access, body),
    )

    assert result["error"].code == "INVITE_LIMIT"
    with engine.connect() as conn:
        assert conn.execute(
            text("SELECT count(*) FROM family_invites WHERE parent_id = :p"), {"p": parent_id}
        ).scalar_one() == 10


def test_admins_demote_each_other(family):
    x, y, members = family["x"], family["y"], family["members"]

    result = race(
        lambda db: family_service.change_role(db, x, members[y], RoleUpdateIn(role="writer")),
        lambda db: family_service.change_role(db, y, members[x], RoleUpdateIn(role="writer")),
    )

    # Y는 잠금 뒤 다시 확인 → 이미 관리자 아님
    assert result["error"].status_code == 403
    assert admin_count(family["parent_id"]) == 1


def test_remove_and_demote_at_once(family):
    x, y, members = family["x"], family["y"], family["members"]

    result = race(
        lambda db: family_service.remove_member(db, x, members[y]),
        lambda db: family_service.change_role(db, y, members[x], RoleUpdateIn(role="viewer")),
    )

    # Y는 이미 가족 아님 → 404
    assert result["error"].status_code == 404
    assert admin_count(family["parent_id"]) == 1


def test_both_admins_leave_at_once(family):
    x, y, members = family["x"], family["y"], family["members"]

    result = race(
        lambda db: family_service.remove_member(db, x, members[x]),
        lambda db: family_service.remove_member(db, y, members[y]),
    )

    assert result["error"].code == "LAST_ADMIN"
    assert admin_count(family["parent_id"]) == 1


WITHDRAW = WithdrawalIn(confirm=True)


def test_both_admins_withdraw_at_once(family):
    x, y = family["x"], family["y"]

    result = race(
        lambda db: account_service.withdraw(db, x, WITHDRAW),
        lambda db: account_service.withdraw(db, y, WITHDRAW),
    )

    # Y는 잠금 뒤 다시 확인 → 혼자 남음 → 공간 삭제 확인 필요
    assert result["error"].code == "SOLE_MEMBER_CONFIRM_REQUIRED"
    assert admin_count(family["parent_id"]) == 1


def test_withdraw_and_self_demote(family):
    x, y, members = family["x"], family["y"], family["members"]

    result = race(
        lambda db: account_service.withdraw(db, x, WITHDRAW),
        lambda db: family_service.change_role(db, y, members[y], RoleUpdateIn(role="writer")),
    )

    assert result["error"].code == "LAST_ADMIN"
    assert admin_count(family["parent_id"]) == 1
