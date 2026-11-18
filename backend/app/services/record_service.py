"""기록 작성·조회·수정·재처리 (A-HOME-001~005, A-HOME-009, A-DET-001/002)

- 트랜잭션: 라우터에서 시작, 여기선 그 안에서 실행
- 기록 저장 + 작업 등록 (받아쓰기·분류) → 같은 트랜잭션
- 잠금 순서: records 잠금 → jobs INSERT만 (기존 작업 행 잠금 X → 워커와 교착 없음)
- 기록 없음 / 다른 가족 기록 → 404 (존재 여부 숨김)
- 수정·재처리: 작성자 본인 + admin·writer
"""
from datetime import datetime, time, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.ai.provider import stt_configured
from app.core.config import settings
from app.core.errors import AppError, service_unavailable
from app.db import storage
from app.repositories import record_repo, survey_repo, symptom_repo, upload_repo
from app.repositories.record_repo import RecordFilter
from app.schemas.records import (
    IMMUTABLE_FIELDS,
    TEXT_MAX_LENGTH,
    VOICE_TEXT_MAX_LENGTH,
    RecordListQuery,
    RecordUpdateIn,
    ReplaceAudioIn,
    ReplaceTextIn,
    TextRecordIn,
    VoiceRecordIn,
)
from app.services import (
    audio_upload_service,
    classification_service,
    pagination,
    transcription_service,
)
from app.services.access import ParentAccess, ensure_write, get_parent_access
from app.services.dday import KST
from app.services.patch_rules import check_patch


# 기기 시계 오차 허용
CLOCK_SKEW = timedelta(minutes=5)

PLAYBACK_URL_EXPIRES_SECONDS = 5 * 60

# 수정 칸 → 이력 changed_fields 이름
VERSION_FIELDS = {"current_text": "text", "source": "source", "occurred_at": "occurred_at"}


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


def stage_of(record) -> str:
    if record["input_type"] == "voice" and record["original_text"] is None:
        return "transcription"
    if record["processing_status"] != "completed":
        return "classification"
    return "done"


def to_list_item(record, user_id: str) -> dict:
    return {
        "id": str(record["id"]),
        "parent_id": str(record["parent_id"]),
        "author_id": str(record["author_id"]),
        "author_name": record["author_name"],
        "is_mine": str(record["author_id"]) == user_id,
        "input_type": record["input_type"],
        "source": record["source"],
        "status": record["status"],
        "processing_status": record["processing_status"],
        "stage": stage_of(record),
        "processing_error": record["processing_error"],
        "classification_status": record["classification_status"],
        "current_text": record["current_text"],
        "transcript_empty": record["transcript_empty"],
        "is_edited": record["is_edited"],
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
        "edit_version": record_repo.edit_version(db, record["id"]),
        "symptom": symptom_of(db, record),
        "audio_duration_seconds": record["audio_duration_seconds"],
        # 음성 기록인데 false → 작성자 탈퇴로 음성 삭제 (글은 유지)
        "audio_available": record["audio_path"] is not None and record["audio_deleted_at"] is None,
        "items": [dict(i) for i in record_repo.get_items(db, record["id"])],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
    }


def symptom_of(db: Session, record) -> dict | None:
    if record["input_type"] != "symptom":
        return None
    row = symptom_repo.get(db, record["id"])
    if row is None:
        return None
    from app.services.symptom_service import label_of  # 순환 import 방지
    return {**row, "label": label_of(row["symptom_type"], row["custom_label"])}


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


def create_voice(db: Session, access: ParentAccess, body: VoiceRecordIn) -> dict:
    """업로드 확인 → 기록 저장 (원문 NULL) → 업로드 사용 완료 → 받아쓰기 작업 (한 트랜잭션)"""
    check_times(body.recorded_at, body.occurred_at)

    upload = audio_upload_service.take_upload(db, access, str(body.upload_id))

    created = record_repo.insert_record(
        db,
        parent_id=access.parent_id,
        author_id=access.user_id,
        input_type="voice",
        source=body.source,
        text_value=None,
        recorded_at=body.recorded_at,
        occurred_at=body.occurred_at,
        audio_path=upload["audio_path"],
        audio_duration_seconds=body.duration_seconds
    )
    upload_repo.consume(db, str(upload["id"]), str(created["id"]))
    transcription_service.enqueue_transcription(db, created["id"])

    record = record_repo.get_record(db, created["id"])
    return to_detail(db, record, access.user_id)


