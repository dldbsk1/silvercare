"""가족 권한 확인 (RLS 대신 FastAPI에서 막는다).

URL에 parent_id가 있으면 api/deps.py의 의존성(ReadAccess 등)을 쓴다.
/records/{record_id}처럼 parent_id가 URL에 없으면, service에서 리소스의
parent_id를 먼저 찾은 뒤 get_parent_access()를 직접 호출한다.
"""
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.repositories import family_repo


@dataclass(frozen=True)
class ParentAccess:
    parent_id: str
    user_id: str
    role: str

    @property
    def can_write(self) -> bool:
        return self.role in ("admin", "writer")

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def get_parent_access(
    db: Session,
    user_id: str,
    parent_id: str
) -> ParentAccess:
    """가족이 아니면 404. 다른 가족 부모님이 있는지조차 알 수 없게 한다 (API 명세서 14.1)"""
    role = family_repo.get_role(db, parent_id, user_id)

    if role is None:
        raise AppError(404, "NOT_FOUND", "부모님 정보를 찾을 수 없어요.")

    return ParentAccess(parent_id=parent_id, user_id=user_id, role=role)


def ensure_write(access: ParentAccess) -> ParentAccess:
    if not access.can_write:
        raise AppError(403, "PERMISSION_DENIED", "보기 전용 권한이에요.")
    return access


def ensure_admin(access: ParentAccess) -> ParentAccess:
    if not access.is_admin:
        raise AppError(403, "PERMISSION_DENIED", "관리자만 할 수 있어요.")
    return access
