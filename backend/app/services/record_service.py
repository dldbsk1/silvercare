"""기록 작성·조회·수정·재분류 (A-HOME-002~005, A-HOME-009, A-DET-001/002)

- 트랜잭션: 라우터에서 시작, 여기선 그 안에서 실행
- 기록 저장 + 분류 작업 등록 → 같은 트랜잭션
- 기록 없음 / 다른 가족 기록 → 404 (존재 여부 숨김)
- 수정·재분류: 작성자 본인 + admin·writer
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.repositories import record_repo, survey_repo
from app.schemas.records import IMMUTABLE_FIELDS, RecordUpdateIn, TextRecordIn
from app.services import classification_service
from app.services.access import ParentAccess, ensure_write, get_parent_access


# 기기 시계 오차 허용
CLOCK_SKEW = timedelta(minutes=5)


# ── 공통 ──

def record_access(
    db: Session,
    user_id: str,
    record_id: str,
    for_update: bool = False
) -> tuple[ParentAccess, dict]:
    record = record_repo.get_record(db, record_id, for_update=for_update)
    if record is None:
        raise AppError(404, "NOT_FOUND", "기록을 찾을 수 없어요.")

    access = get_parent_access(db, user_id, str(record["parent_id"]))
    return access, record


def ensure_author(access: ParentAccess, record):
    ensure_write(access)
    if str(record["author_id"]) != access.user_id:
        raise AppError(
            403, "PERMISSION_DENIED", "내가 작성한 기록만 고칠 수 있어요."
        )


def to_list_item(record, user_id: str) -> dict:
    return {
        "id": str(record["id"]),
        "parent_id": str(record["parent_id"]),
        "author_id": str(record["author_id"]),
        "is_mine": str(record["author_id"]) == user_id,
        "input_type": record["input_type"],
        "source": record["source"],
        "status": record["status"],
        "processing_status": record["processing_status"],
        "classification_status": record["classification_status"],
        "current_text": record["current_text"],
        "is_edited": record["text_version"] > 1,
        "areas": list(record["areas"]),
        "recorded_at": record["recorded_at"],
        "occurred_at": record["occurred_at"],
    }


def to_detail(db: Session, record, user_id: str) -> dict:
    return {
        **to_list_item(record, user_id),
        "original_text": record["original_text"],
        "classified_by": record["classified_by"],
        "text_version": record["text_version"],
        "audio_duration_seconds": record["audio_duration_seconds"],
        "items": [dict(i) for i in record_repo.get_items(db, record["id"])],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
    }


def check_times(recorded_at: datetime, occurred_at: datetime | None):
    now = datetime.now(timezone.utc)

    if recorded_at > now + CLOCK_SKEW:
        raise AppError(400, "INVALID_REQUEST", "기록 시각이 현재보다 미래예요.")

    if occurred_at is not None and occurred_at > recorded_at + CLOCK_SKEW:
        raise AppError(
            400, "INVALID_REQUEST", "일어난 시각이 기록 시각보다 미래예요."
        )


# ── 작성 ──

def create_text(db: Session, access: ParentAccess, body: TextRecordIn) -> dict:
    """원문 저장 (original_text = current_text) + 분류 작업 등록"""
    check_times(body.recorded_at or datetime.now(timezone.utc), body.occurred_at)

    created = record_repo.insert_record(
        db,
        parent_id=access.parent_id,
        author_id=access.user_id,
        input_type="text",
        source=body.source,
        text_value=body.text,
        recorded_at=body.recorded_at,
        occurred_at=body.occurred_at
    )
    classification_service.enqueue_classification(
        db, created["id"], created["text_version"]
    )

    record = record_repo.get_record(db, created["id"])
    return to_detail(db, record, access.user_id)


# ── 조회 ──

def list_records(
    db: Session,
    access: ParentAccess,
    status: str | None,
    limit: int
) -> list[dict]:
    return [
        to_list_item(record, access.user_id)
        for record in record_repo.list_records(db, access.parent_id, status, limit)
    ]


def get_detail(db: Session, user_id: str, record_id: str) -> dict:
    access, record = record_access(db, user_id, record_id)
    return to_detail(db, record, access.user_id)


def get_processing(db: Session, user_id: str, record_id: str) -> dict:
    _, record = record_access(db, user_id, record_id)
    return {
        "record_id": str(record["id"]),
        "processing_status": record["processing_status"],
        "classification_status": record["classification_status"],
        "classified_by": record["classified_by"],
        "text_version": record["text_version"],
        "original_text": record["original_text"],
        "current_text": record["current_text"],
        "items": [dict(i) for i in record_repo.get_items(db, record["id"])],
    }


# ── 재분류 ──

def reclassify(db: Session, user_id: str, record_id: str) -> dict:
    """failed·completed → pending + 작업 등록. 분석 중·사용자 분류 → 409"""
    access, record = record_access(db, user_id, record_id, for_update=True)
    ensure_author(access, record)

    if record["processing_status"] in ("pending", "processing"):
        raise AppError(409, "ALREADY_PROCESSING", "분류하고 있어요.")
    if record["classified_by"] == "user":
        raise AppError(
            409, "USER_CLASSIFIED", "직접 고친 분류가 있어 다시 분류하지 않아요."
        )

    record_repo.set_processing_status(db, record_id, "pending")
    classification_service.enqueue_classification(
        db, record_id, record["text_version"]
    )
    return get_processing(db, user_id, record_id)


# ── 수정 (A-DET-002) ──

def update(db: Session, user_id: str, record_id: str, body: RecordUpdateIn) -> dict:
    """한 트랜잭션: 수정 이력 저장 → 필드 변경(버전 증가는 트리거) → 분류 처리

    - item_codes 보냄 → 사용자 분류 (52항목만, AI 작업 없음)
    - 글만 변경 + AI 분류 기록 → 이전 분류 삭제 + 새 버전 분류 작업 등록
    - 글만 변경 + 사용자 분류 기록 → 사용자 분류 유지
    """
    check_update_fields(body)

    access, record = record_access(db, user_id, record_id, for_update=True)
    ensure_author(access, record)

    sent = body.model_fields_set
    fields = {}

    if "current_text" in sent and body.current_text != record["current_text"]:
        if record["current_text"] is None:
            raise AppError(409, "ALREADY_PROCESSING", "받아쓰기가 끝난 뒤 고칠 수 있어요.")
        fields["current_text"] = body.current_text

    if "source" in sent and body.source != record["source"]:
        fields["source"] = body.source

    if "occurred_at" in sent and body.occurred_at != record["occurred_at"]:
        if body.occurred_at is not None:
            check_times(record["recorded_at"], body.occurred_at)
        fields["occurred_at"] = body.occurred_at

    old_codes = [i["item_code"] for i in record_repo.get_items(db, record_id)]
    new_codes = None

    if "item_codes" in sent:
        unknown = set(body.item_codes) - survey_repo.existing_codes(db, body.item_codes)
        if unknown:
            raise AppError(
                400, "INVALID_REQUEST", "조사표 항목에서만 고를 수 있어요.",
                details={"unknown_codes": sorted(unknown)}
            )
        if set(body.item_codes) != set(old_codes) or record["classified_by"] != "user":
            new_codes = body.item_codes

    if not fields and new_codes is None:
        return to_detail(db, record, user_id)

    record_repo.insert_version(
        db, record_id,
        text_value=record["current_text"],
        edited_by=user_id,
        source=record["source"],
        item_codes=old_codes,
        occurred_at=record["occurred_at"]
    )

    text_version = record["text_version"]
    if fields:
        text_version = record_repo.update_fields(db, record_id, fields)

    if new_codes is not None:
        record_repo.replace_items(db, record_id, [(c, None) for c in new_codes], "user")
        record_repo.set_classification(
            db, record_id,
            "classified" if new_codes else "unclassified",
            "user",
            "completed"
        )
    elif "current_text" in fields and record["classified_by"] != "user":
        # 최신 버전 분류 완료 전 → 이전 분류 표시 금지
        record_repo.replace_items(db, record_id, [], "ai")
        record_repo.set_classification(db, record_id, None, None, "pending")
        classification_service.enqueue_classification(db, record_id, text_version)

    return to_detail(db, record_repo.get_record(db, record_id), user_id)


def check_update_fields(body: RecordUpdateIn):
    extra = set(body.model_extra or {})

    immutable = extra & IMMUTABLE_FIELDS
    if immutable:
        raise AppError(
            400, "IMMUTABLE_FIELD", "바꿀 수 없는 항목이 있어요.",
            details={"fields": sorted(immutable)}
        )
    if extra:
        raise AppError(
            422, "VALIDATION_ERROR", "알 수 없는 항목이 있어요.",
            details={"fields": sorted(extra)}
        )

    sent = body.model_fields_set
    if not sent:
        raise AppError(400, "INVALID_REQUEST", "바꿀 내용이 없어요.")

    nullable = {"occurred_at"}
    for field in sent - nullable:
        if getattr(body, field) is None:
            raise AppError(
                422, "VALIDATION_ERROR", "비울 수 없는 항목이에요.",
                details={"fields": [field]}
            )
