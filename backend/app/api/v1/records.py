from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import WriteAccess
from app.schemas.common import DataResponse
from app.schemas.records import AudioUploadUrlIn, AudioUploadUrlOut
from app.services import audio_upload_service


router = APIRouter()


@router.post(
    "/parents/{parent_id}/records/audio/upload-url",
    status_code=status.HTTP_201_CREATED,
    response_model=DataResponse[AudioUploadUrlOut]
)
def create_audio_upload_url(
    parent_id: UUID,
    body: AudioUploadUrlIn,
    access: WriteAccess
):
    """음성 파일 업로드용 서명 URL 발급"""
    return {"data": audio_upload_service.create_upload(access, body.content_type)}
