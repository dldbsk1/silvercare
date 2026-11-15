"""증상 기록 (A-SYM-001/002)

증상 칩 6개 (추천)
- 후보: 조사표 52항목 중 증상으로 볼 수 있는 행동변화 14 · 인지 7 (신체·간호·재활 → 증상 X)
- 우리 가족 기록 (최근 SUGGEST_DAYS 일, 모든 입력 방식) 에서 많이 분류된 항목 순
- 기록 적음 (후보 항목으로 분류된 기록 < SUGGEST_MIN_RECORDS) → 기본 6개 (디자인 키워드)
- 6개 안 차면 기본 키워드로 채움 · 같은 수 → 기본 순서 → 조사표 순서

저장
- records (input_type symptom, 글 = "증상 · 시간대 · N번" + 메모) + record_symptoms 1:1
- 조사표 항목 → 분류 바로 확정 (사용자 분류, AI X) / 직접 입력 → AI 분류 작업 (텍스트 기록과 같음)

주간 (최근 4주): 월요일 시작 한국 시간, 횟수 합 (occurrence_count)
"""
from datetime import datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.repositories import record_repo, symptom_repo
from app.schemas.symptoms import CUSTOM, SymptomIn, SymptomWeeklyQuery
from app.services import classification_service
from app.services.access import ParentAccess, ensure_write
from app.services.dday import KST
from app.services.record_service import check_times


# 칩 글자 (짧게). 순서 = 조사표 순서 (같은 수일 때)
SYMPTOM_LABELS = {
    # 행동변화 14개
    "beh_irregular_sleep": "수면 패턴 변화",
    "beh_hallucination": "환청·환각",
    "beh_wandering": "길을 잃음",
    "beh_verbal_abuse": "폭언·위협",
    "beh_hiding": "물건 감추기",
    "beh_delusion": "의심·망상",
    "beh_sad_crying": "슬퍼하거나 울음",
    "beh_resist_help": "도움 거부",
    "beh_restless": "서성거림·안절부절",
    "beh_going_out": "밖으로 나가려 함",
    "beh_breaking": "물건 파손",
    "beh_meaningless": "목적 없는 행동",
    "beh_improper_dress": "부적절한 옷차림",
    "beh_incontinence_act": "대소변 관련 행동",

    # 인지기능 7개
    "cog_short_memory": "최근 일 잊어버림",
    "cog_date_disorient": "날짜·시간 혼동",
    "cog_place_disorient": "장소 혼동",
    "cog_age_dob_disorient": "나이·생일 혼동",
    "cog_instruction": "지시 이해 어려움",
    "cog_judgment": "상황 판단 어려움",
    "cog_communication": "의사소통 어려움",
    
    # 신체기능 
    "phys_eating": "혼자 식사 어려움",
    "phys_bowel_control": "대변 조절 어려움",
    "phys_bladder_control": "소변 조절 어려움",
    "phys_toilet_use": "화장실 이용 어려움",
    "phys_dressing": "옷 갈아입기 어려움",
    "phys_go_outside_room": "혼자 이동 어려움",

}

# 기록 적을 때 (Figma 키워드)
DEFAULT_SYMPTOMS = [
    "beh_irregular_sleep", "beh_hallucination", "beh_wandering",
    "cog_short_memory", "beh_verbal_abuse", "beh_hiding",
]

TIME_BAND_LABELS = {"dawn": "새벽", "morning": "아침", "afternoon": "오후", "evening": "저녁", "night": "밤"}

CHIP_COUNT = 6
SUGGEST_DAYS = 90
SUGGEST_MIN_RECORDS = 5
WEEKS = 4


def label_of(symptom_type: str, custom_label: str | None = None) -> str:
    return custom_label if symptom_type == CUSTOM else SYMPTOM_LABELS[symptom_type]


def ensure_known(symptom_type: str):
    if symptom_type != CUSTOM and symptom_type not in SYMPTOM_LABELS:
        raise AppError(400, "INVALID_REQUEST", "고를 수 없는 증상이에요.", details={"symptom_type": symptom_type})


