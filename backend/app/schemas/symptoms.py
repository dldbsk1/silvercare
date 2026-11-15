from datetime import date
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, model_validator


TimeBand = Literal["dawn", "morning", "afternoon", "evening", "night"]

# 직접 입력 증상
CUSTOM = "custom"

OCCURRENCE_MAX = 20
NOTE_MAX_LENGTH = 500


class SymptomIn(BaseModel):
    """증상 기록 (A-SYM-001). symptom_type: 추천 칩의 조사표 코드 또는 'custom' (+ custom_label)"""

    symptom_type: str = Field(min_length=1, max_length=50)
    custom_label: str | None = Field(None, min_length=1, max_length=20)
    time_band: TimeBand
    occurrence_count: int = Field(1, ge=1, le=OCCURRENCE_MAX)
    note: str | None = Field(None, max_length=NOTE_MAX_LENGTH)
    # 미입력 → 기록 시각만 (발생 시각 모름)
    occurred_at: AwareDatetime | None = None

    model_config = {"str_strip_whitespace": True, "extra": "forbid"}

    @model_validator(mode="after")
    def custom_needs_label(self):
        if (self.symptom_type == CUSTOM) != (self.custom_label is not None):
            raise ValueError("직접 입력은 증상 이름이 필요해요 (custom_label).")
        if self.note == "":
            self.note = None
        return self


class SymptomCreatedOut(BaseModel):
    record_id: str
    # 공간 삭제 때 멱등 키 응답 정리 기준 (parent_deletion_repo.delete_space)
    parent_id: str
    symptom_type: str
    label: str
    time_band: TimeBand
    occurrence_count: int


class SymptomSuggestionOut(BaseModel):
    symptom_type: str
    label: str
    # 최근 기간 이 항목으로 분류된 기록 수 (기본 추천 → 0일 수 있음)
    record_count: int


class SymptomSuggestionsOut(BaseModel):
    # personal: 우리 가족 기록 기준 / default: 기록 적음 → 기본 6개
    source: Literal["personal", "default"]
    items: list[SymptomSuggestionOut]


class SymptomWeekOut(BaseModel):
    week_start: date
    # 횟수 합 (기록마다 occurrence_count)
    count: int


class SymptomWeeklyOut(BaseModel):
    symptom_type: str
    label: str
    # 오래된 주 → 이번 주 (4개, 월요일 시작, 한국 시간)
    weeks: list[SymptomWeekOut]


class SymptomWeeklyQuery(BaseModel):
    symptom_type: str = Field(min_length=1, max_length=50)
    custom_label: str | None = Field(None, min_length=1, max_length=20)

    model_config = {"str_strip_whitespace": True, "extra": "forbid"}


class SymptomUpdateIn(BaseModel):
    """증상 기록 수정 (작성자만). 보낸 칸만. note: null 또는 "" → 비움
    기록 글 다시 만듦 + 수정 이력. base_version → RecordUpdateIn과 같음"""

    base_version: int = Field(ge=0)
    time_band: TimeBand | None = None
    occurrence_count: int | None = Field(None, ge=1, le=OCCURRENCE_MAX)
    note: str | None = Field(None, max_length=NOTE_MAX_LENGTH)

    model_config = {"str_strip_whitespace": True, "extra": "forbid"}
