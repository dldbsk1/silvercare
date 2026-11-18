"""알림 설정·기기 토큰 (A-SET-002). 트랜잭션은 라우터가 연다.

- 저장 전 → 모두 켜짐 (GET은 DB에 쓰지 않음)
- 푸시 = 알림 동의(noti) + 해당 설정 켜짐 + 끄지 않은 기기. 발송 = 워커 send_push (FCM)
- 기기: 같은 토큰 → 1건 (다른 사용자 토큰이면 나에게 옮김). 끄기 = revoked_at (행 유지)
- 목록: 나간 공간 알림 X
"""
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.db import fcm
from app.repositories import consent_repo, notification_repo
from app.services import pagination
from app.workers import queue
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


# ── 알림 저장 (설정 꺼짐 → 저장 X) + 푸시 작업 등록 ──
#
# 설정 스위치: 할 일 (체크리스트) · 브리핑 (조사 전날) · 컨디션 (저녁)
# 스위치 없는 알림 (가족 합류·댓글·기록 실패) → setting=None, 항상 저장

TASKS = "tasks_enabled"
BRIEFING = "briefing_enabled"
CONDITION = "condition_enabled"

SEND_PUSH_JOB = "send_push"


def setting_enabled(db: Session, user_id: str, setting: str | None) -> bool:
    if setting is None:
        return True
    row = notification_repo.get_settings(db, user_id)
    return row[setting] if row else DEFAULT_SETTINGS[setting]


def push_target(db: Session, user_id: str) -> bool:
    """푸시 받을 수 있음 = 발송 켜짐 + 알림 동의 + 끄지 않은 기기"""
    return (
        settings.PUSH_PROVIDER != "none"
        and noti_consented(db, user_id)
        and notification_repo.has_active_device(db, user_id)
    )


def notify(
    db: Session, user_id: str, parent_id: str | None, type_: str, title: str,
    body: str | None = None, payload: dict | None = None, setting: str | None = TASKS,
    dedupe_key: str | None = None
) -> str | None:
    """호출한 쪽 트랜잭션 안에서 저장 + 푸시 작업 등록 (같이 커밋). 저장 안 함 → None"""
    if not setting_enabled(db, user_id, setting):
        return None
    notification_id = notification_repo.insert_notification(
        db, user_id, parent_id, type_, title, body, payload, dedupe_key
    )
    if notification_id and push_target(db, user_id):
        queue.enqueue(
            db, SEND_PUSH_JOB, {"notification_id": notification_id},
            target_type="notification", target_id=notification_id, max_attempts=4,
        )
    return notification_id


def notify_record_failed(db: Session, record, stage: str):
    """받아쓰기·분류 최종 실패 → 작성자 알림 (작업 최종 실패 1번당 1건)

    stage: transcription (녹음 → 글 실패) / classification (분류 실패)
    """
    record_id = str(record["id"])
    voice = stage == "transcription"
    notify(
        db, str(record["author_id"]), str(record["parent_id"]), "record_failed",
        "녹음을 글로 옮기지 못했어요" if voice else "기록을 항목에 나누지 못했어요",
        "다시 시도하거나 글로 적어 주세요." if voice else "기록은 저장돼 있어요. 다시 시도해 주세요.",
        {"record_id": record_id},
        setting=None,
    )


# ── 알림 목록 (POP_A_NOTI) ──

def to_out(row) -> dict:
    return {
        "notification_id": str(row["id"]),
        "type": row["type"],
        "parent_id": str(row["parent_id"]) if row["parent_id"] else None,
        "title": row["title"],
        "body": row["body"],
        "payload": row["payload"] or {},
        "created_at": row["created_at"],
        "read_at": row["read_at"],
    }


def read_cursor(cursor: str, scope: dict) -> tuple[datetime, str]:
    position = pagination.decode_cursor(cursor, scope)
    try:
        created_at, notification_id = position
        return datetime.fromisoformat(created_at), str(UUID(notification_id))
    except ValueError:
        raise pagination.invalid_cursor()


def list_notifications(db: Session, user_id: str, limit: int, cursor: str | None) -> dict:
    """최신순. 안 읽은 개수 = 모든 페이지 같은 값"""
    scope = {"user_id": user_id}
    after = read_cursor(cursor, scope) if cursor else None
    rows = notification_repo.list_notifications(db, user_id, limit + 1, after)
    has_more = len(rows) > limit
    rows = rows[:limit]

    next_cursor = None
    if has_more:
        last = rows[-1]
        next_cursor = pagination.encode_cursor([last["created_at"].isoformat(), str(last["id"])], scope)

    return {
        "data": [to_out(r) for r in rows],
        "meta": {
            "next_cursor": next_cursor,
            "has_more": has_more,
            "unread_count": notification_repo.count_unread(db, user_id),
        },
    }


def mark_read(db: Session, user_id: str, notification_id: str) -> dict:
    """내 알림 아님·나간 공간 알림 → 404. 이미 읽음 → 그대로"""
    row = notification_repo.mark_read(db, user_id, notification_id)
    if row is None:
        raise AppError(404, "NOT_FOUND", "알림을 찾을 수 없어요.")
    return to_out(row)


def mark_all_read(db: Session, user_id: str):
    notification_repo.mark_all_read(db, user_id)


def count_unread(db: Session, user_id: str) -> int:
    return notification_repo.count_unread(db, user_id)


# ── 푸시 발송 (워커 send_push) ──

@dataclass(frozen=True)
class PushTarget:
    notification_id: str
    title: str
    body: str | None
    data: dict[str, str]
    devices: list[tuple[str, str]]


def push_data(row) -> dict[str, str]:
    """FCM data = 문자열만. 앱: type + payload로 화면 이동"""
    data = {"notification_id": str(row["id"]), "type": row["type"]}
    if row["parent_id"]:
        data["parent_id"] = str(row["parent_id"])
    for key, value in (row["payload"] or {}).items():
        if value is not None:
            data[key] = str(value)
    return data


def load_push(db: Session, notification_id: str) -> PushTarget | None:
    """보낼 것 없음 → None: 알림 삭제됨 · 이미 보냄 · 읽음 · 동의 철회 · 기기 없음"""
    row = notification_repo.get_for_push(db, notification_id)
    if row is None or row["sent_at"] is not None or row["read_at"] is not None:
        return None
    user_id = str(row["user_id"])
    if not noti_consented(db, user_id):
        return None
    devices = notification_repo.active_tokens(db, user_id)
    if not devices:
        return None
    return PushTarget(
        notification_id=notification_id,
        title=row["title"],
        body=row["body"],
        data=push_data(row),
        devices=devices,
    )


class PushRetry(Exception):
    """모든 기기 일시 오류 → 작업 재시도"""


def deliver(target: PushTarget) -> tuple[bool, list[str]]:
    """(1대라도 보냄, 무효 기기 id). 트랜잭션 밖 (FCM 호출 동안 DB 연결 점유 X)"""
    sent = False
    invalid: list[str] = []
    retry = False
    for device_id, token in target.devices:
        result = fcm.send(token, target.title, target.body, target.data)
        if result == fcm.Result.SENT:
            sent = True
        elif result == fcm.Result.INVALID:
            invalid.append(device_id)
        elif result == fcm.Result.RETRY:
            retry = True
    if retry and not sent:
        raise PushRetry(target.notification_id)
    return sent, invalid


def finish_push(db: Session, notification_id: str, sent: bool, invalid: list[str]):
    notification_repo.revoke_tokens(db, invalid)
    if sent:
        notification_repo.mark_sent(db, notification_id)
