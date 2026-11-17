"""관찰 체크리스트 (A-TASK, SCR_A_310). API 명세서 6장"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse

from app.api.deps import ConsentedUser, DbSession, IdempotencyKey, ReadAccess, WriteAccess
from app.schemas.checklists import (
    AnswerIn,
    AnswerOut,
    ChecklistCreateIn,
    ChecklistListOut,
    ChecklistListQuery,
    ChecklistOut,
    DraftOut,
)
from app.schemas.common import DataResponse
from app.services import checklist_service
from app.services.idempotency import run_idempotent


router = APIRouter()


@router.get("/parents/{parent_id}/checklists/draft", response_model=DataResponse[DraftOut])
def get_draft(parent_id: UUID, access: ReadAccess, db: DbSession):
    """보내기 탭: 고르기 목록 42개 (설명·마지막 기록) + 추천 항목 최대 6개"""
    with db.begin():
        return {"data": checklist_service.draft(db, access)}


@router.post(
    "/parents/{parent_id}/checklists",
    status_code=status.HTTP_201_CREATED,
    response_model=DataResponse[ChecklistOut]
)
def create_checklist(
    parent_id: UUID,
    body: ChecklistCreateIn,
    access: WriteAccess,
    db: DbSession,
    idempotency_key: IdempotencyKey = None
):
    """체크리스트 보내기. 같은 키 재전송 → 첫 응답"""
    status_code, response = run_idempotent(
        db, access.user_id, "POST /v1/parents/{parent_id}/checklists",
        idempotency_key,
        request_body={"parent_id": access.parent_id, **body.model_dump(mode="json")},
        handler=lambda: (201, {"data": checklist_service.create(db, access, body)})
    )
    return JSONResponse(response, status_code=status_code)


@router.get("/parents/{parent_id}/checklists", response_model=ChecklistListOut)
def list_checklists(
    parent_id: UUID,
    access: ReadAccess,
    db: DbSession,
    query: Annotated[ChecklistListQuery, Query()]
):
    """받은 탭 (box=received&state=open) · 보낸 목록 (box=sent&state=all)"""
    with db.begin():
        return checklist_service.list_(db, access, query)


@router.get("/checklists/{checklist_id}", response_model=DataResponse[ChecklistOut])
def get_checklist(checklist_id: UUID, user: ConsentedUser, db: DbSession):
    with db.begin():
        return {"data": checklist_service.get(db, user.id, str(checklist_id))}


@router.put(
    "/checklists/{checklist_id}/items/{task_id}/answer",
    response_model=DataResponse[AnswerOut]
)
def answer_item(checklist_id: UUID, task_id: UUID, body: AnswerIn, user: ConsentedUser, db: DbSession):
    """항목 하나 답 (받은 사람, 보내기 전까지 덮어쓰기)"""
    with db.begin():
        return {"data": checklist_service.answer(db, user.id, str(checklist_id), str(task_id), body)}


@router.post("/checklists/{checklist_id}/submit", response_model=DataResponse[ChecklistOut])
def submit_checklist(checklist_id: UUID, user: ConsentedUser, db: DbSession):
    """모두 답했어요 → 보내기. 못 봤어요 제외 답마다 기록 1건. 다시 보내도 같은 응답"""
    with db.begin():
        return {"data": checklist_service.submit(db, user.id, str(checklist_id))}
