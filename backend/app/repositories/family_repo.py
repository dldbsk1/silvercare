from sqlalchemy import text
from sqlalchemy.orm import Session


MEMBER_COLUMNS = """
    fm.id, fm.parent_id, fm.user_id, fm.role::text AS role, fm.joined_at,
    u.display_name
"""


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


def lock_parent(db: Session, parent_id: str) -> bool:
    """가족 구성 변경 직렬화 (모든 경로 공통 첫 잠금). 부모님 없음 → False"""
    return db.execute(
        text("SELECT 1 FROM parents WHERE id = :id FOR UPDATE"),
        {"id": parent_id}
    ).first() is not None


def get_member(db: Session, member_id: str, for_update: bool = False):
    lock = "FOR UPDATE OF fm" if for_update else ""
    return db.execute(
        text(f"""
            SELECT {MEMBER_COLUMNS}
            FROM family_members fm
            JOIN users u ON u.id = fm.user_id
            WHERE fm.id = :id
            {lock}
        """),
        {"id": member_id}
    ).mappings().first()


def list_members(db: Session, parent_id: str):
    """관리자 → 쓰기 → 보기, 같은 역할은 가입 순"""
    return db.execute(
        text(f"""
            SELECT {MEMBER_COLUMNS}
            FROM family_members fm
            JOIN users u ON u.id = fm.user_id
            WHERE fm.parent_id = :parent_id
            ORDER BY fm.role, fm.joined_at, fm.id
        """),
        {"parent_id": parent_id}
    ).mappings().all()


def count_admins(db: Session, parent_id: str) -> int:
    return db.execute(
        text("""
            SELECT count(*) FROM family_members
            WHERE parent_id = :parent_id AND role = 'admin'
        """),
        {"parent_id": parent_id}
    ).scalar_one()


def add_member(
    db: Session,
    parent_id: str,
    user_id: str,
    role: str,
    share_doc_version: str
):
    db.execute(
        text("""
            INSERT INTO family_members
                (parent_id, user_id, role, share_doc_version, share_agreed_at)
            VALUES (:parent_id, :user_id, CAST(:role AS family_role_enum),
                    :share_doc_version, now())
        """),
        {
            "parent_id": parent_id,
            "user_id": user_id,
            "role": role,
            "share_doc_version": share_doc_version
        }
    )


def set_role(db: Session, member_id: str, role: str):
    db.execute(
        text("""
            UPDATE family_members SET role = CAST(:role AS family_role_enum)
            WHERE id = :id
        """),
        {"id": member_id, "role": role}
    )


def delete_member(db: Session, member_id: str):
    db.execute(text("DELETE FROM family_members WHERE id = :id"), {"id": member_id})


def list_parent_ids_for_user(db: Session, user_id: str) -> list[str]:
    """id 순 (여러 부모님 잠글 때 순서 고정 → 교착 방지)"""
    return [
        str(parent_id) for parent_id in db.execute(
            text("""
                SELECT parent_id FROM family_members
                WHERE user_id = :user_id
                ORDER BY parent_id
            """),
            {"user_id": user_id}
        ).scalars()
    ]


def get_membership(db: Session, parent_id: str, user_id: str):
    return db.execute(
        text(f"""
            SELECT {MEMBER_COLUMNS}
            FROM family_members fm
            JOIN users u ON u.id = fm.user_id
            WHERE fm.parent_id = :parent_id AND fm.user_id = :user_id
        """),
        {"parent_id": parent_id, "user_id": user_id}
    ).mappings().first()
