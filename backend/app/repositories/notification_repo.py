from sqlalchemy import text
from sqlalchemy.orm import Session


SETTING_COLUMNS = "condition_enabled, tasks_enabled, briefing_enabled"


def get_settings(db: Session, user_id: str):
    """저장 전 → None (기본값은 서비스에서)"""
    return db.execute(
        text(f"SELECT {SETTING_COLUMNS} FROM notification_settings WHERE user_id = :u"),
        {"u": user_id}
    ).mappings().first()


def upsert_settings(db: Session, user_id: str, values: dict):
    db.execute(
        text("""
            INSERT INTO notification_settings
                (user_id, condition_enabled, tasks_enabled, briefing_enabled)
            VALUES (:u, :condition_enabled, :tasks_enabled, :briefing_enabled)
            ON CONFLICT (user_id) DO UPDATE
            SET condition_enabled = EXCLUDED.condition_enabled,
                tasks_enabled = EXCLUDED.tasks_enabled,
                briefing_enabled = EXCLUDED.briefing_enabled,
                updated_at = now()
        """),
        {"u": user_id, **values}
    )


def upsert_device(db: Session, user_id: str, platform: str, push_token: str):
    """같은 토큰 → 갱신 (다른 사용자 토큰이면 나에게 옮김, 끈 토큰 다시 켬)"""
    return db.execute(
        text("""
            INSERT INTO devices (user_id, platform, push_token)
            VALUES (:u, CAST(:platform AS device_platform_enum), :token)
            ON CONFLICT (push_token) DO UPDATE
            SET user_id = EXCLUDED.user_id,
                platform = EXCLUDED.platform,
                last_seen_at = now(),
                revoked_at = NULL
            RETURNING id, platform::text AS platform, last_seen_at
        """),
        {"u": user_id, "platform": platform, "token": push_token}
    ).mappings().one()


def revoke_device(db: Session, user_id: str, device_id: str) -> bool:
    """내 기기 아님 → False. 이미 끔 → 그대로 True"""
    return db.execute(
        text("""
            UPDATE devices SET revoked_at = coalesce(revoked_at, now())
            WHERE id = :id AND user_id = :u
            RETURNING id
        """),
        {"id": device_id, "u": user_id}
    ).first() is not None


def revoke_all_devices(db: Session, user_id: str):
    db.execute(
        text("UPDATE devices SET revoked_at = now() WHERE user_id = :u AND revoked_at IS NULL"),
        {"u": user_id}
    )

