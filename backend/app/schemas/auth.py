from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.consents import ConsentType


class MeUserOut(BaseModel):
    id: str
    login_type: str | None
    # 본인이 정한 표시 이름 (초대·작성자 표시). 미설정 → null
    display_name: str | None


class OnboardingOut(BaseModel):
    consents_completed: bool
    missing_consents: list[ConsentType]
    # 표시 이름 입력 여부. 순서: 동의 → 이름 → 부모님 등록
    name_set: bool
    parent_registered: bool


class AccountOut(BaseModel):
    # withdrawn: 탈퇴 접수됨 → 다른 API 403 ACCOUNT_WITHDRAWN
    status: Literal["active", "withdrawn"]
    # 탈퇴 삭제 예정 시각 (active → null)
    deletion_scheduled_for: datetime | None


class MeOut(BaseModel):
    user: MeUserOut
    account: AccountOut
    onboarding: OnboardingOut
    parent_ids: list[str]


# 수정 불가 → 400 IMMUTABLE_FIELD
ME_IMMUTABLE_FIELDS = {"id", "login_type", "phone", "created_at"}


class MeUpdateIn(BaseModel):
    """본인만. 실명 아니어도 됨 (예: 홍길동). 관계 호칭(형·동생) 아님"""

    display_name: str | None = Field(None, min_length=1, max_length=20)

    model_config = {"str_strip_whitespace": True, "extra": "allow"}
