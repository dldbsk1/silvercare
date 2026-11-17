"""관찰 체크리스트 (A-TASK, SCR_A_310)"""
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


ChecklistAnswer = Literal["alone", "little", "full", "yes", "no", "not_seen"]
ChecklistStatus = Literal["pending", "in_progress", "overdue", "submitted", "cancelled"]
SuggestReason = Literal["no_records", "few_records", "not_seen_before"]

ITEMS_MAX = 10
NOTE_MAX_LENGTH = 200


class ChecklistCreateIn(BaseModel):
    to_user_id: UUID
    item_codes: list[str] = Field(min_length=1, max_length=ITEMS_MAX)
    due_date: date

    model_config = {"extra": "forbid"}


class AnswerIn(BaseModel):
    """note: "한 줄 덧붙이기" (못 봤어요에도 가능)"""

    answer: ChecklistAnswer
    note: str | None = Field(None, max_length=NOTE_MAX_LENGTH)

    model_config = {"str_strip_whitespace": True, "extra": "forbid"}

    @model_validator(mode="after")
    def empty_note(self):
        if self.note == "":
            self.note = None
        return self


class ChecklistListQuery(BaseModel):
    """received: 받은 탭 / sent: 보내기 탭 아래 보낸 목록
    open: 대기 (미제출·미취소) / done: 완료·취소 / all
    """

    box: Literal["received", "sent"] = "received"
    state: Literal["open", "done", "all"] = "all"
    limit: int = Field(50, ge=1, le=50)

    model_config = {"extra": "forbid"}


# ── 응답 ──

class DraftItemOut(BaseModel):
    item_code: str
    label: str
    hint: str
    scale: str
    # 가장 최근 기록 날짜 (한국 시간). 없음 → null ("기록 없음")
    last_recorded_on: date | None
    # 추천 이유. 추천 아님 → null
    reason: SuggestReason | None


class DraftAreaOut(BaseModel):
    area: str
    label: str
    items: list[DraftItemOut]


class DraftOut(BaseModel):
    # "기록이 부족한 N개 항목으로 만들었어요" (최대 6, 없음 → [])
    suggested_codes: list[str]
    areas: list[DraftAreaOut]


class UserRefOut(BaseModel):
    id: str
    name: str | None
    is_me: bool


class TaskOut(BaseModel):
    task_id: str
    item_code: str
    label: str
    area: str
    scale: str
    hint: str
    # 척도별 선택지 (화면 표시 순서)
    choices: list[ChecklistAnswer]
    answer: ChecklistAnswer | None
    note: str | None
    answered_at: datetime | None
    # 제출 뒤 생성된 기록 (못 봤어요 → null)
    record_id: str | None


class ChecklistSummaryOut(BaseModel):
    id: str
    parent_id: str
    from_user: UserRefOut
    to_user: UserRefOut
    due_date: date
    status: ChecklistStatus
    answered_items: int
    total_items: int
    created_at: datetime
    submitted_at: datetime | None
    cancelled_at: datetime | None


class ChecklistOut(ChecklistSummaryOut):
    is_recipient: bool
    # 답하기 순서 = 영역 → 조사표 순서
    items: list[TaskOut]


class AnswerOut(BaseModel):
    item: TaskOut
    answered_items: int
    total_items: int


class ChecklistListMeta(BaseModel):
    # 커서 없음 (한 공간 체크리스트 수 적음). 50개 넘으면 has_more
    next_cursor: None = None
    has_more: bool
    total: int


class ChecklistListOut(BaseModel):
    data: list[ChecklistSummaryOut]
    meta: ChecklistListMeta
