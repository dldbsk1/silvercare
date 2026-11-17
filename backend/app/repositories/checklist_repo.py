from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.repositories.record_repo import USER_NAME


# 열린 체크리스트 = 미제출·미취소
OPEN = "c.submitted_at IS NULL AND c.cancelled_at IS NULL"

CHECKLIST_COLUMNS = f"""
    c.id, c.parent_id, c.from_user_id, c.to_user_id, c.due_date,
    c.created_at, c.submitted_at, c.cancelled_at,
    (SELECT {USER_NAME} FROM users u WHERE u.id = c.from_user_id) AS from_name,
    (SELECT {USER_NAME} FROM users u WHERE u.id = c.to_user_id) AS to_name,
    (SELECT count(*) FROM tasks t WHERE t.checklist_id = c.id) AS total_items,
    (SELECT count(*) FROM tasks t WHERE t.checklist_id = c.id AND t.answer IS NOT NULL) AS answered_items
"""

# 기록 날짜 (한국 시간)
RECORD_DAY = "(COALESCE(r.occurred_at, r.recorded_at) AT TIME ZONE 'Asia/Seoul')::date"


# ── 고르기 목록·추천 ──

def checklist_items(db: Session):
    """가족 체크리스트 대상 42개 (재활 제외), 조사표 순서"""
    return db.execute(
        text("""
            SELECT code, label, area::text AS area, scale::text AS scale,
                   observation_hint AS hint, sort_order
            FROM survey_items
            WHERE family_checklist
            ORDER BY sort_order
        """)
    ).mappings().all()


def record_stats(db: Session, parent_id: str, since: datetime) -> dict[str, dict]:
    """항목별 {last_on: 마지막 기록 날짜, days: since 이후 서로 다른 날 수}

    정상 기록 + 처리 완료만 (제외·처리 중·실패 X)
    """
    rows = db.execute(
        text(f"""
            SELECT ri.item_code,
                   max({RECORD_DAY}) AS last_on,
                   count(DISTINCT {RECORD_DAY})
                       FILTER (WHERE COALESCE(r.occurred_at, r.recorded_at) >= :since) AS days
            FROM records r
            JOIN record_items ri ON ri.record_id = r.id
            WHERE r.parent_id = :p
              AND r.status = 'normal' AND r.processing_status = 'completed'
            GROUP BY ri.item_code
        """),
        {"p": parent_id, "since": since}
    ).mappings().all()
    return {row["item_code"]: {"last_on": row["last_on"], "days": row["days"]} for row in rows}


def recent_not_seen(db: Session, parent_id: str, since: datetime) -> set[str]:
    """제출된 체크리스트에서 "못 봤어요" 답한 항목"""
    rows = db.execute(
        text("""
            SELECT DISTINCT t.item_code
            FROM tasks t
            JOIN checklists c ON c.id = t.checklist_id
            WHERE t.parent_id = :p AND t.answer = 'not_seen'
              AND c.submitted_at IS NOT NULL AND t.done_at >= :since
        """),
        {"p": parent_id, "since": since}
    ).scalars().all()
    return set(rows)


def open_item_codes(db: Session, parent_id: str) -> set[str]:
    rows = db.execute(
        text(f"""
            SELECT DISTINCT t.item_code
            FROM tasks t
            JOIN checklists c ON c.id = t.checklist_id
            WHERE c.parent_id = :p AND {OPEN}
        """),
        {"p": parent_id}
    ).scalars().all()
    return set(rows)


# ── 만들기 ──

def insert_checklist(db: Session, parent_id: str, from_id: str, to_id: str, due_date: date) -> str:
    return str(db.execute(
        text("""
            INSERT INTO checklists (parent_id, from_user_id, to_user_id, due_date)
            VALUES (:p, :f, :t, :d)
            RETURNING id
        """),
        {"p": parent_id, "f": from_id, "t": to_id, "d": due_date}
    ).scalar_one())


def insert_tasks(
    db: Session, checklist_id: str, parent_id: str, from_id: str, to_id: str,
    due_date: date, codes: list[str]
):
    """항목마다 1행. question = 보낼 때 설명 복사 (문구 바뀌어도 보낸 그대로)"""
    db.execute(
        text("""
            INSERT INTO tasks
                (checklist_id, parent_id, item_code, question, from_user, to_user, due_date)
            SELECT :c, :p, si.code, si.observation_hint, :f, :t, :d
            FROM survey_items si
            WHERE si.code = ANY(:codes)
        """),
        {"c": checklist_id, "p": parent_id, "f": from_id, "t": to_id, "d": due_date,
         "codes": codes}
    )


# ── 조회 ──

