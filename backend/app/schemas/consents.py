from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


ConsentType = Literal["service", "privacy", "health", "noti"]


class ConsentRevokeIn(BaseModel):
    """필수 동의 철회 선택. 본문 없음 = 기본값"""

    # 내가 쓴 기록도 모두 지우기 (7일 뒤, 그 전에 다시 동의하면 취소). false → 기록 유지
    delete_my_records: bool = False

    model_config = {"extra": "forbid"}


class ConsentDocumentOut(BaseModel):
    type: ConsentType
    required: bool
    doc_version: str
    title: str
    content: str


class ConsentItemIn(BaseModel):
    type: ConsentType
    doc_version: str = Field(min_length=1, max_length=100)
    agreed: bool


class ConsentsIn(BaseModel):
    items: list[ConsentItemIn] = Field(min_length=1, max_length=4)

    @field_validator("items")
    @classmethod
    def unique_types(cls, items: list[ConsentItemIn]):
        types = [item.type for item in items]
        if len(types) != len(set(types)):
            raise ValueError("같은 동의 종류가 두 번 들어 있어요.")
        return items


class CurrentConsentOut(BaseModel):
    type: ConsentType
    doc_version: str
    agreed_at: datetime
    # 지금 유효한 문구 버전에 대한 동의인지 (문구가 바뀌면 false → 다시 동의 필요)
    is_latest: bool


class ConsentHistoryOut(BaseModel):
    type: ConsentType
    doc_version: str
    agreed_at: datetime
    revoked_at: datetime | None


class ConsentStatusOut(BaseModel):
    completed: bool
    # 아직 동의하지 않았거나 문구가 바뀌어 다시 동의해야 하는 필수 항목
    missing_required: list[ConsentType]
    current: list[CurrentConsentOut]
    # 필수 동의 철회 → 내가 쓴 기록 삭제 예정 시각. 다시 동의하면 null (예약 취소)
    deletion_scheduled_for: datetime | None


class MyConsentsOut(ConsentStatusOut):
    history: list[ConsentHistoryOut]
