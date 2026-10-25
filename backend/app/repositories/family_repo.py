from sqlalchemy import text
from sqlalchemy.orm import Session


def get_role(db: Session, parent_id: str, user_id: str) -> str | None:
    """이 사용자의 해당 부모님에 대한 역할 (admin/writer/viewer). 가족이 아니면 None"""
    return db.execute(
        text("""
            SELECT role::text
            FROM family_members
            WHERE parent_id = :parent_id AND user_id = :user_id
        """),
        {"parent_id": parent_id, "user_id": user_id}
    ).scalar_one_or_none()
