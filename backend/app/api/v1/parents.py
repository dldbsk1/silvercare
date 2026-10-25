from uuid import UUID

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.api.deps import ConsentedUser, DbSession, IdempotencyKey, ReadAccess
from app.schemas.common import DataResponse
from app.schemas.parents import ParentCreateIn, ParentOut
from app.services import parent_service
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
