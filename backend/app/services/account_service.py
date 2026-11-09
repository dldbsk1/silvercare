"""탈퇴 (A-SET-003). 트랜잭션은 라우터가 연다.

- 잠금 순서: 사용자 행 → 내 부모님 행 (id 순) → 잠근 뒤 역할 다시 확인
  가족 추가 경로 (부모님 등록·초대 수락)도 사용자 → 부모님 순 → 탈퇴 뒤 새 가족 관계 X
- 부모님별 상태
  ok                 다른 관리자 있음 / 내가 관리자 아님 → 바로 나가기
  transfer_required  내가 유일한 관리자 + 다른 가족 있음 → 요청 안에서 넘길 사람 지정
  sole_member        나 혼자 → 확인 (delete_sole_parents) 후 공간 삭제 예약, 가족 관계는 실행 때까지 유지
                     (관리자 0명 공간 X, 탈퇴 계정은 API 차단이라 접근 X)
- 하나라도 실패 → 아무것도 안 바뀜 (409)
- 처리: 관리자 넘기기 → 나가기 → 내 초대 취소 → 기기 토큰 끔 → withdrawn_at → 삭제 예약
- 다시 요청 → 같은 결과
"""
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.repositories import family_repo, invite_repo, notification_repo, parent_repo, user_repo
from app.schemas.account import WithdrawalIn
from app.services import deletion_service


def lock_active_user(db: Session, user_id: str):
    """가족 추가 경로 첫 잠금 (부모님 등록·초대 수락). 그사이 탈퇴 → 403"""
    if user_repo.lock_user(db, user_id) is not None:
        raise AppError(403, "ACCOUNT_WITHDRAWN", "탈퇴 처리 중인 계정이에요.")


OK = "ok"
TRANSFER_REQUIRED = "transfer_required"
SOLE_MEMBER = "sole_member"


def parent_state(db: Session, parent_id: str, user_id: str) -> dict | None:
    """목록 조회 뒤 그사이 내보내짐 → None"""
    members = family_repo.list_members(db, parent_id)
    me = next((m for m in members if str(m["user_id"]) == user_id), None)
    if me is None:
        return None
    others = [m for m in members if str(m["user_id"]) != user_id]
    other_admins = [m for m in others if m["role"] == "admin"]

    if not others:
        status = SOLE_MEMBER
    elif me["role"] == "admin" and not other_admins:
        status = TRANSFER_REQUIRED
    else:
        status = OK

    return {
        "parent_id": parent_id,
        "nickname": parent_repo.get_nickname(db, parent_id),
        "my_role": me["role"],
        "my_member_id": str(me["id"]),
        "status": status,
        "candidates": [
            {
                "member_id": str(m["id"]),
                "display_name": m["display_name"],
                "role": m["role"],
            }
            for m in others
        ] if status == TRANSFER_REQUIRED else [],
    }


def parent_states(db: Session, parent_ids: list[str], user_id: str) -> list[dict]:
    states = [parent_state(db, parent_id, user_id) for parent_id in parent_ids]
    return [state for state in states if state is not None]


def withdrawal_check(db: Session, user_id: str) -> dict:
    parent_ids = family_repo.list_parent_ids_for_user(db, user_id)
    return {"parents": parent_states(db, parent_ids, user_id)}


def to_withdrawal_out(request) -> dict:
    return {
        "request_id": str(request["id"]),
        "status": request["status"],
        "scheduled_for": request["scheduled_for"],
    }


def withdraw(db: Session, user_id: str, body: WithdrawalIn) -> dict:
    if user_repo.lock_user(db, user_id) is not None:
        return to_withdrawal_out(deletion_service.account_request(db, user_id))

    parent_ids = family_repo.list_parent_ids_for_user(db, user_id)
    for parent_id in parent_ids:
        family_repo.lock_parent(db, parent_id)
    states = parent_states(db, parent_ids, user_id)

    transfers = check_transfers(states, body)

    sole = [s["parent_id"] for s in states if s["status"] == SOLE_MEMBER]
    if sole and not body.delete_sole_parents:
        raise AppError(
            409, "SOLE_MEMBER_CONFIRM_REQUIRED",
            "혼자 기록하던 부모님 기록도 함께 삭제돼요. 확인 후 다시 시도해 주세요.",
            details={"parent_ids": sole}
        )

    for member_id in transfers.values():
        family_repo.set_role(db, member_id, "admin")

    for state in states:
        invite_repo.revoke_created_by(db, state["parent_id"], user_id)
        if state["status"] != SOLE_MEMBER:
            family_repo.delete_member(db, state["my_member_id"])

    notification_repo.revoke_all_devices(db, user_id)
    user_repo.mark_withdrawn(db, user_id)

    return to_withdrawal_out(deletion_service.schedule_account(db, user_id, sole))


def check_transfers(states: list[dict], body: WithdrawalIn) -> dict[str, str]:
    """{parent_id: 받을 member_id}. 필요한 부모님만, 받을 사람은 그 부모님 가족"""
    by_parent = {s["parent_id"]: s for s in states}
    requested = {str(t.parent_id): str(t.member_id) for t in body.admin_transfers}

    unknown = [p for p in requested if p not in by_parent]
    if unknown:
        raise AppError(
            400, "INVALID_REQUEST", "관리자를 넘길 부모님을 다시 확인해 주세요.",
            details={"parent_ids": unknown}
        )

    transfers = {}
    missing = []
    for state in states:
        if state["status"] != TRANSFER_REQUIRED:
            continue
        member_id = requested.get(state["parent_id"])
        candidates = {c["member_id"] for c in state["candidates"]}
        if member_id not in candidates:
            missing.append(state["parent_id"])
        else:
            transfers[state["parent_id"]] = member_id

    if missing:
        raise AppError(
            409, "ADMIN_TRANSFER_REQUIRED",
            "관리자를 넘길 가족을 선택해 주세요.",
            details={"parent_ids": missing}
        )
    return transfers