# ── 추천 ──

def suggestions(db: Session, access: ParentAccess, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    counts = symptom_repo.item_record_counts(
        db, access.parent_id, list(SYMPTOM_LABELS), now - timedelta(days=SUGGEST_DAYS)
    )
    personal = sum(counts.values()) >= SUGGEST_MIN_RECORDS

    if personal:
        order = list(SYMPTOM_LABELS)
        ranked = sorted(
            (code for code in order if counts.get(code)),
            key=lambda code: (
                -counts[code],
                DEFAULT_SYMPTOMS.index(code) if code in DEFAULT_SYMPTOMS else len(DEFAULT_SYMPTOMS),
                order.index(code),
            ),
        )[:CHIP_COUNT]
        codes = ranked + [c for c in DEFAULT_SYMPTOMS if c not in ranked][:CHIP_COUNT - len(ranked)]
    else:
        codes = DEFAULT_SYMPTOMS

    return {
        "source": "personal" if personal else "default",
        "items": [
            {"symptom_type": c, "label": SYMPTOM_LABELS[c], "record_count": counts.get(c, 0)}
            for c in codes
        ],
    }


# ── 저장 ──

def record_text(body: SymptomIn) -> str:
    """기록함·상세에 보이는 글. 예: 밤에 헤매 · 새벽 · 2번\n새벽 3시에 현관문을 열려고 하심"""
    head = f"{label_of(body.symptom_type, body.custom_label)} · {TIME_BAND_LABELS[body.time_band]} · {body.occurrence_count}번"
    return f"{head}\n{body.note}" if body.note else head


def create(db: Session, access: ParentAccess, body: SymptomIn) -> dict:
    ensure_write(access)
    ensure_known(body.symptom_type)
    recorded_at = datetime.now(timezone.utc)
    check_times(recorded_at, body.occurred_at)

    created = record_repo.insert_record(
        db,
        parent_id=access.parent_id,
        author_id=access.user_id,
        input_type="symptom",
        source="direct",
        text_value=record_text(body),
        recorded_at=recorded_at,
        occurred_at=body.occurred_at,
    )
    record_id = str(created["id"])
    symptom_repo.insert(
        db, record_id, body.symptom_type, body.custom_label,
        body.time_band, body.occurrence_count, body.note,
    )

    if body.symptom_type == CUSTOM:
        classification_service.enqueue_classification(db, record_id, created["text_version"])
    else:
        record_repo.replace_items(db, record_id, [(body.symptom_type, None)], "user")
        record_repo.set_classification(db, record_id, "classified", "user", "completed")

    return {
        "record_id": record_id,
        "parent_id": access.parent_id,
        "symptom_type": body.symptom_type,
        "label": label_of(body.symptom_type, body.custom_label),
        "time_band": body.time_band,
        "occurrence_count": body.occurrence_count,
    }


# ── 최근 4주 ──

def week_start(day) -> datetime:
    """그 날이 속한 주 월요일 0시 (한국 시간)"""
    monday = day - timedelta(days=day.weekday())
    return datetime.combine(monday, time(), KST)


def weekly(db: Session, access: ParentAccess, query: SymptomWeeklyQuery, now: datetime | None = None) -> dict:
    ensure_known(query.symptom_type)
    if (query.symptom_type == CUSTOM) != (query.custom_label is not None):
        raise AppError(400, "INVALID_REQUEST", "직접 입력은 증상 이름이 필요해요 (custom_label).")

    today = (now or datetime.now(timezone.utc)).astimezone(KST).date()
    this_week = week_start(today)
    starts = [this_week - timedelta(weeks=WEEKS - 1 - i) for i in range(WEEKS)]

    rows = symptom_repo.weekly_counts(
        db, access.parent_id, query.symptom_type, query.custom_label, starts[0]
    )
    by_week = {week.date(): int(total) for week, total in rows}

    return {
        "symptom_type": query.symptom_type,
        "label": label_of(query.symptom_type, query.custom_label),
        "weeks": [{"week_start": s.date(), "count": by_week.get(s.date(), 0)} for s in starts],
    }
