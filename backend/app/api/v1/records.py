from uuid import UUID

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse

from app.api.deps import (
    ConsentedUser,
    DbSession,
    IdempotencyKey,
    ReadAccess,
    WriteAccess,
)
from app.schemas.common import DataResponse
from app.schemas.records import (
    AudioPlaybackOut,
    AudioUploadUrlIn,
    AudioUploadUrlOut,
    RecordListItemOut,
    RecordOut,
    RecordProcessingOut,
    RecordStatus,
    RecordUpdateIn,
    TextRecordIn,
    VoiceRecordIn,
)
from app.services import audio_upload_service, record_service
from app.services.idempotency import run_idempotent


router = APIRouter()


@router.post(
    "/parents/{parent_id}/records/audio/upload-url",
    status_code=status.HTTP_201_CREATED,
    response_model=DataResponse[AudioUploadUrlOut]
)
def create_audio_upload_url(
    parent_id: UUID,
    body: AudioUploadUrlIn,
    access: WriteAccess,
    db: DbSession
):
    """음성 파일 업로드용 서명 URL + upload_id 발급. 트랜잭션: 서비스 (Storage 호출은 밖)"""
    return {"data": audio_upload_service.create_upload(db, access, body.content_type)}


@router.post(
    "/parents/{parent_id}/records/audio",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DataResponse[RecordOut]
)
def create_voice_record(
    parent_id: UUID,
    body: VoiceRecordIn,
    access: WriteAccess,
    db: DbSession,
    idempotency_key: IdempotencyKey = None
):
    """음성 기록 (A-HOME-001). 업로드 확인 → 저장 + 받아쓰기 작업. 같은 키 재전송 → 첫 응답"""
    status_code, response = run_idempotent(
        db, access.user_id, "POST /v1/parents/{parent_id}/records/audio",
        idempotency_key,
        request_body={"parent_id": access.parent_id, **body.model_dump(mode="json")},
        handler=lambda: (
            202,
            {"data": record_service.create_voice(db, access, body)}
        )
    )
    return JSONResponse(response, status_code=status_code)


@router.post(
    "/parents/{parent_id}/records/text",
    status_code=status.HTTP_201_CREATED,
    response_model=DataResponse[RecordOut]
)
def create_text_record(
    parent_id: UUID,
    body: TextRecordIn,
    access: WriteAccess,
    db: DbSession,
    idempotency_key: IdempotencyKey = None
):
    """텍스트 기록 (A-HOME-002). 저장 + 분류 작업 등록"""
    status_code, response = run_idempotent(
        db, access.user_id, "POST /v1/parents/{parent_id}/records/text",
        idempotency_key,
        request_body={"parent_id": access.parent_id, **body.model_dump(mode="json")},
        handler=lambda: (
            201,
            {"data": record_service.create_text(db, access, body)}
        )
    )
    return JSONResponse(response, status_code=status_code)


@router.get(
    "/parents/{parent_id}/records",
    response_model=DataResponse[list[RecordListItemOut]]
)
def list_records(
    parent_id: UUID,
    access: ReadAccess,
    db: DbSession,
    record_status: RecordStatus | None = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100)
):
    """최신순 목록. 홈 최근 기록: ?status=normal&limit=3"""
    with db.begin():
        return {"data": record_service.list_records(db, access, record_status, limit)}


@router.get("/records/{record_id}", response_model=DataResponse[RecordOut])
def get_record(record_id: UUID, user: ConsentedUser, db: DbSession):
    with db.begin():
        return {"data": record_service.get_detail(db, user.id, str(record_id))}


@router.get(
    "/records/{record_id}/processing",
    response_model=DataResponse[RecordProcessingOut]
)
def get_processing(record_id: UUID, user: ConsentedUser, db: DbSession):
    """저장 확인 카드 (A-HOME-005). 1~2초 간격 조회"""
    with db.begin():
        return {"data": record_service.get_processing(db, user.id, str(record_id))}


@router.get(
    "/records/{record_id}/audio",
    response_model=DataResponse[AudioPlaybackOut]
)
def get_record_audio(record_id: UUID, user: ConsentedUser, db: DbSession):
    """음성 재생 (A-DET-001). 5분 서명 URL, viewer 포함"""
    with db.begin():
        return {"data": record_service.get_audio_url(db, user.id, str(record_id))}


@router.patch("/records/{record_id}", response_model=DataResponse[RecordOut])
def update_record(
    record_id: UUID,
    body: RecordUpdateIn,
    user: ConsentedUser,
    db: DbSession
):
    """작성자만. 글·출처·일어난 시각·분류(52항목) 수정 (A-DET-002)"""
    with db.begin():
        return {"data": record_service.update(db, user.id, str(record_id), body)}


@router.post(
    "/records/{record_id}/reclassify",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DataResponse[RecordProcessingOut]
)
def reclassify_record(record_id: UUID, user: ConsentedUser, db: DbSession):
    """재처리 (A-HOME-004). 작성자만. 실패한 단계부터 (받아쓰기 / 분류)"""
    with db.begin():
        return {"data": record_service.reclassify(db, user.id, str(record_id))}
