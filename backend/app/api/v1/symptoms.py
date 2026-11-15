from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse

from app.api.deps import DbSession, IdempotencyKey, ReadAccess, WriteAccess
from app.schemas.common import DataResponse
from app.schemas.symptoms import (
    SymptomCreatedOut,
    SymptomIn,
    SymptomSuggestionsOut,
    SymptomWeeklyOut,
    SymptomWeeklyQuery,
)
from app.services import symptom_service
from app.services.idempotency import run_idempotent


router = APIRouter()


@router.get("/parents/{parent_id}/symptoms/suggestions", response_model=DataResponse[SymptomSuggestionsOut])
def get_suggestions(parent_id: UUID, access: ReadAccess, db: DbSession):
    """증상 칩 6개. 우리 가족 기록에서 많이 나온 항목 / 기록 적으면 기본 6개"""
    with db.begin():
        return {"data": symptom_service.suggestions(db, access)}


@router.post(
    "/parents/{parent_id}/symptoms",
    status_code=status.HTTP_201_CREATED,
    response_model=DataResponse[SymptomCreatedOut]
)
def create_symptom(
    parent_id: UUID,
    body: SymptomIn,
    access: WriteAccess,
    db: DbSession,
    idempotency_key: IdempotencyKey = None
):
    """증상 기록 (A-SYM-001). 같은 키 재전송 → 첫 응답"""
    status_code, response = run_idempotent(
        db, access.user_id, "POST /v1/parents/{parent_id}/symptoms",
        idempotency_key,
        request_body={"parent_id": access.parent_id, **body.model_dump(mode="json")},
        handler=lambda: (201, {"data": symptom_service.create(db, access, body)})
    )
    return JSONResponse(response, status_code=status_code)


@router.get("/parents/{parent_id}/symptoms/weekly", response_model=DataResponse[SymptomWeeklyOut])
def get_weekly(
    parent_id: UUID,
    access: ReadAccess,
    db: DbSession,
    query: Annotated[SymptomWeeklyQuery, Query()]
):
    """최근 4주 증상 횟수 (A-SYM-002). 이번 주 포함, 월요일 시작"""
    with db.begin():
        return {"data": symptom_service.weekly(db, access, query)}
