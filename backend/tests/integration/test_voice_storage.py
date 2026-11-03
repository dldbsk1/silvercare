"""실제 Storage 음성 흐름 (네트워크 필요)

    pytest -m storage          # 이것만
    pytest -m "not storage"    # 제외

업로드 URL 발급 → 서명 URL로 실제 업로드 → 기록 생성 → 워커 (다운로드·mutagen·Mock STT) → 재생 URL
업로드한 파일은 테스트 끝에 삭제
"""
import httpx
import pytest

from app.ai.mock import MOCK_TRANSCRIPT
from app.core.config import settings
from app.db import storage
from app.workers import worker
from tests.audio_samples import make_wav
from tests.integration.conftest import claim_job


pytestmark = pytest.mark.storage


@pytest.fixture
def uploaded_paths():
    paths = []
    yield paths
    if paths:
        storage.remove_objects(settings.STORAGE_AUDIO_BUCKET, paths)


def upload_real(client, parent_id, data, content_type, paths):
    issued = client.post(
        f"/v1/parents/{parent_id}/records/audio/upload-url",
        json={"content_type": content_type}
    ).json()["data"]
    paths.append(issued["audio_path"])

    bucket = storage.get_admin_client().storage.from_(issued["bucket"])
    bucket.upload_to_signed_url(
        issued["audio_path"], issued["token"], data, {"content-type": content_type}
    )
    return issued, bucket


def create(client, parent_id, upload_id):
    return client.post(f"/v1/parents/{parent_id}/records/audio", json={
        "upload_id": upload_id, "duration_seconds": 3,
        "recorded_at": "2026-11-03T09:00:00+09:00"
    })


def test_real_upload_transcribe_and_play(client, db, parent_id, uploaded_paths):
    audio = make_wav(3)
    issued, bucket = upload_real(client, parent_id, audio, "audio/wav", uploaded_paths)

    # 덮어쓰기 금지 (upsert false)
    with pytest.raises(Exception):
        bucket.upload_to_signed_url(
            issued["audio_path"], issued["token"], make_wav(5), {"content-type": "audio/wav"}
        )

    response = create(client, parent_id, issued["upload_id"])
    assert response.status_code == 202, response.text
    record_id = response.json()["data"]["id"]

    worker.run_job(db, claim_job(db, record_id, "transcribe_record"))

    data = client.get(f"/v1/records/{record_id}").json()["data"]
    assert data["original_text"] == MOCK_TRANSCRIPT
    assert data["audio_duration_seconds"] == 3
    assert data["stage"] == "classification"

    play = client.get(f"/v1/records/{record_id}/audio").json()["data"]
    assert httpx.get(play["url"], timeout=10).content == audio


def test_real_broken_file_is_unreadable(client, db, parent_id, uploaded_paths):
    issued, _ = upload_real(client, parent_id, b"not really audio", "audio/mp4", uploaded_paths)

    record_id = create(client, parent_id, issued["upload_id"]).json()["data"]["id"]
    worker.run_job(db, claim_job(db, record_id, "transcribe_record"))

    data = client.get(f"/v1/records/{record_id}/processing").json()["data"]
    assert data["processing_status"] == "failed"
    assert data["processing_error"] == "AUDIO_UNREADABLE"


def test_real_upload_not_finished(client, parent_id, uploaded_paths):
    issued = client.post(
        f"/v1/parents/{parent_id}/records/audio/upload-url", json={"content_type": "audio/wav"}
    ).json()["data"]

    response = create(client, parent_id, issued["upload_id"])

    assert response.status_code == 400
    assert response.json()["error"]["details"]["reason"] == "upload_incomplete"
