from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.schemas.common import DataResponse
from app.schemas.consents import (
    ConsentDocumentOut,
    ConsentsIn,
    ConsentStatusOut,
    ConsentType,
    MyConsentsOut,
)
from app.services import consent_service


# 동의 API는 동의 전에 써야 하므로 로그인만 확인한다 (CurrentUser)
router = APIRouter()


@router.get("/required", response_model=DataResponse[list[ConsentDocumentOut]])
def get_required_documents(user: CurrentUser, db: DbSession):
    """동의 화면에 보여줄 유효한 문구·버전·필수 여부"""
    with db.begin():
        return {"data": consent_service.list_required_documents(db)}


@router.post("", response_model=DataResponse[ConsentStatusOut])
def save_consents(body: ConsentsIn, user: CurrentUser, db: DbSession):
    with db.begin():
        return {"data": consent_service.save_consents(db, user.id, body.items)}


@router.get("/me", response_model=DataResponse[MyConsentsOut])
def get_my_consents(user: CurrentUser, db: DbSession):
    with db.begin():
        return {"data": consent_service.get_my_consents(db, user.id)}


@router.post("/{consent_type}/revoke", response_model=DataResponse[ConsentStatusOut])
def revoke_consent(consent_type: ConsentType, user: CurrentUser, db: DbSession):
    with db.begin():
        return {"data": consent_service.revoke(db, user.id, consent_type)}
