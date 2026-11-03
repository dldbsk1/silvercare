"""2단계 음성 기록 (A-HOME-001, A-DET-001 재생)

Storage는 가짜 (메모리). 실제 Storage 흐름: test_voice_storage.py (-m storage)
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.ai.interfaces import Transcript
from app.ai.mock import MOCK_TRANSCRIPT
from app.ai.stub import StubSpeechToText
from app.db import storage
from app.db.session import engine
from app.services import record_service, transcription_service, upload_cleanup_service
from app.workers import worker
from app.workers.tasks import TASKS
from app.workers.tasks import records as record_tasks
from tests.audio_samples import make_wav
from tests.integration.conftest import (
    claim_job,
    fail_final,
    join_family,
    run_sql,
    sql_scalar,
)


TRANSCRIBE = "transcribe_record"
CLASSIFY = "classify_record"


class FakeStorage:
    def __init__(self):
        self.files: dict[str, tuple[bytes, str]] = {}
        self.removed: list[str] = []
        self.fail_remove = False

    def put(self, path, data, content_type="audio/mp4"):
        self.files[path] = (data, content_type)

    def sign_upload(self, bucket, path):
        return {"signed_url": f"https://storage.test/{path}", "token": "t", "path": path}

    def info(self, bucket, path):
        if path not in self.files:
            return None
        data, content_type = self.files[path]
        return {"size": len(data), "content_type": content_type}

    def download(self, bucket, path):
        return self.files[path][0] if path in self.files else None

    def remove(self, bucket, paths):
        if self.fail_remove:
            raise RuntimeError("Storage down")
        for path in paths:
            self.files.pop(path, None)
            self.removed.append(path)


@pytest.fixture
def fake_storage(monkeypatch):
    fake = FakeStorage()
    monkeypatch.setattr(storage, "create_signed_upload_url", fake.sign_upload)
    monkeypatch.setattr(storage, "object_info", fake.info)
    monkeypatch.setattr(storage, "download_object", fake.download)
    monkeypatch.setattr(storage, "remove_objects", fake.remove)
    monkeypatch.setattr(
        storage, "create_signed_download_url",
        lambda bucket, path, expires: f"https://storage.test/play/{path}?e={expires}"
    )
    return fake


def now_iso(minutes=0):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def issue(client, parent_id, content_type="audio/mp4"):
    response = client.post(
        f"/v1/parents/{parent_id}/records/audio/upload-url",
        json={"content_type": content_type}
    )
    assert response.status_code == 201
    return response.json()["data"]


def create(client, upload_id, parent_id, headers=None, **extra):
    body = {
        "upload_id": upload_id, "duration_seconds": 3,
        "recorded_at": now_iso(), **extra
    }
    return client.post(
        f"/v1/parents/{parent_id}/records/audio", json=body, headers=headers or {}
    )


def uploaded(client, fake, parent_id, data=None, content_type="audio/wav"):
    upload = issue(client, parent_id, content_type)
    fake.put(upload["audio_path"], data if data is not None else make_wav(3), content_type)
    return upload


def new_voice_record(client, fake, parent_id, data=None):
    upload = uploaded(client, fake, parent_id, data)
    response = create(client, upload["upload_id"], parent_id)
    assert response.status_code == 202, response.text
    return response.json()["data"]["id"]


def run_transcribe(db, record_id):
    worker.run_job(db, claim_job(db, record_id, TRANSCRIBE))


def processing(client, record_id):
    return client.get(f"/v1/records/{record_id}/processing").json()["data"]


def job_rows(db, record_id):
    return run_sql(
        db,
        """
            SELECT type, status FROM jobs
            WHERE target_type = 'record' AND target_id = :id
            ORDER BY type DESC, status
        """,
        id=record_id
    )


def use_stt(monkeypatch, stt):
    monkeypatch.setattr(record_tasks, "get_speech_to_text", lambda: stt)


class FixedStt:
    def __init__(self, text_value):
        self.text_value = text_value

    def transcribe(self, audio, content_type):
        return Transcript(text=self.text_value)


class BrokenStt:
    def transcribe(self, audio, content_type):
        raise TimeoutError("STT timeout")


# ── 생성 ──

def test_create_voice_record(client, db, parent_id, fake_storage):
    upload = uploaded(client, fake_storage, parent_id)

    response = create(client, upload["upload_id"], parent_id, source="call")

    assert response.status_code == 202
    data = response.json()["data"]
    assert data["input_type"] == "voice" and data["source"] == "call"
    assert data["original_text"] is None and data["current_text"] is None
    assert data["text_version"] == 1 and data["transcript_empty"] is False
    assert data["processing_status"] == "pending" and data["stage"] == "transcription"
    assert data["audio_duration_seconds"] == 3

    row = run_sql(
        db, "SELECT status, record_id FROM audio_uploads WHERE id = :id",
        id=upload["upload_id"]
    )[0]
    assert row.status == "consumed" and str(row.record_id) == data["id"]
    assert [tuple(j) for j in job_rows(db, data["id"])] == [(TRANSCRIBE, "queued")]


def test_upload_ownership(client, db, consent_docs, parent_id, fake_storage):
    upload = uploaded(client, fake_storage, parent_id)
    other_parent = client.post("/v1/parents", json={
        "nickname": "아빠", "age_band": "70s", "apply_stage": "before", "cohabiting": False
    }).json()["data"]["id"]

    # 다른 부모님 / 없는 업로드
    assert create(client, upload["upload_id"], other_parent).status_code == 404
    missing = "00000000-0000-0000-0000-000000000000"
    assert create(client, missing, parent_id).status_code == 404

    # 같은 가족 다른 사용자 (writer) → 남의 업로드 404
    join_family(db, client, consent_docs, parent_id, "writer")
    response = create(client, upload["upload_id"], parent_id)
    assert response.status_code == 404


def test_upload_not_finished(client, parent_id, fake_storage):
    upload = issue(client, parent_id)

    response = create(client, upload["upload_id"], parent_id)

    assert response.status_code == 400
    assert response.json()["error"]["details"]["reason"] == "upload_incomplete"


def test_storage_metadata_checks(client, parent_id, fake_storage):
    upload = issue(client, parent_id)
    fake_storage.put(upload["audio_path"], b"x" * (10 * 1024 * 1024 + 1))
    assert create(client, upload["upload_id"], parent_id).status_code == 413

    upload = issue(client, parent_id)
    fake_storage.put(upload["audio_path"], make_wav(3), "video/mp4")
    response = create(client, upload["upload_id"], parent_id)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_FILE_TYPE"


def test_already_used_and_idempotent_retry(client, db, parent_id, fake_storage):
    upload = uploaded(client, fake_storage, parent_id)
    body_time = now_iso()
    headers = {"Idempotency-Key": "voice-1"}

    first = create(client, upload["upload_id"], parent_id, headers, recorded_at=body_time)
    again = create(client, upload["upload_id"], parent_id, headers, recorded_at=body_time)
    assert first.status_code == again.status_code == 202
    assert first.json() == again.json()

    # 키 없이 / 다른 키 → 409 + 기존 기록
    response = create(client, upload["upload_id"], parent_id, {"Idempotency-Key": "voice-2"})
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "AUDIO_ALREADY_USED"
    assert error["details"]["record_id"] == first.json()["data"]["id"]

    assert sql_scalar(
        db, "SELECT count(*) FROM records WHERE parent_id = :p", p=parent_id
    ) == 1


def test_expired_upload(client, db, parent_id, fake_storage):
    upload = uploaded(client, fake_storage, parent_id)
    run_sql(db, "UPDATE audio_uploads SET status = 'expired' WHERE id = :id", id=upload["upload_id"])

    response = create(client, upload["upload_id"], parent_id)

    assert response.status_code == 410
    assert response.json()["error"]["code"] == "UPLOAD_EXPIRED"


@pytest.mark.parametrize("extra, status", [
    ({"duration_seconds": 1}, 422),
    ({"duration_seconds": 181}, 422),
    ({"duration_seconds": 2}, 202),
    ({"duration_seconds": 180}, 202),
    ({"source": "kakao"}, 422),
    ({"recorded_at": "2026-11-03T10:00:00"}, 422),
    ({"recorded_at": None}, 422),
])
def test_validation(client, parent_id, fake_storage, extra, status):
    upload = uploaded(client, fake_storage, parent_id)

    assert create(client, upload["upload_id"], parent_id, **extra).status_code == status


def test_future_time(client, parent_id, fake_storage):
    upload = uploaded(client, fake_storage, parent_id)

    assert create(client, upload["upload_id"], parent_id, recorded_at=now_iso(10)).status_code == 400


def test_viewer_cannot_record(client, db, consent_docs, parent_id, fake_storage):
    join_family(db, client, consent_docs, parent_id, "viewer")

    response = client.post(f"/v1/parents/{parent_id}/records/audio/upload-url", json={})

    assert response.status_code == 403


def test_insert_trigger_forces_voice_defaults(client, db, user_id, parent_id):
    record_id = sql_scalar(
        db,
        """
            INSERT INTO records (
                parent_id, author_id, input_type, source, original_text, current_text,
                text_version, transcript_empty, processing_status, audio_path, audio_duration_seconds
            )
            VALUES (:p, :u, 'voice', 'direct', '조작', '조작', 5, true, 'completed', :path, 3)
            RETURNING id
        """,
        p=parent_id, u=user_id, path=f"{parent_id}/{user_id}/forced.m4a"
    )

    row = run_sql(
        db,
        """
            SELECT original_text, current_text, text_version, transcript_empty,
                   processing_status::text AS processing_status
            FROM records WHERE id = :id
        """,
        id=record_id
    )[0]
    assert tuple(row) == (None, None, 1, False, "pending")


# ── 받아쓰기 ──

def test_transcribe_then_classify(client, db, parent_id, fake_storage):
    record_id = new_voice_record(client, fake_storage, parent_id, make_wav(4.4))

    run_transcribe(db, record_id)

    data = client.get(f"/v1/records/{record_id}").json()["data"]
    assert data["original_text"] == data["current_text"] == MOCK_TRANSCRIPT
    assert data["text_version"] == 1 and data["is_edited"] is False
    assert data["audio_duration_seconds"] == 4
    assert data["stage"] == "classification" and data["processing_status"] == "pending"
    assert [tuple(j) for j in job_rows(db, record_id)] == [
        (TRANSCRIBE, "completed"), (CLASSIFY, "queued")
    ]

    worker.run_job(db, claim_job(db, record_id, CLASSIFY, 1))

    data = processing(client, record_id)
    assert data["stage"] == "done" and data["processing_status"] == "completed"
    assert [i["item_code"] for i in data["items"]] == ["phys_eating"]


def test_duplicate_transcribe_run_is_superseded(client, db, parent_id, fake_storage):
    record_id = new_voice_record(client, fake_storage, parent_id)
    run_transcribe(db, record_id)

    # 같은 작업 회수 후 재실행 → 원문 이미 있음 → superseded, 분류 작업 추가 없음
    run_transcribe(db, record_id)

    assert [tuple(j) for j in job_rows(db, record_id)] == [
        (TRANSCRIBE, "superseded"), (CLASSIFY, "queued")
    ]


def test_silent_recording(client, db, parent_id, fake_storage, monkeypatch):
    use_stt(monkeypatch, FixedStt("   "))
    record_id = new_voice_record(client, fake_storage, parent_id)

    run_transcribe(db, record_id)

    data = processing(client, record_id)
    assert data["original_text"] == data["current_text"] == ""
    assert data["transcript_empty"] is True
    assert data["processing_status"] == "completed" and data["stage"] == "done"
    assert data["classification_status"] == "unclassified"
    assert [tuple(j) for j in job_rows(db, record_id)] == [(TRANSCRIBE, "completed")]

    # 사용자가 글 입력 → 버전 2, 원문 '' 보존
    data = client.patch(f"/v1/records/{record_id}", json={"current_text": "식사 잘 하셨어요"}).json()["data"]
    assert data["original_text"] == "" and data["text_version"] == 2
    assert data["transcript_empty"] is True


@pytest.mark.parametrize("seconds, code", [
    (None, "AUDIO_UNREADABLE"),
    (1.4, "AUDIO_DURATION_OUT_OF_RANGE"),
    (180.5, "AUDIO_DURATION_OUT_OF_RANGE"),
])
def test_file_problem_fails_without_retry(client, db, parent_id, fake_storage, seconds, code):
    data = b"not audio" if seconds is None else make_wav(seconds)
    record_id = new_voice_record(client, fake_storage, parent_id, data)

    run_transcribe(db, record_id)

    result = processing(client, record_id)
    assert result["processing_status"] == "failed" and result["processing_error"] == code
    assert result["stage"] == "transcription"
    assert [tuple(j) for j in job_rows(db, record_id)] == [(TRANSCRIBE, "failed")]

    response = client.post(f"/v1/records/{record_id}/reclassify")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "AUDIO_INVALID"
    assert response.json()["error"]["details"] == {"reason": code, "action": "re_record"}


@pytest.mark.parametrize("seconds, stored", [(1.5, 2), (180.4, 180)])
def test_duration_boundaries_pass(client, db, parent_id, fake_storage, seconds, stored):
    record_id = new_voice_record(client, fake_storage, parent_id, make_wav(seconds))

    run_transcribe(db, record_id)

    assert client.get(f"/v1/records/{record_id}").json()["data"]["audio_duration_seconds"] == stored


def test_file_deleted_after_check(client, db, parent_id, fake_storage):
    record_id = new_voice_record(client, fake_storage, parent_id)
    fake_storage.files.clear()

    run_transcribe(db, record_id)

    assert processing(client, record_id)["processing_error"] == "AUDIO_MISSING"


def test_stt_not_configured(client, db, parent_id, fake_storage, monkeypatch):
    use_stt(monkeypatch, StubSpeechToText())
    record_id = new_voice_record(client, fake_storage, parent_id)

    run_transcribe(db, record_id)

    data = processing(client, record_id)
    assert data["processing_error"] == "STT_NOT_CONFIGURED"
    assert [tuple(j) for j in job_rows(db, record_id)] == [(TRANSCRIBE, "failed")]

    # 여전히 미설정 → 503
    monkeypatch.setattr(record_service, "stt_configured", lambda: False)
    assert client.post(f"/v1/records/{record_id}/reclassify").status_code == 503

    # 설정됨 → 받아쓰기부터 다시
    monkeypatch.setattr(record_service, "stt_configured", lambda: True)
    response = client.post(f"/v1/records/{record_id}/reclassify")
    assert response.status_code == 202
    assert response.json()["data"]["processing_error"] is None
    assert [tuple(j) for j in job_rows(db, record_id)] == [
        (TRANSCRIBE, "failed"), (TRANSCRIBE, "queued")
    ]


def test_stt_error_retries_then_fails(client, db, parent_id, fake_storage, monkeypatch):
    use_stt(monkeypatch, BrokenStt())
    record_id = new_voice_record(client, fake_storage, parent_id)

    run_transcribe(db, record_id)

    # 재시도 예약 (무음 성공으로 저장 X)
    assert [tuple(j) for j in job_rows(db, record_id)] == [(TRANSCRIBE, "queued")]
    data = processing(client, record_id)
    assert data["processing_status"] == "processing" and data["transcript_empty"] is False

    run_sql(db, "UPDATE jobs SET attempts = max_attempts - 1 WHERE target_id = :id", id=record_id)
    run_transcribe(db, record_id)

    data = processing(client, record_id)
    assert data["processing_status"] == "failed" and data["processing_error"] == "STT_FAILED"
    assert data["original_text"] is None

    # 일시 장애 실패 → 받아쓰기부터 다시
    use_stt(monkeypatch, FixedStt("밥 드셨어요"))
    assert client.post(f"/v1/records/{record_id}/reclassify").status_code == 202
    run_transcribe(db, record_id)
    assert processing(client, record_id)["original_text"] == "밥 드셨어요"


def test_classification_failure_keeps_transcript(client, db, parent_id, fake_storage, monkeypatch):
    use_stt(monkeypatch, FixedStt("[ai-fail] 밥"))
    record_id = new_voice_record(client, fake_storage, parent_id)
    run_transcribe(db, record_id)

    run_sql(
        db, "UPDATE jobs SET max_attempts = 1 WHERE target_id = :id AND type = :t",
        id=record_id, t=CLASSIFY
    )
    worker.run_job(db, claim_job(db, record_id, CLASSIFY, 1))

    data = processing(client, record_id)
    assert data["processing_status"] == "failed" and data["processing_error"] == "CLASSIFY_FAILED"
    assert data["stage"] == "classification"
    assert data["original_text"] == data["current_text"] == "[ai-fail] 밥"
    assert data["text_version"] == 1

    # 재처리 → 분류만
    response = client.post(f"/v1/records/{record_id}/reclassify")
    assert response.status_code == 202
    types = [j.type for j in job_rows(db, record_id)]
    assert types.count(TRANSCRIBE) == 1 and types.count(CLASSIFY) == 2


# ── 수정 ──

def test_edit_before_transcription(client, db, parent_id, fake_storage):
    record_id = new_voice_record(client, fake_storage, parent_id)

    for body in ({"current_text": "고침"}, {"source": "call"}, {"item_codes": ["phys_eating"]}):
        response = client.patch(f"/v1/records/{record_id}", json=body)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ALREADY_PROCESSING"

    fail_final(db, claim_job(db, record_id, TRANSCRIBE), "STT_FAILED")
    response = client.patch(f"/v1/records/{record_id}", json={"current_text": "고침"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TRANSCRIPTION_FAILED"


def test_edit_after_transcription_and_length(client, db, parent_id, fake_storage):
    record_id = new_voice_record(client, fake_storage, parent_id)
    run_transcribe(db, record_id)

    long_text = "가" * 1500
    data = client.patch(f"/v1/records/{record_id}", json={"current_text": long_text}).json()["data"]
    assert data["current_text"] == long_text and data["text_version"] == 2
    assert data["original_text"] == MOCK_TRANSCRIPT

    assert client.patch(f"/v1/records/{record_id}", json={"current_text": "가" * 2001}).status_code == 422

    text_record = client.post(f"/v1/parents/{parent_id}/records/text", json={"text": "밥"}).json()["data"]["id"]
    response = client.patch(f"/v1/records/{text_record}", json={"current_text": "가" * 1001})
    assert response.status_code == 422
    assert response.json()["error"]["details"]["max_length"] == 1000


# ── 원문 보호 트리거 ──

def test_original_text_only_by_transcription(client, db, user_id, parent_id, fake_storage):
    record_id = new_voice_record(client, fake_storage, parent_id)

    def update(query, writer=None):
        try:
            if writer:
                db.execute(text("SELECT set_config('app.writer', :w, true)"), {"w": writer})
            db.execute(text(query), {"id": record_id})
            db.commit()
            return True
        except DBAPIError:
            db.rollback()
            return False
        finally:
            run_sql(db, "SELECT set_config('app.writer', '', true)")

    # 워커 표시 없음
    assert not update("UPDATE records SET original_text = 'x', current_text = 'x' WHERE id = :id")
    # 원문 ≠ 현재 글
    assert not update("UPDATE records SET original_text = 'x', current_text = 'y' WHERE id = :id", "transcription")
    # 받아쓰기 전 현재 글만
    assert not update("UPDATE records SET current_text = 'y' WHERE id = :id")
    # 정상 최초 저장
    assert update("UPDATE records SET original_text = 'x', current_text = 'x' WHERE id = :id", "transcription")
    assert sql_scalar(db, "SELECT text_version FROM records WHERE id = :id", id=record_id) == 1
    # 두 번째 저장
    assert not update("UPDATE records SET original_text = 'z', current_text = 'z' WHERE id = :id", "transcription")
    # audio_path 변경
    assert not update("UPDATE records SET audio_path = 'other.m4a' WHERE id = :id")

    text_record = client.post(f"/v1/parents/{parent_id}/records/text", json={"text": "밥"}).json()["data"]["id"]
    record_id = text_record
    # 텍스트 기록에 받아쓰기 규칙 사용 불가
    assert not update("UPDATE records SET original_text = 'x', current_text = 'x' WHERE id = :id", "transcription")


def test_set_config_is_transaction_local():
    with engine.connect() as connection:
        with connection.begin():
            connection.execute(text("SELECT set_config('app.writer', 'transcription', true)"))
        with connection.begin():
            value = connection.execute(text("SELECT current_setting('app.writer', true)")).scalar()

    assert value in (None, "")


# ── 작업 소유권 (lease) ──

def test_reclaimed_job_old_worker_changes_nothing(client, db, parent_id, fake_storage, monkeypatch):
    record_id = new_voice_record(client, fake_storage, parent_id)
    old = claim_job(db, record_id, TRANSCRIBE)

    class ReclaimDuringStt:
        def transcribe(self, audio, content_type):
            # STT 도중 멈춤 → 다른 워커가 회수
            claim_job(db, record_id, TRANSCRIBE)
            return Transcript(text="오래된 결과")

    use_stt(monkeypatch, ReclaimDuringStt())
    worker.run_job(db, old)

    # 이전 워커: 결과 저장·완료 기록 없음
    assert processing(client, record_id)["original_text"] is None
    assert [tuple(j) for j in job_rows(db, record_id)] == [(TRANSCRIBE, "running")]

    # 이전 워커의 실패 처리 → on_failure 미실행
    fail_final(db, old, "AUDIO_MISSING")
    assert processing(client, record_id)["processing_status"] == "processing"
    assert [tuple(j) for j in job_rows(db, record_id)] == [(TRANSCRIBE, "running")]


def test_reclaimed_after_last_attempt_fails(client, db, parent_id, fake_storage):
    record_id = new_voice_record(client, fake_storage, parent_id)
    run_sql(db, "UPDATE jobs SET attempts = max_attempts WHERE target_id = :id", id=record_id)

    job = claim_job(db, record_id, TRANSCRIBE)
    assert job.attempts > job.max_attempts
    worker.run_job(db, job)

    data = processing(client, record_id)
    assert data["processing_status"] == "failed" and data["processing_error"] == "STT_FAILED"
    assert [tuple(j) for j in job_rows(db, record_id)] == [(TRANSCRIBE, "failed")]


def test_one_active_transcription_per_record(client, db, parent_id, fake_storage):
    record_id = new_voice_record(client, fake_storage, parent_id)

    with pytest.raises(Exception) as e:
        with db.begin():
            transcription_service.enqueue_transcription(db, record_id)

    assert getattr(e.value, "code", None) == "ALREADY_PROCESSING"


def test_final_failure_is_one_transaction(client, db, parent_id, fake_storage, monkeypatch):
    """on_failure 오류 → 작업만 failed, 기록은 그대로 (중간 상태 없음)"""
    record_id = new_voice_record(client, fake_storage, parent_id)
    job = claim_job(db, record_id, TRANSCRIBE)

    def broken(db, job, code):
        from app.repositories import record_repo
        record_repo.set_processing_status(db, job.payload["record_id"], "failed", code)
        raise RuntimeError("on_failure 중간 오류")

    monkeypatch.setitem(TASKS, TRANSCRIBE, TASKS[TRANSCRIBE].__class__(
        func=TASKS[TRANSCRIBE].func, on_failure=broken
    ))
    worker.fail_job(db, TASKS[TRANSCRIBE], job, "AUDIO_MISSING", "test")

    assert processing(client, record_id)["processing_status"] == "pending"
    assert [tuple(j) for j in job_rows(db, record_id)] == [(TRANSCRIBE, "failed")]


# ── 업로드 상태 ──

def test_upload_state_constraints(client, db, parent_id, fake_storage):
    upload = uploaded(client, fake_storage, parent_id)

    for query in (
        "UPDATE audio_uploads SET status = 'consumed' WHERE id = :id",
        "UPDATE audio_uploads SET audio_path = 'other' WHERE id = :id",
    ):
        with pytest.raises(DBAPIError):
            run_sql(db, query, id=upload["upload_id"])
        db.rollback()

    run_sql(db, "UPDATE audio_uploads SET status = 'expired' WHERE id = :id", id=upload["upload_id"])
    with pytest.raises(DBAPIError):
        run_sql(db, "UPDATE audio_uploads SET status = 'issued' WHERE id = :id", id=upload["upload_id"])
    db.rollback()


# ── 정리 작업 ──

def age(db, upload_id, days):
    run_sql(
        db,
        "UPDATE audio_uploads SET expires_at = now() - make_interval(days => :d) WHERE id = :id",
        id=upload_id, d=days
    )


def upload_state(db, upload_id):
    return run_sql(
        db,
        "SELECT status, storage_deleted_at IS NOT NULL AS deleted FROM audio_uploads WHERE id = :id",
        id=upload_id
    )[0]


def test_cleanup_orphan_uploads(client, db, parent_id, fake_storage):
    orphan = uploaded(client, fake_storage, parent_id)
    recent = uploaded(client, fake_storage, parent_id)
    used = uploaded(client, fake_storage, parent_id)
    create(client, used["upload_id"], parent_id)
    age(db, orphan["upload_id"], 8)
    age(db, recent["upload_id"], 6)
    age(db, used["upload_id"], 30)

    upload_cleanup_service.run(db)

    assert tuple(upload_state(db, orphan["upload_id"])) == ("expired", True)
    assert tuple(upload_state(db, recent["upload_id"])) == ("issued", False)
    assert tuple(upload_state(db, used["upload_id"])) == ("consumed", False)
    assert orphan["audio_path"] in fake_storage.removed
    assert used["audio_path"] in fake_storage.files


def test_cleanup_retries_after_storage_failure(client, db, parent_id, fake_storage):
    orphan = uploaded(client, fake_storage, parent_id)
    age(db, orphan["upload_id"], 8)

    fake_storage.fail_remove = True
    upload_cleanup_service.run(db)
    assert tuple(upload_state(db, orphan["upload_id"])) == ("expired", False)
    # 삭제 예정 업로드 → 기록 생성 불가
    assert create(client, orphan["upload_id"], parent_id).status_code == 410

    fake_storage.fail_remove = False
    upload_cleanup_service.run(db)
    assert tuple(upload_state(db, orphan["upload_id"])) == ("expired", True)


def test_cleanup_recovers_when_db_update_failed(client, db, parent_id, fake_storage, monkeypatch):
    orphan = uploaded(client, fake_storage, parent_id)
    age(db, orphan["upload_id"], 8)

    from app.repositories import upload_repo
    original = upload_repo.mark_storage_deleted

    def fail_once(*args):
        raise RuntimeError("DB down")

    monkeypatch.setattr(upload_repo, "mark_storage_deleted", fail_once)
    with pytest.raises(RuntimeError):
        upload_cleanup_service.run(db)
    db.rollback()
    assert orphan["audio_path"] not in fake_storage.files

    # 다음 실행: 이미 없는 파일 다시 삭제 (오류 아님) → 완료 기록
    monkeypatch.setattr(upload_repo, "mark_storage_deleted", original)
    upload_cleanup_service.run(db)
    assert tuple(upload_state(db, orphan["upload_id"])) == ("expired", True)


def test_cleanup_skips_referenced_file(client, db, user_id, parent_id, fake_storage):
    orphan = uploaded(client, fake_storage, parent_id)
    record_id = sql_scalar(
        db,
        """
            INSERT INTO records (parent_id, author_id, input_type, source, audio_path, audio_duration_seconds)
            VALUES (:p, :u, 'voice', 'direct', :path, 3)
            RETURNING id
        """,
        p=parent_id, u=user_id, path=orphan["audio_path"]
    )
    age(db, orphan["upload_id"], 8)

    upload_cleanup_service.run(db)

    row = run_sql(db, "SELECT status, record_id FROM audio_uploads WHERE id = :id", id=orphan["upload_id"])[0]
    assert row.status == "consumed" and str(row.record_id) == str(record_id)
    assert orphan["audio_path"] in fake_storage.files


# ── 재생 ──

def test_playback_url(client, db, consent_docs, parent_id, fake_storage):
    record_id = new_voice_record(client, fake_storage, parent_id)
    text_record = client.post(f"/v1/parents/{parent_id}/records/text", json={"text": "밥"}).json()["data"]["id"]

    join_family(db, client, consent_docs, parent_id, "viewer")
    response = client.get(f"/v1/records/{record_id}/audio")
    assert response.status_code == 200
    assert response.json()["data"]["expires_in_seconds"] == 300

    assert client.get(f"/v1/records/{text_record}/audio").status_code == 404


def test_playback_hidden_from_other_family(client, db, consent_docs, parent_id, fake_storage):
    from tests.integration.conftest import agree_all, create_auth_user

    record_id = new_voice_record(client, fake_storage, parent_id)
    client.login(create_auth_user(db))
    agree_all(client, consent_docs)

    assert client.get(f"/v1/records/{record_id}/audio").status_code == 404
