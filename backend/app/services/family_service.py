"""가족 초대·구성원·역할·내보내기 (A-3, A-FAM-001/002)

- 트랜잭션: 라우터에서 시작
- 잠금 순서 (가족 구성 변경 전부): 부모님 행 → family_members / family_invites
  가족 추가 (수락)·탈퇴: 사용자 행 먼저 → 부모님 행
  → 초대 생성·수락·역할 변경·내보내기·나가기 직렬화. 잠금 뒤 요청자 역할 다시 확인
- 마지막 관리자: 409 LAST_ADMIN (서비스) + 트랜잭션 끝 검사 (DB, 006)
- 관리자 권한 잃음 (강등·내보내기·나가기) → 그 사람이 만든 미사용 초대 취소
- 토큰: 원문은 생성 응답에만, DB엔 SHA-256
- 내보내기 = 가족 관계만 삭제. 작성 기록·수정 이력·동의 기록 유지
"""
import hashlib
import secrets

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.repositories import family_repo, invite_repo, parent_repo
from app.schemas.family import InviteAcceptIn, InviteCreateIn, RoleUpdateIn
from app.services import account_service, consent_service
from app.services.access import ParentAccess, get_parent_access


INVITE_VALID_DAYS = 7
MAX_ACTIVE_INVITES = 10
TOKEN_BYTES = 32


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def not_found() -> AppError:
    return AppError(404, "NOT_FOUND", "부모님 정보를 찾을 수 없어요.")


def lock_family(db: Session, parent_id: str, user_id: str) -> str:
    """부모님 행 잠금 → 요청자의 현재 역할. 가족 아님 → 404"""
    if not family_repo.lock_parent(db, parent_id):
        raise not_found()
    role = family_repo.get_role(db, parent_id, user_id)
    if role is None:
        raise not_found()
    return role


def lock_family_as_admin(db: Session, parent_id: str, user_id: str):
    if lock_family(db, parent_id, user_id) != "admin":
        raise AppError(403, "PERMISSION_DENIED", "관리자만 할 수 있어요.")


def ensure_other_admin(db: Session, parent_id: str):
    if family_repo.count_admins(db, parent_id) <= 1:
        raise AppError(
            409, "LAST_ADMIN",
            "다른 가족을 관리자로 지정한 뒤 다시 시도해 주세요."
        )


# ── 초대 (관리자) ──

def create_invite(db: Session, access: ParentAccess, body: InviteCreateIn) -> dict:
    lock_family_as_admin(db, access.parent_id, access.user_id)

    if invite_repo.count_active(db, access.parent_id) >= MAX_ACTIVE_INVITES:
        raise AppError(
            409, "INVITE_LIMIT",
            f"사용하지 않은 초대가 {MAX_ACTIVE_INVITES}개예요. 안 쓰는 초대를 취소해 주세요."
        )

    token = secrets.token_urlsafe(TOKEN_BYTES)
    row = invite_repo.insert_invite(
        db, access.parent_id, access.user_id, body.role,
        hash_token(token), INVITE_VALID_DAYS
    )

    return {
        "invite_id": str(row["id"]),
        "invite_url": f"{settings.INVITE_BASE_URL}#t={token}",
        "token": token,
        "role": row["role"],
        "expires_at": row["expires_at"],
    }


def to_invite_out(invite) -> dict:
    return {
        "invite_id": str(invite["id"]),
        "role": invite["role"],
        "invited_by": str(invite["invited_by"]),
        "inviter_name": invite["inviter_name"],
        "created_at": invite["created_at"],
        "expires_at": invite["expires_at"],
    }


def list_invites(db: Session, access: ParentAccess) -> list[dict]:
    return [to_invite_out(i) for i in invite_repo.list_active(db, access.parent_id)]


def revoke_invite(db: Session, user_id: str, invite_id: str):
    """수락된 초대 → 409 INVITE_USED (가족 관계는 내보내기로). 이미 취소 → 그대로"""
    invite = invite_repo.get_by_id(db, invite_id)
    if invite is None:
        raise invite_not_found()

    parent_id = str(invite["parent_id"])
    get_parent_access(db, user_id, parent_id)
    lock_family_as_admin(db, parent_id, user_id)

    invite = invite_repo.get_by_id(db, invite_id, for_update=True)
    if invite["accepted_at"] is not None:
        raise invite_used()
    if invite["revoked_at"] is None:
        invite_repo.revoke(db, invite_id)


# ── 초대받은 사람 ──

def invite_not_found() -> AppError:
    return AppError(404, "INVITE_NOT_FOUND", "초대를 찾을 수 없어요. 링크를 다시 확인해 주세요.")


def invite_used() -> AppError:
    return AppError(409, "INVITE_USED", "이미 사용된 초대예요. 초대한 가족에게 새 링크를 요청해 주세요.")


def check_invite(invite, user_id: str, my_role: str | None) -> bool:
    """사용 가능 여부. True → 내가 이미 수락했고 지금도 가족 (같은 결과 반환)

    수락했지만 내보내짐 → INVITE_USED (예전 링크로 다시 들어오기 방지)
    """
    if invite["accepted_by"] is not None:
        if str(invite["accepted_by"]) == user_id and my_role is not None:
            return True
        raise invite_used()
    if invite["revoked_at"] is not None:
        raise AppError(410, "INVITE_REVOKED", "취소된 초대예요. 초대한 가족에게 새 링크를 요청해 주세요.")
    if invite["expired"]:
        raise AppError(410, "INVITE_EXPIRED", "기간이 지난 초대예요. 초대한 가족에게 새 링크를 요청해 주세요.")
    return False


