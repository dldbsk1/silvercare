"""음성 업로드 (Flutter → Storage 직접 업로드)

1. 앱이 create_upload()로 upload_id + 서명 업로드 URL을 받음 (audio_uploads issued)
2. 앱이 Storage에 직접 올림 (덮어쓰기 불가)
3. 앱이 upload_id로 기록 생성 요청 → take_upload()로 소유권·상태·파일 확인

경로 규칙: {parent_id}/{user_id}/{uuid}.{ext}  (버킷: settings.STORAGE_AUDIO_BUCKET)
소유권: 경로 형식이 아니라 audio_uploads 행 (사용자·부모님) 기준
"""
import logging
import uuid

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.db import storage
from app.repositories import upload_repo
from app.services.access import ParentAccess


logger = logging.getLogger("silvercare.audio")

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


def create_upload(db: Session, access: ParentAccess, content_type: str) -> dict:
    """Storage 서명 → audio_uploads 저장. 저장 실패 → 서명 URL 미사용 (무해)"""
    extension = AUDIO_EXTENSIONS.get(content_type)

    if extension is None:
        raise AppError(
            400, "INVALID_FILE_TYPE", "지원하지 않는 음성 파일 형식이에요."
        )

    path = f"{access.parent_id}/{access.user_id}/{uuid.uuid4()}.{extension}"
    signed = storage.create_signed_upload_url(
        settings.STORAGE_AUDIO_BUCKET, path
    )

    with db.begin():
        upload_id = upload_repo.insert_upload(
            db, access.user_id, access.parent_id, signed["path"],
            content_type, UPLOAD_URL_EXPIRES_SECONDS
        )

    return {
        "upload_id": upload_id,
        "bucket": settings.STORAGE_AUDIO_BUCKET,
        "audio_path": signed["path"],
        "upload_url": signed["signed_url"],
        "token": signed["token"],
        "expires_in_seconds": UPLOAD_URL_EXPIRES_SECONDS,
    }


def take_upload(db: Session, access: ParentAccess, upload_id: str):
    """기록 생성용 업로드 확인 (행 잠금). 사용 완료 처리는 기록 저장 후 consume

    - 없음 / 다른 사용자 / 다른 부모님 → 404
    - expired → 410 UPLOAD_EXPIRED
    - consumed → 409 AUDIO_ALREADY_USED (+ record_id)
    - Storage 파일 없음·크기 초과·허용 외 형식 → 400
    """
    upload = upload_repo.get_upload(db, upload_id, for_update=True)

    if (
        upload is None
        or str(upload["user_id"]) != access.user_id
        or str(upload["parent_id"]) != access.parent_id
    ):
        raise AppError(404, "NOT_FOUND", "업로드를 찾을 수 없어요.")

    if upload["status"] == "expired":
        raise AppError(
            410, "UPLOAD_EXPIRED", "업로드 기한이 지났어요. 다시 녹음해 주세요."
        )

    if upload["status"] == "consumed":
        # 같은 부모님 쓰기 권한 확인됨 → 그 기록 조회 권한 있음
        raise AppError(
            409, "AUDIO_ALREADY_USED", "이미 저장된 녹음이에요.",
            details={"record_id": str(upload["record_id"])}
        )

    check_uploaded_file(upload)
    return upload


def check_uploaded_file(upload):
    info = storage.object_info(settings.STORAGE_AUDIO_BUCKET, upload["audio_path"])

    if info is None:
        raise AppError(
            400, "INVALID_REQUEST", "음성 파일 업로드가 끝나지 않았어요.",
            details={"reason": "upload_incomplete"}
        )

    size_limit = storage.BUCKETS[settings.STORAGE_AUDIO_BUCKET]["file_size_limit"]
    if (info.get("size") or 0) > size_limit:
        raise AppError(413, "FILE_TOO_LARGE", "음성 파일이 너무 커요.")

    content_type = info.get("content_type")
    if content_type not in AUDIO_EXTENSIONS:
        raise AppError(400, "INVALID_FILE_TYPE", "지원하지 않는 음성 파일 형식이에요.")

    if content_type != upload["content_type"]:
        logger.warning(
            "업로드 MIME %s ≠ 발급 시 %s (%s)",
            content_type, upload["content_type"], upload["id"]
        )