def get_checklist(db: Session, checklist_id: str, for_update: bool = False):
    if for_update:
        # 묶음 행 잠금 (답·제출 경쟁). 계산 칸 있는 SELECT에는 FOR UPDATE 못 씀 → 따로
        db.execute(
            text("SELECT 1 FROM checklists WHERE id = :id FOR UPDATE"), {"id": checklist_id}
        )
    return db.execute(
        text(f"SELECT {CHECKLIST_COLUMNS} FROM checklists c WHERE c.id = :id"),
        {"id": checklist_id}
    ).mappings().first()


TASK_COLUMNS = """
    t.id, t.item_code, t.question AS hint, t.answer::text AS answer, t.note,
    t.done_at, t.answer_record_id,
    si.label, si.area::text AS area, si.scale::text AS scale
"""


def list_tasks(db: Session, checklist_id: str):
    """답하기 순서 = 영역 → 조사표 순서 (sort_order)"""
    return db.execute(
        text(f"""
            SELECT {TASK_COLUMNS}
            FROM tasks t
            JOIN survey_items si ON si.code = t.item_code
            WHERE t.checklist_id = :c
            ORDER BY si.sort_order
        """),
        {"c": checklist_id}
    ).mappings().all()


def get_task(db: Session, checklist_id: str, task_id: str):
    return db.execute(
        text(f"""
            SELECT {TASK_COLUMNS}
            FROM tasks t
            JOIN survey_items si ON si.code = t.item_code
            WHERE t.checklist_id = :c AND t.id = :id
        """),
        {"c": checklist_id, "id": task_id}
    ).mappings().first()


def list_checklists(
    db: Session, parent_id: str, user_id: str, box: str, state: str, limit: int
):
    """열린 것 확인 날짜 빠른 순 → 닫힌 것 최근 순. limit + 1 조회 (다음 여부)"""
    conditions, params = list_conditions(parent_id, user_id, box, state)
    return db.execute(
        text(f"""
            SELECT {CHECKLIST_COLUMNS}
            FROM checklists c
            WHERE {" AND ".join(conditions)}
            ORDER BY (c.submitted_at IS NOT NULL OR c.cancelled_at IS NOT NULL),
                     CASE WHEN {OPEN} THEN c.due_date END,
                     COALESCE(c.submitted_at, c.cancelled_at, c.created_at) DESC,
                     c.id DESC
            LIMIT :limit
        """),
        {**params, "limit": limit + 1}
    ).mappings().all()


def count_checklists(db: Session, parent_id: str, user_id: str, box: str, state: str) -> int:
    conditions, params = list_conditions(parent_id, user_id, box, state)
    return db.execute(
        text(f"SELECT count(*) FROM checklists c WHERE {' AND '.join(conditions)}"), params
    ).scalar_one()


def list_conditions(parent_id: str, user_id: str, box: str, state: str) -> tuple[list[str], dict]:
    column = "c.to_user_id" if box == "received" else "c.from_user_id"
    conditions = ["c.parent_id = :p", f"{column} = :u"]
    if state == "open":
        conditions.append(OPEN)
    elif state == "done":
        conditions.append(f"NOT ({OPEN})")
    return conditions, {"p": parent_id, "u": user_id}


def count_open_received(db: Session, parent_id: str, user_id: str) -> int:
    return count_checklists(db, parent_id, user_id, "received", "open")


# ── 답·제출·취소 ──

def save_answer(db: Session, task_id: str, answer: str, note: str | None):
    """같은 답·메모 → 그대로 (답한 시각 유지)"""
    db.execute(
        text("""
            UPDATE tasks
            SET answer = CAST(:a AS task_answer_enum), note = :n, done_at = now()
            WHERE id = :id
              AND (answer IS DISTINCT FROM CAST(:a AS task_answer_enum)
                   OR note IS DISTINCT FROM :n)
        """),
        {"id": task_id, "a": answer, "n": note}
    )


def set_answer_record(db: Session, task_id: str, record_id: str):
    db.execute(
        text("UPDATE tasks SET answer_record_id = :r WHERE id = :id"),
        {"id": task_id, "r": record_id}
    )


def mark_submitted(db: Session, checklist_id: str) -> int:
    return db.execute(
        text(f"""
            UPDATE checklists c SET submitted_at = now()
            WHERE c.id = :id AND {OPEN}
        """),
        {"id": checklist_id}
    ).rowcount


def cancel_open(db: Session, user_id: str, parent_id: str | None = None):
    """자동 취소: 이 사람이 보낸·받은 열린 체크리스트 (parent_id 없음 → 모든 공간)

    취소된 행 반환 (상대방 알림용)
    """
    params = {"u": user_id}
    parent_filter = ""
    if parent_id:
        parent_filter = "AND c.parent_id = :p"
        params["p"] = parent_id
    return db.execute(
        text(f"""
            UPDATE checklists c SET cancelled_at = now()
            WHERE (c.from_user_id = :u OR c.to_user_id = :u) AND {OPEN} {parent_filter}
            RETURNING c.id, c.parent_id, c.from_user_id, c.to_user_id
        """),
        params
    ).mappings().all()
