"""음성 받아쓰기 결과 반영 (워커 transcribe_record에서 사용)

- 원문 있음 → StaleTranscription (중복 실행·회수된 작업, 결과 버림)
- 받아쓴 글 있음 → 원문 = 현재 글 저장 + 분류 작업 등록 (같은 트랜잭션)
- 빈 글 (말소리 없음) → 원문 '', transcript_empty, completed + unclassified, 분류 작업 없음
- 트랜잭션: 호출하는 쪽(작업 함수)에서 시작
"""
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.repositories import record_repo, upload_repo
from app.services import classification_service
from app.workers.queue import enqueue


TRANSCRIBE_JOB = "transcribe_record"

# processing_error 코드
STT_FAILED = "STT_FAILED"
STT_NOT_CONFIGURED = "STT_NOT_CONFIGURED"
AUDIO_PROBLEMS = {
    "AUDIO_MISSING",
    "AUDIO_UNREADABLE",
    "AUDIO_FORMAT_MISMATCH",
    "AUDIO_DURATION_OUT_OF_RANGE",
}


class StaleTranscription(Exception):
    """이미 받아쓴 기록 → 결과 저장 금지"""


@dataclass(frozen=True)
class Target:
    record_id: str
    audio_path: str
    content_type: str


def enqueue_transcription(db: Session, record_id: str) -> str:
    """기록당 활성 받아쓰기 작업 1개 (부분 UNIQUE). 중복 → 409"""
    try:
        with db.begin_nested():
            return enqueue(
                db, TRANSCRIBE_JOB, {"record_id": str(record_id)},
                target_type="record", target_id=str(record_id)
            )
    except IntegrityError:
        raise AppError(409, "ALREADY_PROCESSING", "받아쓰고 있어요.")


def start(db: Session, record_id: str) -> Target | None:
    """processing 표시 + 받아쓸 파일. 기록 없음 → None"""
    record = record_repo.get_record(db, record_id, for_update=True)
    if record is None:
        return None
    if record["original_text"] is not None:
        raise StaleTranscription("이미 받아쓴 기록")

    record_repo.set_processing_status(db, record_id, "processing")
    upload = upload_repo.get_by_record(db, record_id)

    return Target(
        record_id=str(record_id),
        audio_path=record["audio_path"],
        content_type=upload["content_type"] if upload else "audio/mp4"
    )


def save(db: Session, record_id: str, transcript: str, duration_seconds: int):
    record = record_repo.get_record(db, record_id, for_update=True)
    if record is None:
        return
    if record["original_text"] is not None:
        raise StaleTranscription("이미 받아쓴 기록")

    text = transcript.strip()

    if text:
        record_repo.save_transcript(db, record_id, text, duration_seconds, "pending")
        classification_service.enqueue_classification(
            db, record_id, record["text_version"]
        )
    else:
        record_repo.save_transcript(db, record_id, "", duration_seconds, "completed")
        record_repo.set_classification(db, record_id, "unclassified", "ai", "completed")


def mark_failed(db: Session, record_id: str, code: str):
    """받아쓰기 전 기록만 failed. 이미 받아쓴 기록 → 지난 실패, 변경 없음"""
    record = record_repo.get_record(db, record_id, for_update=True)
    if record is None or record["original_text"] is not None:
        return

    record_repo.set_processing_status(db, record_id, "failed", code)
