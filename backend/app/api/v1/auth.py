from fastapi import APIRouter

from app.api.deps import ConsentedUser, CurrentUser, DbSession
from app.schemas.auth import MeOut, MeUpdateIn
from app.schemas.common import DataResponse
from app.services import user_service


router = APIRouter()


@router.get("/me", response_model=DataResponse[MeOut])
def get_my_info(user: CurrentUser, db: DbSession):
    """온보딩 상태. 앱은 이 값으로 동의 화면 / 부모님 등록 / 홈 중 어디로 갈지 정한다"""
    with db.begin():
        return {"data": user_service.get_me(db, user.id)}


@router.patch("/me", response_model=DataResponse[MeOut])
def update_my_info(body: MeUpdateIn, user: ConsentedUser, db: DbSession):
    """표시 이름 저장 (동의 후). 이름 변경 → 과거 기록 작성자 표시도 바로 반영"""
    with db.begin():
        return {"data": user_service.update_me(db, user.id, body)}
