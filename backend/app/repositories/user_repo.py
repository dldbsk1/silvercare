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
    """public.users 프로필이 없으면 만든다. 이미 있으면 아무것도 하지 않는다.

    반환: 탈퇴 시각 (새로 만든 프로필 → None). 요청마다 쿼리 1번
    """
    return db.execute(
        text("""
            WITH created AS (
                INSERT INTO users (id, login_type, phone)
                VALUES (:id, CAST(:login_type AS login_type_enum), :phone)
                ON CONFLICT (id) DO NOTHING
            )
            SELECT withdrawn_at FROM users WHERE id = :id
        """),
        {
            "id": user_id,
            "login_type": provider if provider in LOGIN_TYPES else None,
            "phone": phone
        }
    ).scalar_one_or_none()


def get_user(db: Session, user_id: str):
    return db.execute(
        text("""
            SELECT id, login_type::text AS login_type, phone, display_name, created_at,
                   withdrawn_at
            FROM users
            WHERE id = :id
        """),
        {"id": user_id}
    ).mappings().first()


def set_display_name(db: Session, user_id: str, display_name: str):
    db.execute(
        text("UPDATE users SET display_name = :name WHERE id = :id"),
        {"id": user_id, "name": display_name}
    )


def lock_user(db: Session, user_id: str):
    """탈퇴·가족 추가 직렬화 (잠금 순서: 사용자 → 부모님). 탈퇴 시각 반환"""
    return db.execute(
        text("SELECT withdrawn_at FROM users WHERE id = :id FOR UPDATE"),
        {"id": user_id}
    ).scalar_one_or_none()


def mark_withdrawn(db: Session, user_id: str):
    db.execute(
        text("UPDATE users SET withdrawn_at = now() WHERE id = :id"),
        {"id": user_id}
    )


def erase_profile(db: Session, user_id: str):
    """삭제 실행: 이름·전화번호 지움. 행은 탈퇴한 사용자로 유지"""
    db.execute(
        text("UPDATE users SET display_name = NULL, phone = NULL WHERE id = :id"),
        {"id": user_id}
    )
