"""정기 알림 대상 조회 (시각은 한국 시간 기준)

공통: 보낼 시각 <= 지금 < 보낼 시각 + 늦게 보내기 한도 (서버 멈춤 뒤 새벽 발송 방지)
     탈퇴 사용자 X · 삭제 예정 공간 X
"""
from sqlalchemy import text
from sqlalchemy.orm import Session


KST = "Asia/Seoul"

# 보낼 시각 window (:at = 보낼 시각 timestamptz 식)
def window(at: str) -> str:
    return f"({at}) <= now() AND ({at}) > now() - make_interval(hours => :late_hours)"


NOT_DELETING = """
    NOT EXISTS (
        SELECT 1 FROM parent_deletions d
        WHERE d.target_parent_id = {p}.id AND d.status IN ('scheduled', 'executing')
    )
"""


def overdue_checklists(db: Session, hour: int, late_hours: int):
    """확인 날짜 다음 날 {hour}시: 안 냈고 취소 안 된 체크리스트"""
    at = f"((c.due_date + 1) + make_time(:hour, 0, 0)) AT TIME ZONE '{KST}'"
    return db.execute(
        text(f"""
            SELECT c.id, c.parent_id, c.to_user_id, c.due_date, p.nickname
            FROM checklists c
            JOIN parents p ON p.id = c.parent_id
            JOIN users u ON u.id = c.to_user_id
            WHERE c.submitted_at IS NULL AND c.cancelled_at IS NULL
              AND u.withdrawn_at IS NULL
              AND {NOT_DELETING.format(p="p")}
              AND {window(at)}
        """),
        {"hour": hour, "late_hours": late_hours}
    ).mappings().all()


def briefing_targets(db: Session, hour: int, late_hours: int):
    """조사일 전날 {hour}시: 그 공간 가족 모두"""
    at = f"((p.survey_date - 1) + make_time(:hour, 0, 0)) AT TIME ZONE '{KST}'"
    return db.execute(
        text(f"""
            SELECT p.id AS parent_id, p.nickname, p.survey_date, fm.user_id
            FROM parents p
            JOIN family_members fm ON fm.parent_id = p.id
            JOIN users u ON u.id = fm.user_id
            WHERE p.survey_date IS NOT NULL
              AND u.withdrawn_at IS NULL
              AND {NOT_DELETING.format(p="p")}
              AND {window(at)}
        """),
        {"hour": hour, "late_hours": late_hours}
    ).mappings().all()


def condition_targets(db: Session, hour: int, late_hours: int):
    """매일 {hour}시: 오늘 컨디션 없는 공간의 기록할 수 있는 가족 (관리자·쓰기)

    오늘 = 한국 날짜. 공간당 하루 1건 (uq_condition_day) → 누가 적었든 적혀 있으면 X
    """
    today = f"(now() AT TIME ZONE '{KST}')::date"
    at = f"({today} + make_time(:hour, 0, 0)) AT TIME ZONE '{KST}'"
    return db.execute(
        text(f"""
            SELECT p.id AS parent_id, p.nickname, {today} AS day, fm.user_id
            FROM parents p
            JOIN family_members fm ON fm.parent_id = p.id AND fm.role IN ('admin', 'writer')
            JOIN users u ON u.id = fm.user_id
            WHERE u.withdrawn_at IS NULL
              AND {NOT_DELETING.format(p="p")}
              AND NOT EXISTS (
                  SELECT 1 FROM conditions c WHERE c.parent_id = p.id AND c.date = {today}
              )
              AND {window(at)}
        """),
        {"hour": hour, "late_hours": late_hours}
    ).mappings().all()