# ── 조회 ──

def to_filter(query: RecordListQuery) -> RecordFilter:
    if query.date_from and query.date_to and query.date_from > query.date_to:
        raise AppError(400, "INVALID_REQUEST", "시작 날짜가 끝 날짜보다 늦어요.")

    return RecordFilter(
        status=None if query.status == "all" else query.status,
        area=query.area,
        author_id=str(query.author_id) if query.author_id else None,
        recorded_from=(
            datetime.combine(query.date_from, time(), KST) if query.date_from else None
        ),
        recorded_before=(
            datetime.combine(query.date_to + timedelta(days=1), time(), KST)
            if query.date_to else None
        ),
        source=query.source,
        input_type=query.input_type,
        processing_status=query.processing_status,
        classification_status=query.classification_status,
        q=query.q,
    )


def read_cursor(cursor: str, scope: dict) -> tuple[datetime, str]:
    position = pagination.decode_cursor(cursor, scope)
    try:
        recorded_at, record_id = position
        return datetime.fromisoformat(recorded_at), str(UUID(record_id))
    except ValueError:
        raise pagination.invalid_cursor()


def list_records(db: Session, access: ParentAccess, query: RecordListQuery) -> dict:
    """기록함 (A-2). 최신순 keyset, limit + 1건 조회 → 다음 페이지 여부

    커서 범위: 부모님 + 조건 (cursor·limit 제외) → 조건 변경 시 이전 커서 거부
    total: 첫 페이지만
    """
    filters = to_filter(query)
    scope = {
        "parent_id": access.parent_id,
        **query.model_dump(mode="json", exclude={"cursor", "limit"}),
    }
    after = read_cursor(query.cursor, scope) if query.cursor else None

    rows = record_repo.list_records(
        db, access.parent_id, filters, query.limit + 1, after=after
    )
    has_more = len(rows) > query.limit
    rows = rows[:query.limit]

    next_cursor = None
    if has_more:
        last = rows[-1]
        next_cursor = pagination.encode_cursor(
            [last["recorded_at"].isoformat(), str(last["id"])], scope
        )

    return {
        "data": [to_list_item(record, access.user_id) for record in rows],
        "meta": {
            "next_cursor": next_cursor,
            "has_more": has_more,
            "total": (
                None if query.cursor
                else record_repo.count_records(db, access.parent_id, filters)
            ),
        },
    }


def get_detail(db: Session, user_id: str, record_id: str) -> dict:
    access, record = record_access(db, user_id, record_id)
    return to_detail(db, record, access.user_id)


def get_processing(db: Session, user_id: str, record_id: str) -> dict:
    _, record = record_access(db, user_id, record_id)
    return {
        "record_id": str(record["id"]),
        "input_type": record["input_type"],
        "stage": stage_of(record),
        "processing_status": record["processing_status"],
        "processing_error": record["processing_error"],
        "transcript_empty": record["transcript_empty"],
        "classification_status": record["classification_status"],
        "classified_by": record["classified_by"],
        "text_version": record["text_version"],
        "original_text": record["original_text"],
        "current_text": record["current_text"],
        "items": [dict(i) for i in record_repo.get_items(db, record["id"])],
    }


def get_audio_url(db: Session, user_id: str, record_id: str) -> dict:
    """재생용 서명 URL (5분). 같은 가족이면 viewer 포함"""
    _, record = record_access(db, user_id, record_id)
    if record["audio_path"] is None:
        raise AppError(404, "NOT_FOUND", "음성이 없는 기록이에요.")
    if record["audio_deleted_at"] is not None:
        raise AppError(410, "AUDIO_DELETED", "작성자가 탈퇴해 음성 파일이 삭제됐어요.")

    return {
        "url": storage.create_signed_download_url(
            settings.STORAGE_AUDIO_BUCKET, record["audio_path"],
            PLAYBACK_URL_EXPIRES_SECONDS
        ),
        "expires_in_seconds": PLAYBACK_URL_EXPIRES_SECONDS,
    }


