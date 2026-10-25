"""Supabase Storage 접근 (서버 전용 secret key 사용).

앱/웹은 Storage에 직접 권한이 없다. 서버가 발급한 서명 업로드 URL로만 올릴 수 있다.
Storage 호출이 실패하면 503 SERVICE_UNAVAILABLE로 바꿔서 올린다.
"""
import logging
from contextlib import contextmanager
from functools import lru_cache

from supabase import Client, create_client

from app.core.config import settings
from app.core.errors import service_unavailable


logger = logging.getLogger("silvercare.storage")

MB = 1024 * 1024

# 버킷 설정. scripts/setup_storage.py가 이 내용대로 만들거나 맞춘다
BUCKETS = {
    settings.STORAGE_AUDIO_BUCKET: {
        "public": False,
        # 3분 녹음은 보통 3MB 안팎
        "file_size_limit": 10 * MB,
        "allowed_mime_types": [
            "audio/mp4", "audio/m4a", "audio/x-m4a", "audio/aac",
            "audio/mpeg", "audio/wav", "audio/x-wav",
        ],
    },
    settings.STORAGE_IMPORT_BUCKET: {
        "public": False,
        "file_size_limit": 20 * MB,
        "allowed_mime_types": ["text/plain"],
    },
}


@lru_cache
def get_admin_client() -> Client:
    if not settings.SUPABASE_SECRET_KEY:
        raise RuntimeError(".env에 SUPABASE_SECRET_KEY가 없습니다.")
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SECRET_KEY)


@contextmanager
def storage_call(action: str):
    try:
        yield
    except Exception as e:
        logger.exception("Storage 호출 실패: %s", action)
        raise service_unavailable("storage") from e


def create_signed_upload_url(bucket: str, path: str) -> dict:
    """{"signed_url", "token", "path"}. Supabase 기준 2시간 유효"""
    with storage_call("create_signed_upload_url"):
        result = get_admin_client().storage.from_(bucket) \
            .create_signed_upload_url(path)

    return {
        "signed_url": result["signed_url"],
        "token": result["token"],
        "path": result["path"],
    }


def object_exists(bucket: str, path: str) -> bool:
    # 파일이 없을 때는 라이브러리가 False를 돌려준다. 예외는 장애일 때만
    with storage_call("exists"):
        return get_admin_client().storage.from_(bucket).exists(path)


def remove_objects(bucket: str, paths: list[str]):
    with storage_call("remove"):
        get_admin_client().storage.from_(bucket).remove(paths)
