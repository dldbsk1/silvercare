"""음성 업로드 (Flutter → Storage 직접 업로드)

1. 앱이 create_upload()로 서명 업로드 URL을 받음
2. 앱이 Storage에 직접 올림
3. 앱이 audio_path로 기록 생성을 요청하면 verify_uploaded_audio()로 확인

경로 규칙: {parent_id}/{user_id}/{uuid}.{ext}  (버킷: settings.STORAGE_AUDIO_BUCKET)
"""
import uuid

from app.core.config import settings
from app.core.errors import AppError
from app.db import storage
from app.services.access import ParentAccess


# Flutter record 패키지 기본값은 AAC(m4a) = audio/mp4
AUDIO_EXTENSIONS = {
    "audio/mp4": "m4a",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/aac": "aac",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
}

# Supabase 서명 업로드 URL 유효 시간 (고정값)
UPLOAD_URL_EXPIRES_SECONDS = 2 * 60 * 60


def create_upload(access: ParentAccess, content_type: str) -> dict:
    extension = AUDIO_EXTENSIONS.get(content_type)

    if extension is None:
        raise AppError(
            400, "INVALID_FILE_TYPE", "지원하지 않는 음성 파일 형식이에요."
        )

    path = f"{access.parent_id}/{access.user_id}/{uuid.uuid4()}.{extension}"
    signed = storage.create_signed_upload_url(
        settings.STORAGE_AUDIO_BUCKET, path
    )

    return {
        "bucket": settings.STORAGE_AUDIO_BUCKET,
        "audio_path": signed["path"],
        "upload_url": signed["signed_url"],
        "token": signed["token"],
        "expires_in_seconds": UPLOAD_URL_EXPIRES_SECONDS,
    }


def verify_uploaded_audio(access: ParentAccess, audio_path: str):
    prefix = f"{access.parent_id}/{access.user_id}/"
    file_name = audio_path.removeprefix(prefix)

    if (
        not audio_path.startswith(prefix)
        or "/" in file_name
        or ".." in file_name
        or not file_name
    ):
        raise AppError(400, "INVALID_REQUEST", "음성 파일 경로가 올바르지 않아요.")

    if not storage.object_exists(settings.STORAGE_AUDIO_BUCKET, audio_path):
        raise AppError(
            400, "INVALID_REQUEST", "음성 파일 업로드가 끝나지 않았어요."
        )
