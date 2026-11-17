"""관찰 체크리스트 (A-TASK, SCR_A_310). 트랜잭션은 라우터가 연다.

- 보내기: writer·admin → 같은 공간 writer·admin (나 포함). 항목 1~10개, 재활 제외 42개 중
- 조회: 보낸·받은 사람만 (그 외 404, 존재 숨김). 보낸 사람은 진행 중 답도 봄
- 답: 받은 사람만, 보내기 전까지 덮어쓰기. 척도별 선택지 (adl / yesno)
- 제출: 한 트랜잭션 → 못 봤어요 제외 답마다 기록 1건 (분류 = 그 항목, 사용자 분류). 다시 제출 → 같은 응답
- 취소: 사용자 기능 없음. 가족 나가기·내보내기·탈퇴 → 열린 것 자동 취소 + 상대방 알림
- 점수·등급 없음 (POL-03): 답 = 관찰 사실 문구 그대로
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.repositories import checklist_repo, family_repo, parent_repo, record_repo
from app.schemas.checklists import AnswerIn, ChecklistCreateIn, ChecklistListQuery
from app.services import notification_service
from app.services.access import ParentAccess, ensure_not_locked, ensure_write, get_parent_access
from app.services.dday import today_kst


CHOICES = {
    "adl": ["alone", "little", "full", "not_seen"],
    "yesno": ["yes", "no", "not_seen"],
}
NOT_SEEN = "not_seen"

# 기록 글에 쓰는 답 문구 (화면 문구와 같음)
ANSWER_TEXT = {
    "alone": "혼자 하심",
    "little": "조금 도와드림",
    "full": "다 도와드림",
    "yes": "있었어요",
    "no": "없었어요",
}

AREA_LABEL = {
    "physical": "신체",
    "cognitive": "인지",
    "behavior": "행동변화",
    "nursing": "간호처치",
}

WRITER_ROLES = ("admin", "writer")
MAX_DUE_DAYS = 30
RECENT_DAYS = 30
NOT_SEEN_DAYS = 60
SUGGEST_MAX = 6
# 기록 없는 새 공간: 영역별 앞에서 2개씩
NEW_SPACE_AREAS = ("physical", "cognitive", "behavior")
NEW_SPACE_PER_AREA = 2

REASON_ORDER = {"no_records": 0, "few_records": 1, "not_seen_before": 2}


def not_found() -> AppError:
    return AppError(404, "CHECKLIST_NOT_FOUND", "체크리스트를 찾을 수 없어요.")


# ── 고르기 목록·추천 ──

def draft(db: Session, access: ParentAccess, now: datetime | None = None) -> dict:
    ensure_write(access)
    now = now or datetime.now(timezone.utc)

    items = checklist_repo.checklist_items(db)
    stats = checklist_repo.record_stats(db, access.parent_id, now - timedelta(days=RECENT_DAYS))
    not_seen = checklist_repo.recent_not_seen(
        db, access.parent_id, now - timedelta(days=NOT_SEEN_DAYS)
    )
    in_open = checklist_repo.open_item_codes(db, access.parent_id)

    reasons = {}
    for item in items:
        code = item["code"]
        if code in in_open:
            continue
        days = stats.get(code, {}).get("days", 0)
        if days == 0:
            reasons[code] = "no_records"
        elif days == 1:
            reasons[code] = "few_records"
        elif code in not_seen:
            reasons[code] = "not_seen_before"

    suggested = suggest(items, reasons, has_records=bool(stats))
    suggested_set = set(suggested)

    areas: dict[str, list] = {}
    for item in items:
        code = item["code"]
        areas.setdefault(item["area"], []).append({
            "item_code": code,
            "label": item["label"],
            "hint": item["hint"],
            "scale": item["scale"],
            "last_recorded_on": stats.get(code, {}).get("last_on"),
            "reason": reasons.get(code) if code in suggested_set else None,
        })

    return {
        "suggested_codes": suggested,
        "areas": [
            {"area": area, "label": AREA_LABEL.get(area, area), "items": rows}
            for area, rows in areas.items()
        ],
    }


def suggest(items, reasons: dict[str, str], has_records: bool) -> list[str]:
    """이유 순위 → 조사표 순서, 최대 6. 기록 없는 공간 → 영역 섞기"""
    if not has_records:
        picked = []
        for area in NEW_SPACE_AREAS:
            codes = [i["code"] for i in items if i["area"] == area and i["code"] in reasons]
            picked += codes[:NEW_SPACE_PER_AREA]
        return picked[:SUGGEST_MAX]

    order = {item["code"]: item["sort_order"] for item in items}
    ranked = sorted(reasons, key=lambda code: (REASON_ORDER[reasons[code]], order[code]))
    return ranked[:SUGGEST_MAX]


# ── 보내기 ──

def create(db: Session, access: ParentAccess, body: ChecklistCreateIn, now: datetime | None = None) -> dict:
    ensure_write(access)
    today = today_kst(now)

    if not today <= body.due_date <= today + timedelta(days=MAX_DUE_DAYS):
        raise AppError(422, "INVALID_DUE_DATE", f"확인 날짜는 오늘부터 {MAX_DUE_DAYS}일 안에서 골라 주세요.")

    codes = body.item_codes
    allowed = {item["code"] for item in checklist_repo.checklist_items(db)}
    if len(set(codes)) != len(codes) or not set(codes) <= allowed:
        raise AppError(
            422, "ITEM_NOT_ALLOWED", "체크리스트로 보낼 수 있는 항목이 아니에요.",
            details={"item_codes": sorted(set(codes) - allowed)}
        )

    to_user_id = str(body.to_user_id)
    if family_repo.get_role(db, access.parent_id, to_user_id) not in WRITER_ROLES:
        raise AppError(400, "RECIPIENT_NOT_WRITER", "기록할 수 있는 가족에게만 보낼 수 있어요.")

    checklist_id = checklist_repo.insert_checklist(
        db, access.parent_id, access.user_id, to_user_id, body.due_date
    )
    checklist_repo.insert_tasks(
        db, checklist_id, access.parent_id, access.user_id, to_user_id, body.due_date, codes
    )

    row = checklist_repo.get_checklist(db, checklist_id)
    if to_user_id != access.user_id:
        nickname = parent_repo.get_nickname(db, access.parent_id) or "부모님"
        notification_service.notify(
            db, to_user_id, access.parent_id, "checklist_received",
            f"{row['from_name'] or '가족'}님이 {nickname} 관찰 체크리스트를 보냈어요",
            f"{len(codes)}개 항목 · {body.due_date.month}/{body.due_date.day}까지",
            {"checklist_id": checklist_id},
        )

    return to_out(db, row, access.user_id, today)


# ── 조회 ──

def load_for(db: Session, user_id: str, checklist_id: str, for_update: bool = False):
    """(access, row). 없음·가족 아님·보낸/받은 사람 아님 → 모두 404"""
    row = checklist_repo.get_checklist(db, checklist_id, for_update=for_update)
    if row is None:
        raise not_found()
    try:
        access = get_parent_access(db, user_id, str(row["parent_id"]))
    except AppError:
        raise not_found()
    if user_id not in (str(row["from_user_id"]), str(row["to_user_id"])):
        raise not_found()
    return access, row


def get(db: Session, user_id: str, checklist_id: str) -> dict:
    _, row = load_for(db, user_id, checklist_id)
    return to_out(db, row, user_id, today_kst())


def list_(db: Session, access: ParentAccess, query: ChecklistListQuery) -> dict:
    rows = checklist_repo.list_checklists(
        db, access.parent_id, access.user_id, query.box, query.state, query.limit
    )
    has_more = len(rows) > query.limit
    rows = rows[:query.limit]
    today = today_kst()
    return {
        "data": [to_summary(row, access.user_id, today) for row in rows],
        "meta": {
            "next_cursor": None,
            "has_more": has_more,
            "total": checklist_repo.count_checklists(
                db, access.parent_id, access.user_id, query.box, query.state
            ),
        },
    }


def status_of(row, today: date) -> str:
    if row["submitted_at"] is not None:
        return "submitted"
    if row["cancelled_at"] is not None:
        return "cancelled"
    if row["due_date"] < today:
        return "overdue"
    return "in_progress" if row["answered_items"] else "pending"


def user_ref(user_id, name, me: str) -> dict:
    return {"id": str(user_id), "name": name, "is_me": str(user_id) == me}


def to_summary(row, user_id: str, today: date) -> dict:
    return {
        "id": str(row["id"]),
        "parent_id": str(row["parent_id"]),
        "from_user": user_ref(row["from_user_id"], row["from_name"], user_id),
        "to_user": user_ref(row["to_user_id"], row["to_name"], user_id),
        "due_date": row["due_date"],
        "status": status_of(row, today),
        "answered_items": row["answered_items"],
        "total_items": row["total_items"],
        "created_at": row["created_at"],
        "submitted_at": row["submitted_at"],
        "cancelled_at": row["cancelled_at"],
    }


def to_task(task) -> dict:
    return {
        "task_id": str(task["id"]),
        "item_code": task["item_code"],
        "label": task["label"],
        "area": task["area"],
        "scale": task["scale"],
        "hint": task["hint"],
        "choices": CHOICES[task["scale"]],
        "answer": task["answer"],
        "note": task["note"],
        "answered_at": task["done_at"] if task["answer"] is not None else None,
        "record_id": str(task["answer_record_id"]) if task["answer_record_id"] else None,
    }


def to_out(db: Session, row, user_id: str, today: date) -> dict:
    tasks = checklist_repo.list_tasks(db, str(row["id"]))
    return {
        **to_summary(row, user_id, today),
        "is_recipient": str(row["to_user_id"]) == user_id,
        "items": [to_task(task) for task in tasks],
    }


# ── 답·제출 ──

def ensure_open(row):
    if row["submitted_at"] is not None:
        raise AppError(409, "CHECKLIST_SUBMITTED", "이미 보낸 체크리스트예요.")
    if row["cancelled_at"] is not None:
        raise AppError(409, "CHECKLIST_CANCELLED", "취소된 체크리스트예요.")


def ensure_writer(access: ParentAccess):
    """보낸 뒤 보기 전용으로 바뀐 받은 사람 → 답·제출 X. 공간 삭제 예정 → 409"""
    ensure_not_locked(access)
    if access.role not in WRITER_ROLES:
        raise AppError(403, "PERMISSION_DENIED", "보기 전용 권한이에요.")


def ensure_recipient(row, user_id: str):
    if str(row["to_user_id"]) != user_id:
        raise AppError(403, "NOT_RECIPIENT", "받은 사람만 답할 수 있어요.")


def answer(db: Session, user_id: str, checklist_id: str, task_id: str, body: AnswerIn) -> dict:
    access, row = load_for(db, user_id, checklist_id, for_update=True)
    ensure_recipient(row, user_id)
    ensure_open(row)
    ensure_writer(access)

    task = checklist_repo.get_task(db, checklist_id, task_id)
    if task is None:
        raise AppError(404, "NOT_FOUND", "항목을 찾을 수 없어요.")
    if body.answer not in CHOICES[task["scale"]]:
        raise AppError(
            422, "INVALID_ANSWER", "이 항목에 맞는 답을 골라 주세요.",
            details={"choices": CHOICES[task["scale"]]}
        )

    checklist_repo.save_answer(db, task_id, body.answer, body.note)
    row = checklist_repo.get_checklist(db, checklist_id)
    return {
        "item": to_task(checklist_repo.get_task(db, checklist_id, task_id)),
        "answered_items": row["answered_items"],
        "total_items": row["total_items"],
    }


def record_text(label: str, answer_code: str, note: str | None) -> str:
    """기록 글: "화장실 사용하기 — 조금 도와드림. 밤에는 부축이 필요해요" """
    body = f"{label} — {ANSWER_TEXT[answer_code]}"
    return f"{body}. {note}" if note else body


def submit(db: Session, user_id: str, checklist_id: str, now: datetime | None = None) -> dict:
    access, row = load_for(db, user_id, checklist_id, for_update=True)
    ensure_recipient(row, user_id)
    today = today_kst(now)

    # 다시 보냄 → 같은 응답 (기록 다시 안 만듦)
    if row["submitted_at"] is not None:
        return to_out(db, row, user_id, today)
    ensure_open(row)
    ensure_writer(access)

    tasks = checklist_repo.list_tasks(db, checklist_id)
    missing = [str(t["id"]) for t in tasks if t["answer"] is None]
    if missing:
        raise AppError(
            409, "INCOMPLETE_ANSWERS", "아직 답하지 않은 항목이 있어요.",
            details={"task_ids": missing}
        )

    recorded_at = now or datetime.now(timezone.utc)
    for task in tasks:
        if task["answer"] == NOT_SEEN:
            continue
        created = record_repo.insert_record(
            db,
            parent_id=access.parent_id,
            author_id=user_id,
            input_type="checklist",
            source="direct",
            text_value=record_text(task["label"], task["answer"], task["note"]),
            recorded_at=recorded_at,
            occurred_at=task["done_at"],
        )
        record_id = str(created["id"])
        record_repo.replace_items(db, record_id, [(task["item_code"], None)], "user")
        record_repo.set_classification(db, record_id, "classified", "user", "completed")
        checklist_repo.set_answer_record(db, str(task["id"]), record_id)

    if checklist_repo.mark_submitted(db, checklist_id) == 0:
        raise AppError(409, "CHECKLIST_SUBMITTED", "이미 보낸 체크리스트예요.")

    row = checklist_repo.get_checklist(db, checklist_id)
    if str(row["from_user_id"]) != user_id:
        notification_service.notify(
            db, str(row["from_user_id"]), access.parent_id, "checklist_submitted",
            f"{row['to_name'] or '가족'}님이 체크리스트에 모두 답했어요",
            None,
            {"checklist_id": checklist_id},
        )
    return to_out(db, row, user_id, today)


# ── 자동 취소 (가족 나가기·내보내기·탈퇴) ──

def cancel_open(db: Session, user_id: str, parent_id: str | None = None):
    """이 사람이 보낸·받은 열린 체크리스트 취소 + 상대방 알림. parent_id 없음 → 모든 공간"""
    for row in checklist_repo.cancel_open(db, user_id, parent_id):
        other = str(row["to_user_id"]) if str(row["from_user_id"]) == user_id else str(row["from_user_id"])
        if other == user_id:
            continue
        notification_service.notify(
            db, other, str(row["parent_id"]), "checklist_cancelled",
            "체크리스트가 취소됐어요",
            "보내거나 받은 가족이 가족 공간을 떠났어요.",
            {"checklist_id": str(row["id"])},
        )
