"""기록 AI 작업

잠금 순서 (모든 트랜잭션): hold_lease (jobs) → 기록 잠금 (records)

transcribe_record: payload {record_id}
1. 트랜잭션 A: lease → 원문 없음 확인 + processing
2. 트랜잭션 밖: 다운로드 → 형식·길이 확인 → STT
3. 트랜잭션 B: lease → 원문 없음 재확인 → 원문 저장 + 분류 작업 등록

classify_record: payload {record_id, text_version}
1. 트랜잭션 A: lease → 버전 확인 + processing
2. AI 호출 (트랜잭션 밖, DB 연결 점유 X)
3. 트랜잭션 B: lease → 버전 재확인 → 저장
"""
from app.ai.interfaces import SpeechToTextNotConfigured
from app.ai.provider import get_record_classifier, get_speech_to_text
from app.core.config import settings
from app.db import storage
from app.services import audio_probe, classification_service, transcription_service
from app.services.classification_service import StaleClassification
from app.services.transcription_service import StaleTranscription
from app.workers.tasks import Job, JobSuperseded, PermanentJobError, hold_lease, task


# ── 받아쓰기 ──

def mark_transcribe_failed(db, job: Job, code: str | None):
    transcription_service.mark_failed(
        db, job.payload["record_id"], code or transcription_service.STT_FAILED
    )


@task(transcription_service.TRANSCRIBE_JOB, on_failure=mark_transcribe_failed)
def transcribe_record(db, job: Job):
    record_id = job.payload["record_id"]

    try:
        with db.begin():
            hold_lease(db, job)
            target = transcription_service.start(db, record_id)

        if target is None:
            return

        audio = storage.download_object(settings.STORAGE_AUDIO_BUCKET, target.audio_path)
        if audio is None:
            raise PermanentJobError("AUDIO_MISSING", "Storage에 파일 없음")

        try:
            info = audio_probe.probe(audio, target.content_type)
        except audio_probe.AudioProblem as e:
            raise PermanentJobError(e.code, str(e)) from e

        try:
            transcript = get_speech_to_text().transcribe(audio, info.mime)
        except SpeechToTextNotConfigured as e:
            raise PermanentJobError(transcription_service.STT_NOT_CONFIGURED, str(e)) from e

        with db.begin():
            hold_lease(db, job)
            transcription_service.save(
                db, record_id, transcript.text, info.duration_seconds
            )

    except StaleTranscription as e:
        raise JobSuperseded(str(e)) from e


# ── 분류 ──

def mark_classify_failed(db, job: Job, code: str | None):
    classification_service.mark_failed(
        db, job.payload["record_id"], job.payload["text_version"],
        code or classification_service.CLASSIFY_FAILED
    )


@task(classification_service.CLASSIFY_JOB, on_failure=mark_classify_failed)
def classify_record(db, job: Job):
    record_id = job.payload["record_id"]
    text_version = job.payload["text_version"]

    try:
        with db.begin():
            hold_lease(db, job)
            text = classification_service.start(db, record_id, text_version)

        if text is None:
            return

        results = get_record_classifier().classify(text) if text else []

        with db.begin():
            hold_lease(db, job)
            classification_service.save_result(db, record_id, text_version, results)

    except StaleClassification as e:
        raise JobSuperseded(str(e)) from e
