"""푸시 발송 작업

send_push: payload {notification_id}
1. 트랜잭션 A: 보낼 알림·기기 확인 (이미 보냄·읽음·동의 철회·기기 없음 → 끝)
2. 트랜잭션 밖: FCM 발송 (기기마다)
3. 트랜잭션 B: lease → 무효 기기 끄기 + sent_at

재시도: 모든 기기 일시 오류 → 30초 → 2분 → 8분 (max_attempts 4). 일부라도 성공 → 끝
중복 실행 (워커 회수): sent_at 있으면 다시 안 보냄. 발송 직후 중단 → 드물게 2번 (허용)
"""
from app.services import notification_service
from app.services.notification_service import PushRetry
from app.workers.tasks import Job, hold_lease, task


@task(notification_service.SEND_PUSH_JOB)
def send_push(db, job: Job):
    notification_id = job.payload["notification_id"]

    with db.begin():
        target = notification_service.load_push(db, notification_id)
    if target is None:
        return

    try:
        sent, invalid = notification_service.deliver(target)
    except PushRetry:
        raise RuntimeError("FCM 일시 오류 (모든 기기)")

    with db.begin():
        hold_lease(db, job)
        notification_service.finish_push(db, notification_id, sent, invalid)
