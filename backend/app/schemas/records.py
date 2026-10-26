from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, field_validator


RecordSource = Literal["direct", "call", "kakao"]
RecordStatus = Literal["normal", "excluded"]
ProcessingStatus = Literal["pending", "processing", "completed", "failed"]
ClassificationStatus = Literal["classified", "unclassified"]
SetBy = Literal["ai", "user"]


# ── 음성 업로드 ──

class AudioUploadUrlIn(BaseModel):
    content_type: str = "audio/mp4"


class AudioUploadUrlOut(BaseModel):
    bucket: str
    audio_path: str
    upload_url: str
    token: str
    expires_in_seconds: int


# ── 텍스트 기록 ──

class TextRecordIn(BaseModel):
    # 앞뒤 공백 제거 후 1~1000자. kakao: 단톡방 불러오기 전용 → 거부
    text: str = Field(min_length=1, max_length=1000)
    source: Literal["direct", "call"] = "direct"
    # 오프셋 필수. 미입력 → 서버 시각
    recorded_at: AwareDatetime | None = None
    occurred_at: AwareDatetime | None = None

    model_config = {"str_strip_whitespace": True}


# 수정 불가 필드 → 400 IMMUTABLE_FIELD (POL-02 + 서버 관리 필드)
IMMUTABLE_FIELDS = {
    "id", "parent_id", "author_id", "input_type",
    "original_text", "audio_path", "audio_duration_seconds",
    "recorded_at", "created_at", "updated_at",
    "text_version", "status", "processing_status",
    "classification_status", "classified_by",
}


class RecordUpdateIn(BaseModel):
    """작성자만. 보낸 필드만 변경. occurred_at: null → 비움"""

    current_text: str | None = Field(None, min_length=1, max_length=1000)
    source: RecordSource | None = None
    occurred_at: AwareDatetime | None = None
    # 사용자 직접 분류: 52항목 코드만. [] → 미분류
    item_codes: list[str] | None = Field(None, max_length=10)

    model_config = {"str_strip_whitespace": True, "extra": "allow"}

    @field_validator("item_codes")
    @classmethod
    def unique_codes(cls, codes):
        if codes is not None and len(codes) != len(set(codes)):
            raise ValueError("같은 항목이 두 번 들어 있어요.")
        return codes


class RecordItemOut(BaseModel):
    area: str
    item_code: str
    label: str
    confidence: float | None
    set_by: SetBy


class RecordListItemOut(BaseModel):
    id: str
    parent_id: str
    author_id: str
    is_mine: bool
    input_type: str
    source: RecordSource
    status: RecordStatus
    processing_status: ProcessingStatus
    classification_status: ClassificationStatus | None
    current_text: str | None
    is_edited: bool
    areas: list[str]
    recorded_at: datetime
    occurred_at: datetime | None


class RecordOut(RecordListItemOut):
    original_text: str | None
    classified_by: SetBy | None
    text_version: int
    audio_duration_seconds: int | None
    items: list[RecordItemOut]
    created_at: datetime
    updated_at: datetime


class RecordProcessingOut(BaseModel):
    record_id: str
    processing_status: ProcessingStatus
    classification_status: ClassificationStatus | None
    classified_by: SetBy | None
    text_version: int
    original_text: str | None
    current_text: str | None
    items: list[RecordItemOut]
