"""D-day (A-HOME-008). 한국 시간 기준 오늘

- 저장 X, 조회마다 계산 → 조사일 연기·취소(null) 즉시 반영
- status: not_set / upcoming / today / past (days_left 음수)
- 문구는 앱이 결정
"""
from datetime import date, datetime, timedelta, timezone


# 한국: 서머타임 없음 → 고정 오프셋 (Windows tzdata 의존 X)
KST = timezone(timedelta(hours=9))


def today_kst(now: datetime | None = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(KST).date()


def compute(survey_date: date | None, today: date) -> dict:
    if survey_date is None:
        return {"survey_date": None, "days_left": None, "status": "not_set"}

    days_left = (survey_date - today).days

    if days_left > 0:
        status = "upcoming"
    elif days_left == 0:
        status = "today"
    else:
        status = "past"

    return {"survey_date": survey_date, "days_left": days_left, "status": status}
