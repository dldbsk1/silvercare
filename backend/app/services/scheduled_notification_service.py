"""정기 알림 (워커 /notify, Cloud Scheduler 매시 정각 · 로컬 워커 10분마다)

| 종류 | 시각 (KST) | 받는 사람 | 설정 |
| checklist_overdue | 확인 날짜 다음 날 10:00 | 안 낸 체크리스트 받은 사람 | 할 일 |
| survey_briefing | 조사일 전날 20:00 | 그 공간 가족 모두 | 브리핑 |
| condition_reminder | 매일 20:00 | 오늘 컨디션 없는 공간의 관리자·쓰기 가족 | 컨디션 (CONDITION_REMINDER_ENABLED) |

- 중복 방지: dedupe_key (여러 번 실행·여러 워커 → 1번만)
- 늦게 보내기 한도 3시간 (서버 멈춘 뒤 새벽에 몰아 보내기 X)
- 종류마다 따로 트랜잭션 (하나 실패해도 나머지 진행)
"""
import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.repositories import scheduled_notification_repo as repo
from app.services import notification_service as notifications


logger = logging.getLogger("silvercare.notify")

OVERDUE_HOUR = 10
BRIEFING_HOUR = 20
CONDITION_HOUR = 20
LATE_HOURS = 3


def checklist_overdue(db: Session) -> int:
    count = 0
    for row in repo.overdue_checklists(db, OVERDUE_HOUR, LATE_HOURS):
        due = row["due_date"]
        if notifications.notify(
            db, str(row["to_user_id"]), str(row["parent_id"]), "checklist_overdue",
            f"{row['nickname']} 체크리스트 확인 날짜가 지났어요",
            f"{due.month}/{due.day}까지였어요. 본 것만이라도 답해 주세요.",
            {"checklist_id": str(row["id"])},
            setting=notifications.TASKS,
            dedupe_key=f"checklist_overdue:{row['id']}",
        ):
            count += 1
    return count


def survey_briefing(db: Session) -> int:
    count = 0
    for row in repo.briefing_targets(db, BRIEFING_HOUR, LATE_HOURS):
        if notifications.notify(
            db, str(row["user_id"]), str(row["parent_id"]), "survey_briefing",
            f"내일 {row['nickname']} 방문 조사가 있어요",
            "조사원에게 꼭 전할 내용을 미리 확인해 보세요.",
            {"survey_date": row["survey_date"].isoformat()},
            setting=notifications.BRIEFING,
            dedupe_key=f"survey_briefing:{row['parent_id']}:{row['survey_date']}:{row['user_id']}",
        ):
            count += 1
    return count


def condition_reminder(db: Session) -> int:
    if not settings.CONDITION_REMINDER_ENABLED:
        return 0
    count = 0
    for row in repo.condition_targets(db, CONDITION_HOUR, LATE_HOURS):
        if notifications.notify(
            db, str(row["user_id"]), str(row["parent_id"]), "condition_reminder",
            f"오늘 {row['nickname']} 컨디션은 어떠셨나요?",
            "한 번만 눌러 남겨 두면 좋은 날·힘든 날을 비교할 수 있어요.",
            {"date": row["day"].isoformat()},
            setting=notifications.CONDITION,
            dedupe_key=f"condition_reminder:{row['parent_id']}:{row['day']}:{row['user_id']}",
        ):
            count += 1
    return count


JOBS = {
    "checklist_overdue": checklist_overdue,
    "survey_briefing": survey_briefing,
    "condition_reminder": condition_reminder,
}


def run(session_factory) -> dict[str, int]:
    """종류별 새 세션·트랜잭션. 결과 = 종류별 새로 만든 알림 수 (실패 → -1)"""
    result = {}
    for name, job in JOBS.items():
        try:
            with session_factory() as db:
                with db.begin():
                    result[name] = job(db)
        except Exception:
            logger.exception("정기 알림 실패 %s", name)
            result[name] = -1
    if any(result.values()):
        logger.info("정기 알림 %s", result)
    return result
