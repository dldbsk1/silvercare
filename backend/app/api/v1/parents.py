from uuid import UUID

from fastapi import APIRouter, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import AdminAccess, ConsentedUser, DbSession, IdempotencyKey, ReadAccess
from app.schemas.common import DataResponse
from app.schemas.home import HomeOut
from app.schemas.parent_deletion import ParentDeletionOut
from app.schemas.parents import ParentCreateIn, ParentOut, ParentUpdateIn
from app.services import home_service, parent_deletion_service, parent_service
from app.services.idempotency import run_idempotent


router = APIRouter()


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=DataResponse[ParentOut]
)
def create_parent(
    body: ParentCreateIn,
    user: ConsentedUser,
    db: DbSession,
    idempotency_key: IdempotencyKey = None
):
    """부모님 등록. 만든 사람이 관리자가 된다. 두 번 눌려도 Idempotency-Key로 한 번만 생성"""
    status_code, response = run_idempotent(
        db, user.id, "POST /v1/parents", idempotency_key,
        request_body=body.model_dump(mode="json"),
        handler=lambda: (
            201,
            {"data": parent_service.create_parent(db, user.id, body)}
        )
    )
    return JSONResponse(response, status_code=status_code)


@router.get("", response_model=DataResponse[list[ParentOut]])
def list_parents(user: ConsentedUser, db: DbSession):
    with db.begin():
        return {"data": parent_service.list_parents(db, user.id)}


@router.get("/{parent_id}", response_model=DataResponse[ParentOut])
def get_parent(parent_id: UUID, access: ReadAccess, db: DbSession):
    with db.begin():
        return {"data": parent_service.get_parent(db, access.user_id, access.parent_id)}



@router.patch("/{parent_id}", response_model=DataResponse[ParentOut])
def update_parent(parent_id: UUID, body: ParentUpdateIn, access: AdminAccess, db: DbSession):
    """관리자만. 공통 호칭·나이대·신청 단계·동거·조사일·판정일 (A-SET, D-day)"""
    with db.begin():
        return {"data": parent_service.update_parent(db, access, body)}


@router.get("/{parent_id}/home", response_model=DataResponse[HomeOut])
def get_home(parent_id: UUID, access: ReadAccess, db: DbSession):
    """홈 묶음 (A-HOME-007~009): 호칭·D-day·최근 기록 3건"""
    with db.begin():
        return {"data": home_service.get_home(db, access)}


# ── 공간 삭제 (내 정보 탭, 관리자) ──

@router.get("/{parent_id}/deletion", response_model=DataResponse[ParentDeletionOut | None])
def get_deletion(parent_id: UUID, access: ReadAccess, db: DbSession):
    """열린 삭제 요청. 없음 → data null (가족 누구나: 유예 안내용)"""
    with db.begin():
        return {"data": parent_deletion_service.get_status(db, access.user_id, access.parent_id)}


@router.post(
    "/{parent_id}/deletion",
    status_code=status.HTTP_201_CREATED,
    response_model=DataResponse[ParentDeletionOut]
)
def request_deletion(parent_id: UUID, user: ConsentedUser, db: DbSession):
    """관리자만. 관리자 1명 → 바로 유예 시작 / 여러 명 → 전원 동의 대기. 있음 → 409"""
    with db.begin():
        return {"data": parent_deletion_service.request_deletion(db, user.id, str(parent_id))}


@router.post("/{parent_id}/deletion/approve", response_model=DataResponse[ParentDeletionOut])
def approve_deletion(parent_id: UUID, user: ConsentedUser, db: DbSession):
    """다른 관리자 동의. 마지막 동의 → 유예 시작"""
    with db.begin():
        return {"data": parent_deletion_service.approve(db, user.id, str(parent_id))}


@router.delete("/{parent_id}/deletion", status_code=status.HTTP_204_NO_CONTENT)
def cancel_deletion(parent_id: UUID, user: ConsentedUser, db: DbSession):
    """관리자 누구나 취소 (동의 거절 포함). 삭제 진행 중 → 409"""
    with db.begin():
        parent_deletion_service.cancel(db, user.id, str(parent_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