# ── 재처리 ──

def reclassify(db: Session, user_id: str, record_id: str) -> dict:
    """실패·완료 기록 다시 처리. 실패한 단계부터

    - 받아쓰기 실패: 파일 문제 → 409 AUDIO_INVALID (새 녹음 안내)
                     STT 미설정 → 지금도 미설정이면 503, 설정됨 → 받아쓰기부터
                     그 외 → 받아쓰기부터
    - 분류 단계: 분류만 (원문·버전 그대로). 사용자 분류 → 409
    - 처리 중 → 409
    """
    access, record = record_access(db, user_id, record_id, for_update=True)
    ensure_author(access, record)

    if record["processing_status"] in ("pending", "processing"):
        raise AppError(409, "ALREADY_PROCESSING", "처리하고 있어요.")

    if stage_of(record) == "transcription":
        return retry_transcription(db, user_id, record)

    if record["classified_by"] == "user":
        raise AppError(
            409, "USER_CLASSIFIED", "직접 고친 분류가 있어 다시 분류하지 않아요."
        )

    # 분석 중 → 이전 분류 표시 X (분류 상태 NULL + 항목 없음, DB 검사)
    record_repo.replace_items(db, record_id, [], "ai")
    record_repo.set_classification(db, record_id, None, None, "pending")
    classification_service.enqueue_classification(
        db, record_id, record["text_version"]
    )
    return get_processing(db, user_id, record_id)


def retry_transcription(db: Session, user_id: str, record) -> dict:
    record_id = str(record["id"])
    error = record["processing_error"]

    if error in transcription_service.AUDIO_PROBLEMS:
        raise AppError(
            409, "AUDIO_INVALID",
            "녹음 파일에 문제가 있어요. 다시 녹음하거나 글로 남겨 주세요.",
            details={"reason": error, "action": "re_record"}
        )
    if error == transcription_service.STT_NOT_CONFIGURED and not stt_configured():
        raise service_unavailable("stt")

    record_repo.set_processing_status(db, record_id, "pending")
    transcription_service.enqueue_transcription(db, record_id)
    return get_processing(db, user_id, record_id)


# ── 받아쓰기 실패 → 같은 기록에서 글로 적기 / 다시 녹음 ──

def ensure_transcription_failed(record):
    """음성 + 원문 없음 + failed 만. 그 외 → 409 (이미 처리됨·처리 중 등)"""
    if not (
        record["input_type"] == "voice"
        and record["original_text"] is None
        and record["processing_status"] == "failed"
    ):
        raise AppError(
            409, "NOT_TRANSCRIPTION_FAILED", "받아쓰기에 실패한 기록만 바꿀 수 있어요."
        )


def replace_with_text(db: Session, user_id: str, record_id: str, body: ReplaceTextIn) -> dict:
    """한 트랜잭션: 글 기록으로 전환 (기록 시각·출처 유지) → 이전 음성 해제 → 분류 작업

    이전 음성 파일: 업로드 expired → 정리 작업이 삭제
    """
    access, record = record_access(db, user_id, record_id, for_update=True)
    ensure_author(access, record)
    ensure_transcription_failed(record)

    upload_repo.release_for_record(db, record_id)
    record_repo.replace_with_text(db, record_id, body.text)
    classification_service.enqueue_classification(db, record_id, record["text_version"])

    return to_detail(db, record_repo.get_record(db, record_id), user_id)


