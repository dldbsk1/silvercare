"""모든 API 버전이 같이 쓰는 의존성.

    @router.post("/parents/{parent_id}/records/text")
    def create_text_record(parent_id: UUID, access: WriteAccess, db: DbSession): ...

확인 순서 (API 명세서 0.5·14.1): 토큰 → 프로필 → 필수 동의 → 부모님 가족 여부·역할
- CurrentUser: 로그인만 확인 (/auth/me, 동의 API)
- ConsentedUser: 필수 동의까지 확인 (부모님 등록 등)
- ReadAccess/WriteAccess/AdminAccess: 동의 + 해당 부모님 가족·역할 확인

의존성은 끝날 때 트랜잭션을 닫아 둔다. 라우터가 db.begin()을 새로 열 수 있게.
"""
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.security import AuthUser, get_auth_user
from app.db.session import get_db
from app.repositories import user_repo
from app.services import consent_service
from app.services.access import (
    ParentAccess,
    ensure_admin,
    ensure_write,
    get_parent_access,
)


DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    auth_user: AuthUser = Depends(get_auth_user)
) -> AuthUser:
    """토큰 확인 + public.users 프로필이 없으면 생성 (첫 요청 때 한 번)"""
    with db.begin():
        user_repo.ensure_user(
            db, auth_user.id, auth_user.provider, auth_user.phone
        )
    return auth_user


CurrentUser = Annotated[AuthUser, Depends(get_current_user)]


def get_consented_user(user: CurrentUser, db: DbSession) -> AuthUser:
    """필수 동의를 철회했거나 문구가 바뀌어 다시 동의해야 하면 403 CONSENT_REQUIRED"""
    with db.begin():
        consent_service.ensure_completed(db, user.id)
    return user


ConsentedUser = Annotated[AuthUser, Depends(get_consented_user)]


def parent_read_access(
    parent_id: UUID,
    user: ConsentedUser,
    db: DbSession
) -> ParentAccess:
    with db.begin():
        return get_parent_access(db, user.id, str(parent_id))


def parent_write_access(
    access: ParentAccess = Depends(parent_read_access)
) -> ParentAccess:
    return ensure_write(access)


def parent_admin_access(
    access: ParentAccess = Depends(parent_read_access)
) -> ParentAccess:
    return ensure_admin(access)


# 조회: 가족 전체(viewer 포함) / 작성: admin·writer / 관리: admin
ReadAccess = Annotated[ParentAccess, Depends(parent_read_access)]
WriteAccess = Annotated[ParentAccess, Depends(parent_write_access)]
AdminAccess = Annotated[ParentAccess, Depends(parent_admin_access)]


# 오프라인 재전송 중복 방지 헤더 (선택). services/idempotency.py와 함께 쓴다
IdempotencyKey = Annotated[
    str | None,
    Header(alias="Idempotency-Key", min_length=1, max_length=200)
]
