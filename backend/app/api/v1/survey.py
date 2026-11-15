from fastapi import APIRouter

from app.api.deps import ConsentedUser, DbSession
from app.repositories import survey_repo
from app.schemas.common import DataResponse
from app.schemas.records import SurveyItemOut


router = APIRouter()


@router.get("/survey/items", response_model=DataResponse[list[SurveyItemOut]])
def list_survey_items(user: ConsentedUser, db: DbSession):
    """조사표 52항목 (조사표 순서). 분류 바꾸기 목록 · 거의 안 바뀜 → 앱이 받아서 보관"""
    with db.begin():
        return {"data": [dict(r) for r in survey_repo.list_items(db)]}
