from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession, ProfileUser
from app.schemas.account import WithdrawalCheckOut, WithdrawalIn, WithdrawalOut
from app.schemas.common import DataResponse
from app.services import account_service


# 로그인만 (동의 철회한 사용자도 탈퇴 가능)
router = APIRouter()


@router.get("/me/withdrawal-check", response_model=DataResponse[WithdrawalCheckOut])
def withdrawal_check(user: CurrentUser, db: DbSession):
    """탈퇴 전 확인: 부모님별 관리자 넘기기·혼자 쓰던 공간"""
    with db.begin():
        return {"data": account_service.withdrawal_check(db, user.id)}


@router.post("/me/withdrawal", response_model=DataResponse[WithdrawalOut])
def withdraw(body: WithdrawalIn, user: ProfileUser, db: DbSession):
    """탈퇴 접수 (A-SET-003). 즉시 가족에서 나감 + 계정 차단, 삭제는 예정일에

    탈퇴 계정도 호출 가능 (응답 유실 후 재요청 → 같은 결과)
    """
    with db.begin():
        return {"data": account_service.withdraw(db, user.id, body)}
