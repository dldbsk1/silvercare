"""음성 기록 전체 흐름을 실제 서버·워커·Storage로 확인 (앱과 같은 순서)

준비: 서버(.\\run.ps1)와 워커(python -m app.workers.worker)가 켜져 있어야 함
      로그인 계정은 동의 완료 상태 (안 됐으면 smoke_test 먼저)

    cd backend
    python -m scripts.voice_test                  # 3초 테스트 음성 자동 생성
    python -m scripts.voice_test 녹음.m4a          # 실제 녹음 파일

1. 업로드 URL 발급 → 2. Storage 직접 업로드 → 3. 기록 생성 (202)
4. 처리 상태 조회 (받아쓰기 → 분류) → 5. 재생 URL → 6. 재전송·중복 확인
끝나면 만든 기록·파일 삭제 여부 선택
"""
import getpass
import io
import sys
import time
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path

import httpx
import mutagen
from sqlalchemy import text
from supabase import create_client

from app.core.config import settings
from app.db import storage
from app.db.session import new_session


BASE_URL = "http://127.0.0.1:8001"
POLL_SECONDS = 60

CONTENT_TYPES = {".m4a": "audio/mp4", ".aac": "audio/aac", ".mp3": "audio/mpeg", ".wav": "audio/wav"}


def sample_wav(seconds=3) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000 * seconds)
    return buffer.getvalue()


def load_audio() -> tuple[bytes, str, int]:
    if len(sys.argv) < 2:
        return sample_wav(), "audio/wav", 3

    path = Path(sys.argv[1])
    content_type = CONTENT_TYPES.get(path.suffix.lower())
    if content_type is None:
        raise SystemExit(f"지원 형식: {', '.join(CONTENT_TYPES)}")

    data = path.read_bytes()
    parsed = mutagen.File(io.BytesIO(data))
    seconds = round(parsed.info.length) if parsed else 3
    return data, content_type, min(max(seconds, 2), 180)


def step(title):
    print(f"\n── {title}")


def main():
    audio, content_type, duration = load_audio()

    app_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_PUBLISHABLE_KEY)
    email = input("테스트 계정 이메일: ")
    password = getpass.getpass("비밀번호: ")
    session = app_client.auth.sign_in_with_password(
        {"email": email, "password": password}
    ).session
    http = httpx.Client(
        base_url=BASE_URL, timeout=30,
        headers={"Authorization": f"Bearer {session.access_token}"}
    )

    me = http.get("/v1/auth/me").json()["data"]
    if not me["onboarding"]["consents_completed"]:
        raise SystemExit("동의가 안 된 계정이에요. python -m scripts.smoke_test 먼저 실행")

    parents = http.get("/v1/parents").json()["data"]
    if parents:
        parent_id = parents[0]["id"]
    else:
        parent_id = http.post("/v1/parents", json={
            "nickname": "음성테스트", "age_band": "80s",
            "apply_stage": "before", "cohabiting": False
        }).json()["data"]["id"]
    print(f"부모님 {parent_id}")

    step("1. 업로드 URL 발급")
    response = http.post(
        f"/v1/parents/{parent_id}/records/audio/upload-url",
        json={"content_type": content_type}
    )
    print(response.status_code, response.text[:300])
    issued = response.json()["data"]

    step("2. Storage 직접 업로드 (앱과 같은 publishable key)")
    app_client.storage.from_(issued["bucket"]).upload_to_signed_url(
        issued["audio_path"], issued["token"], audio, {"content-type": content_type}
    )
    print(f"{len(audio):,} bytes, {content_type}, {duration}초")

    step("3. 기록 생성")
    key = str(uuid.uuid4())
    body = {
        "upload_id": issued["upload_id"],
        "duration_seconds": duration,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    response = http.post(
        f"/v1/parents/{parent_id}/records/audio", json=body,
        headers={"Idempotency-Key": key}
    )
    print(response.status_code)
    record = response.json()["data"]
    record_id = record["id"]
    print(f"기록 {record_id} stage={record['stage']} status={record['processing_status']}")

    step("4. 처리 상태 (워커)")
    last = None
    for _ in range(POLL_SECONDS):
        data = http.get(f"/v1/records/{record_id}/processing").json()["data"]
        state = (data["stage"], data["processing_status"], data["processing_error"])
        if state != last:
            print(f"stage={state[0]} status={state[1]} error={state[2]}")
            last = state
        if data["stage"] == "done" or data["processing_status"] == "failed":
            break
        time.sleep(1)
    else:
        print("60초 안에 안 끝남 → 워커가 켜져 있는지 확인")

    print(f"원문: {data['original_text']!r}")
    print(f"무음: {data['transcript_empty']}")
    print(f"분류: {[i['item_code'] for i in data['items']]}")

    step("5. 재생 URL")
    play = http.get(f"/v1/records/{record_id}/audio").json()["data"]
    same = httpx.get(play["url"], timeout=30).content == audio
    print(f"내려받은 파일 = 올린 파일: {same}")

    step("6. 재전송·중복")
    again = http.post(
        f"/v1/parents/{parent_id}/records/audio", json=body,
        headers={"Idempotency-Key": key}
    )
    print(f"같은 키 재전송: {again.status_code}, 같은 기록 {again.json()['data']['id'] == record_id}")
    dup = http.post(f"/v1/parents/{parent_id}/records/audio", json=body)
    print(f"키 없이 같은 파일: {dup.status_code} {dup.json()['error']['code']}")

    if input("\n만든 기록·파일을 지울까요? (y/n): ").strip().lower() == "y":
        cleanup(record_id, issued["audio_path"])
        print("삭제 완료")


def cleanup(record_id: str, audio_path: str):
    db = new_session()
    with db.begin():
        db.execute(text("DELETE FROM jobs WHERE target_id = :id"), {"id": record_id})
        db.execute(text("DELETE FROM audio_uploads WHERE record_id = :id"), {"id": record_id})
        db.execute(text("DELETE FROM records WHERE id = :id"), {"id": record_id})
    db.close()
    storage.remove_objects(settings.STORAGE_AUDIO_BUCKET, [audio_path])


if __name__ == "__main__":
    main()
