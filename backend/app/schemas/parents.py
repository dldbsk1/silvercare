from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


# 기능명세서 A-ON-003 선택지 (60대/70대/80대/90대 이상)
AgeBand = Literal["60s", "70s", "80s", "90s+"]
# 신청 전 / 조사 대기 / 결과 나옴 / 갱신 준비
ApplyStage = Literal["before", "waiting", "result", "renewal"]
FamilyRole = Literal["admin", "writer", "viewer"]
DdayStatus = Literal["not_set", "upcoming", "today", "past"]


class ParentCreateIn(BaseModel):
    # 호칭만 받는다. 이름·주민번호 필드 없음 (POL-07)
    nickname: str = Field(min_length=1, max_length=20)
    age_band: AgeBand | None = None
    apply_stage: ApplyStage = "before"
    cohabiting: bool = False

    model_config = {"str_strip_whitespace": True}


# 수정 불가 → 400 IMMUTABLE_FIELD. survey_scheduled_at: 조사일 투표 기능 전용
PARENT_IMMUTABLE_FIELDS = {
    "id", "created_at", "my_role", "dday", "survey_scheduled_at",
}
PARENT_NULLABLE_FIELDS = {"age_band", "survey_date", "judged_date"}


class ParentUpdateIn(BaseModel):
    """관리자만. 보낸 칸만 변경, null → 비움 (nullable 칸만)

    - nickname: 가족 공통 호칭
    - survey_date: 조사일. 연기 → 날짜 변경, 취소·미정 → null
    - judged_date: 실제 판정일 (미래 불가). 조사일 변경 시 자동 변경 X
    """

    nickname: str | None = Field(None, min_length=1, max_length=20)
    age_band: AgeBand | None = None
    apply_stage: ApplyStage | None = None
    cohabiting: bool | None = None
    # YYYY-MM-DD만 (시각 포함 거부)
    survey_date: date | None = None
    judged_date: date | None = None

    model_config = {"str_strip_whitespace": True, "extra": "allow"}

    @field_validator("survey_date", "judged_date", mode="before")
    @classmethod
    def date_only(cls, value):
        if isinstance(value, str) and len(value) != 10:
            raise ValueError("날짜는 YYYY-MM-DD 형식이에요.")
        return value


class DdayOut(BaseModel):
    survey_date: date | None
    # 지남 → 음수, 미정 → null
    days_left: int | None
    status: DdayStatus


class ParentOut(BaseModel):
    id: str
    # 가족 공통 호칭 (관리자가 정함)
    nickname: str
    age_band: str | None
    apply_stage: ApplyStage
    cohabiting: bool
    survey_date: date | None
    judged_date: date | None
    survey_scheduled_at: datetime | None
    my_role: FamilyRole
    dday: DdayOut
