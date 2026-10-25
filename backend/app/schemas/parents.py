from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


# 기능명세서 A-ON-003 선택지 (60대/70대/80대/90대 이상)
AgeBand = Literal["60s", "70s", "80s", "90s+"]
# 신청 전 / 조사 대기 / 결과 나옴 / 갱신 준비
ApplyStage = Literal["before", "waiting", "result", "renewal"]
FamilyRole = Literal["admin", "writer", "viewer"]


class ParentCreateIn(BaseModel):
    # 호칭만 받는다. 이름·주민번호 필드 없음 (POL-07)
    nickname: str = Field(min_length=1, max_length=20)
    age_band: AgeBand | None = None
    apply_stage: ApplyStage = "before"
    cohabiting: bool = False

    model_config = {"str_strip_whitespace": True}


class ParentOut(BaseModel):
    id: str
    nickname: str
    age_band: str | None
    apply_stage: ApplyStage
    cohabiting: bool
    survey_date: date | None
    judged_date: date | None
    survey_scheduled_at: datetime | None
    my_role: FamilyRole