def replace_audio(db: Session, user_id: str, record_id: str, body: ReplaceAudioIn) -> dict:
    """한 트랜잭션: 새 업로드 확인 → 이전 음성 해제 → 경로 교체 → 업로드 사용 → 받아쓰기 작업"""
    access, record = record_access(db, user_id, record_id, for_update=True)
    ensure_author(access, record)
    ensure_transcription_failed(record)

    upload = audio_upload_service.take_upload(db, access, str(body.upload_id))

    upload_repo.release_for_record(db, record_id)
    record_repo.replace_audio(db, record_id, upload["audio_path"], body.duration_seconds)
    upload_repo.consume(db, str(upload["id"]), record_id)
    transcription_service.enqueue_transcription(db, record_id)

    return to_detail(db, record_repo.get_record(db, record_id), user_id)


# ── 수정 (A-DET-002) ──

def update(db: Session, user_id: str, record_id: str, body: RecordUpdateIn) -> dict:
    """한 트랜잭션: 수정 이력 저장 → 필드 변경(버전 증가는 트리거) → 분류 처리

    - item_codes 보냄 → 사용자 분류 (52항목만, AI 작업 없음)
    - 글만 변경 + AI 분류 기록 → 이전 분류 삭제 + 새 버전 분류 작업 등록
    - 글만 변경 + 사용자 분류 기록 → 사용자 분류 유지
    - 증상 기록 글 → 증상 수정으로만 (글 = 증상·시간대·횟수에서 만듦)
    - 체크리스트 기록 분류 → 고정 (질문한 항목 = 분류). 같은 값 재전송은 허용
    """
    sent = check_patch(body, IMMUTABLE_FIELDS, nullable={"occurred_at"})
    sent.discard("base_version")
    if not sent:
        raise AppError(400, "INVALID_REQUEST", "바꿀 내용이 없어요.")

    access, record = record_access(db, user_id, record_id, for_update=True)
    ensure_author(access, record)
    ensure_transcribed(record)

    fields = {}

    if "current_text" in sent and body.current_text != record["current_text"]:
        if record["input_type"] == "symptom":
            raise AppError(
                409, "USE_SYMPTOM_EDIT", "증상 기록은 증상 고치기에서 바꿀 수 있어요."
            )
        check_text_length(record, body.current_text)
        fields["current_text"] = body.current_text

    if "source" in sent and body.source != record["source"]:
        fields["source"] = body.source

    if "occurred_at" in sent and body.occurred_at != record["occurred_at"]:
        if body.occurred_at is not None:
            check_times(record["recorded_at"], body.occurred_at)
        fields["occurred_at"] = body.occurred_at

    new_codes = None
    if "item_codes" in sent:
        if record["input_type"] == "checklist" and set(body.item_codes) != {
            i["item_code"] for i in record_repo.get_items(db, record_id)
        }:
            raise AppError(
                409, "CHECKLIST_ITEM_FIXED", "체크리스트 기록은 질문한 항목으로 분류돼요."
            )
        unknown = set(body.item_codes) - survey_repo.existing_codes(db, body.item_codes)
        if unknown:
            raise AppError(
                400, "INVALID_REQUEST", "조사표 항목에서만 고를 수 있어요.",
                details={"unknown_codes": sorted(unknown)}
            )
        new_codes = body.item_codes

    save_edit(db, record, user_id, body.base_version, fields, new_codes)
    return to_detail(db, record_repo.get_record(db, record_id), user_id)


def ensure_base_version(db: Session, record_id: str, base_version: int):
    """동시 수정: 화면에서 본 순번 ≠ 현재 순번 → 409 (다른 기기에서 먼저 저장)"""
    current = record_repo.edit_version(db, record_id)
    if base_version != current:
        raise AppError(
            409, "EDIT_CONFLICT", "다른 곳에서 먼저 고쳤어요. 최신 내용을 불러올게요.",
            details={"edit_version": current}
        )


