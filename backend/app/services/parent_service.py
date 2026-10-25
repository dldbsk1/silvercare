"""부모님 등록·조회 (기능명세서 A-ON-003). 트랜잭션은 라우터가 연다."""
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.repositories import parent_repo
from app.schemas.parents import ParentCreateIn


def to_out(row) -> dict:
    return {**dict(row), "id": str(row["id"])}


def create_parent(db: Session, user_id: str, body: ParentCreateIn) -> dict:
    """부모님 프로필 생성 + 만든 사람 = 관리자. 같은 트랜잭션 안에서 실행돼야 한다"""
    parent_id = parent_repo.create_parent(
        db, body.nickname, body.age_band, body.apply_stage, body.cohabiting
    )
    parent_repo.add_member(db, parent_id, user_id, "admin")

    return to_out(parent_repo.get_for_user(db, parent_id, user_id))


def get_parent(db: Session, user_id: str, parent_id: str) -> dict:
    row = parent_repo.get_for_user(db, parent_id, user_id)
    if row is None:
        raise AppError(404, "NOT_FOUND", "부모님 정보를 찾을 수 없어요.")
    return to_out(row)


def list_parents(db: Session, user_id: str) -> list[dict]:
    return [to_out(row) for row in parent_repo.list_for_user(db, user_id)]
