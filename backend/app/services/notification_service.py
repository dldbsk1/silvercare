"""알림 설정·기기 토큰 (A-SET-002). 트랜잭션은 라우터가 연다.

- 저장 전 → 모두 켜짐 (GET은 DB에 쓰지 않음)
- 푸시 = 알림 동의(noti) + 해당 설정 켜짐. 실제 발송은 B단계 (FCM)
- 기기: 같은 토큰 → 1건 (다른 사용자 토큰이면 나에게 옮김). 끄기 = revoked_at (행 유지)
"""
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.repositories import consent_repo, notification_repo
from app.schemas.settings import DeviceIn, NotificationSettingsIn


DEFAULT_SETTINGS = {
    "condition_enabled": True,
    "tasks_enabled": True,
    "briefing_enabled": True,
}


def noti_consented(db: Session, user_id: str) -> bool:
    return any(c["type"] == "noti" for c in consent_repo.list_active_consents(db, user_id))


def get_settings(db: Session, user_id: str) -> dict:
    row = notification_repo.get_settings(db, user_id)
    values = dict(row) if row else DEFAULT_SETTINGS
    return {**values, "noti_consented": noti_consented(db, user_id)}


def save_settings(db: Session, user_id: str, body: NotificationSettingsIn) -> dict:
    notification_repo.upsert_settings(db, user_id, body.model_dump())
    return get_settings(db, user_id)


def register_device(db: Session, user_id: str, body: DeviceIn) -> dict:
    row = notification_repo.upsert_device(db, user_id, body.platform, body.push_token)
    return {
        "device_id": str(row["id"]),
        "platform": row["platform"],
        "last_seen_at": row["last_seen_at"],
    }


def revoke_device(db: Session, user_id: str, device_id: str):
    """내 기기 아님 → 404. 이미 끔 → 그대로"""
    if not notification_repo.revoke_device(db, user_id, device_id):
        raise AppError(404, "NOT_FOUND", "기기를 찾을 수 없어요.")