def save_edit(
    db: Session,
    record,
    user_id: str,
    base_version: int,
    fields: dict,
    new_codes: list[str] | None,
):
    """실제 바뀐 칸만 저장 (기록 행 잠금 안). 바뀐 것 없음 → 이력·순번 그대로

    fields: current_text / source / occurred_at 중 값이 달라진 것
    new_codes: 보낸 분류 (None → 안 보냄)
    - AI 분류 그대로 확정 → 분류 주체만 user, 이력 X (순번 그대로, 충돌 검사 X)
    """
    record_id = str(record["id"])
    old_codes = [i["item_code"] for i in record_repo.get_items(db, record_id)]

    codes_changed = new_codes is not None and (
        set(new_codes) != set(old_codes) or record["classification_status"] is None
    )
    confirm_only = (
        new_codes is not None and not codes_changed and record["classified_by"] != "user"
    )

    changed = [VERSION_FIELDS[f] for f in fields]
    if codes_changed:
        changed.append("item_codes")

    if not changed and not confirm_only:
        return

    if changed:
        ensure_base_version(db, record_id, base_version)
        # 이력: 수정 전 상태 + 실제로 바뀐 칸 (기록 행 잠금 안에서 순번 결정)
        record_repo.insert_version(
            db, record_id,
            text_value=record["current_text"],
            edited_by=user_id,
            source=record["source"],
            item_codes=old_codes,
            occurred_at=record["occurred_at"],
            classified_by=record["classified_by"],
            changed_fields=changed
        )

    text_version = record["text_version"]
    if fields:
        text_version = record_repo.update_fields(db, record_id, fields)

    if codes_changed or confirm_only:
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


def ensure_transcribed(record):
    """받아쓰기 전 음성 기록 → 수정 불가 (수정 이력에 남길 글 없음)"""
    if stage_of(record) != "transcription":
        return
    if record["processing_status"] == "failed":
        raise AppError(
            409, "TRANSCRIPTION_FAILED",
            "받아쓰기에 실패한 기록은 고칠 수 없어요. 다시 처리하거나 새로 녹음해 주세요."
        )
    raise AppError(409, "ALREADY_PROCESSING", "받아쓰기가 끝난 뒤 고칠 수 있어요.")


def check_text_length(record, value: str):
    limit = VOICE_TEXT_MAX_LENGTH if record["input_type"] == "voice" else TEXT_MAX_LENGTH
    if len(value) > limit:
        raise AppError(
            422, "VALIDATION_ERROR", f"{limit}자까지 쓸 수 있어요.",
            details={"fields": ["current_text"], "max_length": limit}
        )


# ── 기록지에서 제외 (A-DET-003) ──

def set_status(db: Session, user_id: str, record_id: str, status: str) -> dict:
    """normal ↔ excluded. 작성자만, 같은 상태 → 변경 없이 200. 삭제·수정 이력 아님"""
    access, record = record_access(db, user_id, record_id, for_update=True)
    ensure_author(access, record)

    if record["status"] != status:
        record_repo.set_status(db, record_id, status)
        record = record_repo.get_record(db, record_id)

    return to_detail(db, record, user_id)


# ── 수정 이력 ──

def get_versions(db: Session, user_id: str, record_id: str) -> dict:
    """최신 수정 먼저 (version DESC). changed: 저장 시점 기록값"""
    _, record = record_access(db, user_id, record_id)
    items = record_repo.get_items(db, record_id)

    return {
        "edit_version": record_repo.edit_version(db, record_id),
        "original_text": record["original_text"],
        "current": {
            "text": record["current_text"],
            "source": record["source"],
            "occurred_at": record["occurred_at"],
            "item_codes": [i["item_code"] for i in items],
            "classified_by": record["classified_by"],
        },
        "history": [
            {
                "version": v["version"],
                "edited_by": str(v["edited_by"]),
                "edited_by_name": v["edited_by_name"],
                "is_mine": str(v["edited_by"]) == user_id,
                "edited_at": v["edited_at"],
                "changed": list(v["changed_fields"]),
                "before": {
                    "text": v["text"],
                    "source": v["source_snapshot"],
                    "occurred_at": v["occurred_at_snapshot"],
                    "item_codes": list(v["item_codes_snapshot"] or []),
                    "classified_by": v["classified_by_snapshot"],
                },
            }
            for v in record_repo.list_versions(db, record_id)
        ],
    }
