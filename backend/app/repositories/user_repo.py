from sqlalchemy import text
from sqlalchemy.orm import Session


# DB login_type_enum 값. Supabase provider 이름이 이 중 하나일 때만 저장한다
LOGIN_TYPES = {"kakao", "phone", "email"}


def ensure_user(
    db: Session,
    user_id: str,
    provider: str | None,
    phone: str | None
):
    """public.users 프로필이 없으면 만든다. 이미 있으면 아무것도 하지 않는다."""
    db.execute(
        text("""
            INSERT INTO users (id, login_type, phone)
            VALUES (:id, CAST(:login_type AS login_type_enum), :phone)
            ON CONFLICT (id) DO NOTHING
        """),
        {
            "id": user_id,
            "login_type": provider if provider in LOGIN_TYPES else None,
            "phone": phone
        }
    )


def get_user(db: Session, user_id: str):
    return db.execute(
        text("""
            SELECT id, login_type::text AS login_type, phone, created_at
            FROM users
            WHERE id = :id
        """),
        {"id": user_id}
    ).mappings().first()