def require_share_document(db: Session) -> dict:
    doc = consent_service.share_document(db)
    if doc is None:
        raise AppError(
            503, "SERVICE_UNAVAILABLE", "잠시 후 다시 시도해 주세요.",
            details={"service": "consent_document"}
        )
    return doc


def preview(db: Session, user_id: str, token: str) -> dict:
    invite = invite_repo.get_by_hash(db, hash_token(token))
    if invite is None:
        raise invite_not_found()

    parent_id = str(invite["parent_id"])
    my_role = family_repo.get_role(db, parent_id, user_id)
    check_invite(invite, user_id, my_role)
    doc = require_share_document(db)

    return {
        "inviter_name": invite["inviter_name"],
        "parent_nickname": parent_repo.get_nickname(db, parent_id),
        "role": invite["role"],
        "expires_at": invite["expires_at"],
        "already_member": my_role is not None,
        "share_document": {
            "doc_version": doc["doc_version"],
            "title": doc["title"],
            "content": doc["content"],
        },
    }


def accept(db: Session, user_id: str, body: InviteAcceptIn) -> dict:
    """한 트랜잭션: 사용자 잠금 → 부모님 잠금 → 초대 잠금 → 확인 → 가족 추가 + 수락 표시

    응답 유실 후 같은 토큰 재요청 (지금도 가족) → 같은 결과
    다른 부모님 가족인 사용자 → 기존 관계 유지, 관계 추가
    """
    token_hash = hash_token(body.token)
    invite = invite_repo.get_by_hash(db, token_hash)
    if invite is None:
        raise invite_not_found()

    account_service.lock_active_user(db, user_id)
    parent_id = str(invite["parent_id"])
    if not family_repo.lock_parent(db, parent_id):
        raise invite_not_found()
    invite = invite_repo.get_by_hash(db, token_hash, for_update=True)
    my_role = family_repo.get_role(db, parent_id, user_id)

    if check_invite(invite, user_id, my_role):
        return {"parent_id": parent_id, "role": my_role}
    if my_role is not None:
        raise AppError(409, "ALREADY_MEMBER", "이미 함께 기록하고 있어요.")

    doc = require_share_document(db)
    if body.share_doc_version != doc["doc_version"]:
        raise AppError(
            400, "CONSENT_REQUIRED", "동의 문구가 바뀌었어요. 화면을 새로 고쳐 주세요.",
            details={"type": consent_service.SHARE_TYPE, "doc_version": doc["doc_version"]}
        )

    family_repo.add_member(db, parent_id, user_id, invite["role"], doc["doc_version"])
    invite_repo.mark_accepted(db, str(invite["id"]), user_id)

    return {"parent_id": parent_id, "role": invite["role"]}


# ── 구성원 ──

def to_member_out(member, user_id: str) -> dict:
    return {
        "member_id": str(member["id"]),
        "user_id": str(member["user_id"]),
        "display_name": member["display_name"],
        "role": member["role"],
        "joined_at": member["joined_at"],
        "is_me": str(member["user_id"]) == user_id,
    }


def list_members(db: Session, access: ParentAccess) -> list[dict]:
    return [
        to_member_out(m, access.user_id)
        for m in family_repo.list_members(db, access.parent_id)
    ]


def find_member(db: Session, user_id: str, member_id: str):
    """다른 가족의 구성원 → 404 (존재 여부 숨김)"""
    member = family_repo.get_member(db, member_id)
    if member is None:
        raise AppError(404, "NOT_FOUND", "가족을 찾을 수 없어요.")
    get_parent_access(db, user_id, str(member["parent_id"]))
    return member


def lock_member(db: Session, member_id: str):
    """부모님 잠금 뒤 다시 읽기 (그사이 내보내짐 → 404)"""
    member = family_repo.get_member(db, member_id, for_update=True)
    if member is None:
        raise AppError(404, "NOT_FOUND", "가족을 찾을 수 없어요.")
    return member


def change_role(db: Session, user_id: str, member_id: str, body: RoleUpdateIn) -> dict:
    """관리자끼리 동등: 다른 관리자 강등·자기 강등 가능. 관리자 1명 이상 유지"""
    member = find_member(db, user_id, member_id)
    parent_id = str(member["parent_id"])
    lock_family_as_admin(db, parent_id, user_id)
    member = lock_member(db, member_id)

    if member["role"] == body.role:
        return to_member_out(member, user_id)

    if member["role"] == "admin":
        ensure_other_admin(db, parent_id)
        invite_repo.revoke_created_by(db, parent_id, str(member["user_id"]))

    family_repo.set_role(db, member_id, body.role)
    return to_member_out(family_repo.get_member(db, member_id), user_id)


def remove_member(db: Session, user_id: str, member_id: str):
    """본인 → 나가기 (역할 무관). 다른 사람 → 관리자만 (내보내기)"""
    member = find_member(db, user_id, member_id)
    parent_id = str(member["parent_id"])
    my_role = lock_family(db, parent_id, user_id)
    member = lock_member(db, member_id)

    is_self = str(member["user_id"]) == user_id
    if not is_self and my_role != "admin":
        raise AppError(403, "PERMISSION_DENIED", "관리자만 가족을 내보낼 수 있어요.")

    if member["role"] == "admin":
        ensure_other_admin(db, parent_id)

    invite_repo.revoke_created_by(db, parent_id, str(member["user_id"]))
    family_repo.delete_member(db, member_id)
