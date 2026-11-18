import json

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



def insert_notification(
    db: Session, user_id: str, parent_id: str | None, type_: str, title: str,
    body: str | None, payload: dict | None, dedupe_key: str | None = None
) -> str | None:
    """앱 안 알림 저장 → id. 같은 dedupe_key 이미 있음 → None (저장 X)"""
    row = db.execute(
        text("""
            INSERT INTO notifications (user_id, parent_id, type, title, body, payload, dedupe_key)
            VALUES (:u, :p, :t, :title, :body, CAST(:payload AS jsonb), :key)
            ON CONFLICT (dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING
            RETURNING id
        """),
        {"u": user_id, "p": parent_id, "t": type_, "title": title, "body": body,
         "payload": json.dumps(payload) if payload is not None else None,
         "key": dedupe_key}
    ).first()
    return str(row[0]) if row else None


# ── 알림 목록 (POP_A_NOTI) ──

NOTIFICATION_COLUMNS = """
    n.id, n.user_id, n.parent_id, n.type, n.title, n.body, n.payload,
    n.created_at, n.read_at, n.sent_at
"""

# 내 알림 중 볼 수 있는 것: 공간 무관 알림 + 지금도 가족인 공간 알림 (나간 공간 X)
VISIBLE = """
    n.user_id = :u
    AND (n.parent_id IS NULL OR EXISTS (
        SELECT 1 FROM family_members fm
        WHERE fm.parent_id = n.parent_id AND fm.user_id = n.user_id
    ))
"""


def list_notifications(db: Session, user_id: str, limit: int, after: tuple | None = None):
    """최신순 keyset. after = (created_at, id)"""
    cursor = "AND (n.created_at, n.id) < (:after_at, CAST(:after_id AS uuid))" if after else ""
    params = {"u": user_id, "limit": limit}
    if after:
        params.update(after_at=after[0], after_id=after[1])
    return db.execute(
        text(f"""
            SELECT {NOTIFICATION_COLUMNS}
            FROM notifications n
            WHERE {VISIBLE} {cursor}
            ORDER BY n.created_at DESC, n.id DESC
            LIMIT :limit
        """),
        params
    ).mappings().all()


def count_unread(db: Session, user_id: str) -> int:
    return db.execute(
        text(f"SELECT count(*) FROM notifications n WHERE {VISIBLE} AND n.read_at IS NULL"),
        {"u": user_id}
    ).scalar_one()


def mark_read(db: Session, user_id: str, notification_id: str):
    """내 알림 아님·안 보이는 알림 → None. 이미 읽음 → 그대로"""
    db.execute(
        text(f"""
            UPDATE notifications n SET read_at = now()
            WHERE n.id = :id AND n.read_at IS NULL AND {VISIBLE}
        """),
        {"id": notification_id, "u": user_id}
    )
    return db.execute(
        text(f"SELECT {NOTIFICATION_COLUMNS} FROM notifications n WHERE n.id = :id AND {VISIBLE}"),
        {"id": notification_id, "u": user_id}
    ).mappings().first()


def mark_all_read(db: Session, user_id: str) -> int:
    return db.execute(
        text(f"UPDATE notifications n SET read_at = now() WHERE {VISIBLE} AND n.read_at IS NULL"),
        {"u": user_id}
    ).rowcount


# ── 푸시 발송 ──

def get_for_push(db: Session, notification_id: str):
    return db.execute(
        text(f"SELECT {NOTIFICATION_COLUMNS} FROM notifications n WHERE n.id = :id"),
        {"id": notification_id}
    ).mappings().first()


def active_tokens(db: Session, user_id: str) -> list[tuple[str, str]]:
    """끄지 않은 기기 (id, token). 최근 사용 순"""
    return [
        (str(r[0]), r[1]) for r in db.execute(
            text("""
                SELECT id, push_token FROM devices
                WHERE user_id = :u AND revoked_at IS NULL
                ORDER BY last_seen_at DESC
            """),
            {"u": user_id}
        ).all()
    ]


def has_active_device(db: Session, user_id: str) -> bool:
    return db.execute(
        text("SELECT 1 FROM devices WHERE user_id = :u AND revoked_at IS NULL LIMIT 1"),
        {"u": user_id}
    ).first() is not None


def mark_sent(db: Session, notification_id: str):
    db.execute(
        text("UPDATE notifications SET sent_at = now() WHERE id = :id AND sent_at IS NULL"),
        {"id": notification_id}
    )


def revoke_tokens(db: Session, device_ids: list[str]):
    """FCM이 더 이상 받지 않는 토큰 (앱 삭제·토큰 만료)"""
    for device_id in device_ids:
        db.execute(
            text("UPDATE devices SET revoked_at = now() WHERE id = :id AND revoked_at IS NULL"),
            {"id": device_id}
        )
