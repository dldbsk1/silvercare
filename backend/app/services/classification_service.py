"""AI 분류 결과 반영 (워커 classify_record에서 사용)

- 작업 payload의 text_version ≠ 현재 text_version → StaleClassification (결과 버림)
- classified_by = user → StaleClassification (사용자 분류 우선, AI 손대지 않음)
- 저장 전 걸러내기: 52항목 코드만, confidence 0~1, MIN_CONFIDENCE 이상, 중복 제거
- 결과 0건 → unclassified (미분류)
- 트랜잭션: 호출하는 쪽(작업 함수)에서 시작
"""
from sqlalchemy.orm import Session

from app.ai.interfaces import ItemClassification
from app.repositories import record_repo, survey_repo
from app.workers.queue import enqueue


# AI 팀원과 조정 예정
MIN_CONFIDENCE = 0.5

CLASSIFY_JOB = "classify_record"


class StaleClassification(Exception):
    """이 작업의 결과를 저장하면 안 됨 (글 변경 / 사용자 분류)"""


def enqueue_classification(db: Session, record_id: str, text_version: int) -> str:
    return enqueue(
        db, CLASSIFY_JOB,
        {"record_id": str(record_id), "text_version": text_version},
        target_type="record", target_id=str(record_id)
    )


def ensure_current(record, text_version: int):
    if record["text_version"] != text_version:
        raise StaleClassification(
            f"text_version {text_version} → {record['text_version']}"
        )
    if record["classified_by"] == "user":
        raise StaleClassification("사용자 분류 우선")


def start(db: Session, record_id: str, text_version: int) -> str | None:
    """processing 표시 + 분류할 글 반환. 기록 없음 → None"""
    record = record_repo.get_record(db, record_id, for_update=True)
    if record is None:
        return None

    ensure_current(record, text_version)
    record_repo.set_processing_status(db, record_id, "processing")
    return record["current_text"] or ""


def filter_results(
    db: Session,
    results: list[ItemClassification]
) -> list[tuple[str, float]]:
    valid = survey_repo.existing_codes(db, [r.item_code for r in results])
    best: dict[str, float] = {}

    for result in results:
        if result.item_code not in valid:
            continue
        if not 0 <= result.confidence <= 1 or result.confidence < MIN_CONFIDENCE:
            continue
        best[result.item_code] = max(best.get(result.item_code, 0), result.confidence)

    return sorted(best.items())


def save_result(
    db: Session,
    record_id: str,
    text_version: int,
    results: list[ItemClassification]
):
    """records 행 잠금 → 버전 비교 → 같을 때만 저장. 중복 실행 → 같은 결과"""
    record = record_repo.get_record(db, record_id, for_update=True)
    if record is None:
        return

    ensure_current(record, text_version)

    items = filter_results(db, results)
    record_repo.replace_items(db, record_id, items, "ai")
    record_repo.set_classification(
        db, record_id,
        "classified" if items else "unclassified",
        "ai",
        "completed"
    )


def mark_failed(db: Session, record_id: str, text_version: int):
    """재시도 소진 → failed. 이전 버전 작업·사용자 분류 기록 → 변경 없음"""
    record = record_repo.get_record(db, record_id, for_update=True)
    if record is None:
        return

    try:
        ensure_current(record, text_version)
    except StaleClassification:
        return

    record_repo.set_processing_status(db, record_id, "failed")
