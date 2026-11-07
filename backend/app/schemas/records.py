from datetime import date, datetime
from typing import Literal

from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, field_validator


RecordSource = Literal["direct", "call", "kakao"]
RecordStatus = Literal["normal", "excluded"]
# 목록 조건. all → 사용 여부 무관
RecordStatusFilter = Literal["normal", "excluded", "all"]
InputType = Literal["voice", "text", "symptom", "kakao", "checklist"]
# 조사표 영역 (uncat 제외)
Area = Literal["physical", "cognitive", "behavior", "nursing", "rehab"]
ProcessingStatus = Literal["pending", "processing", "completed", "failed"]
ClassificationStatus = Literal["classified", "unclassified"]
SetBy = Literal["ai", "user"]
# 계산값: 음성 + 원문 없음 → transcription / 처리 미완료(실패 포함) → classification / done
Stage = Literal["transcription", "classification", "done"]

# 글 수정 한도. 음성: 3분 받아쓰기 ≈ 900~1200자
TEXT_MAX_LENGTH = 1000
VOICE_TEXT_MAX_LENGTH = 2000


# ── 음성 업로드 ──

class AudioUploadUrlIn(BaseModel):
    content_type: str = "audio/mp4"


class AudioUploadUrlOut(BaseModel):
    upload_id: str
    bucket: str
    audio_path: str
    upload_url: str
    token: str
    expires_in_seconds: int


class AudioPlaybackOut(BaseModel):
    url: str
    expires_in_seconds: int


# ── 음성 기록 ──

class VoiceRecordIn(BaseModel):
    # 업로드 URL 발급 때 받은 값. audio_path는 서버가 audio_uploads에서 꺼냄
    upload_id: UUID
    # 앱 측정값. 워커가 실제 길이로 덮어씀
    duration_seconds: int = Field(ge=2, le=180)
    source: Literal["direct", "call"] = "direct"
    # 오프라인 업로드 → 녹음 시각 필수, 오프셋 필수
    recorded_at: AwareDatetime
    occurred_at: AwareDatetime | None = None


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
    "text_version", "status", "processing_status", "processing_error",
    "classification_status", "classified_by", "transcript_empty",
}


class RecordUpdateIn(BaseModel):
    """작성자만. 보낸 필드만 변경. occurred_at: null → 비움"""

    # 텍스트 1000자 / 음성 2000자 (서비스에서 input_type별 확인)
    current_text: str | None = Field(None, min_length=1, max_length=VOICE_TEXT_MAX_LENGTH)
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


# ── 목록 (A-2) ──

SEARCH_MAX_LENGTH = 50


class RecordListQuery(BaseModel):
    """기록함 목록 조건. 모두 AND. cursor·limit 외 조건이 바뀌면 이전 커서 → 400 INVALID_CURSOR

    from / to: 기록한 날짜 (한국 시간), 양 끝 포함
    """

    area: Area | None = None
    author_id: UUID | None = None
    date_from: date | None = Field(None, alias="from")
    date_to: date | None = Field(None, alias="to")
    source: RecordSource | None = None
    input_type: InputType | None = None
    status: RecordStatusFilter = "normal"
    processing_status: ProcessingStatus | None = None
    # unclassified: 분석 완료 + 분류 항목 없음
    classification_status: ClassificationStatus | None = None
    # current_text만 (원문 X). 공백만 → 검색 없음
    q: str | None = Field(None, max_length=SEARCH_MAX_LENGTH)
    cursor: str | None = None
    limit: int = Field(20, ge=1, le=100)

    model_config = {"extra": "forbid", "str_strip_whitespace": True}

    @field_validator("q")
    @classmethod
    def blank_to_none(cls, q):
        return q or None


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
    # 작성자 표시 이름. 미설정 → null (앱: "가족")
    author_name: str | None
    is_mine: bool
    input_type: str
    source: RecordSource
    status: RecordStatus
    processing_status: ProcessingStatus
    stage: Stage
    processing_error: str | None
    classification_status: ClassificationStatus | None
    current_text: str | None
    transcript_empty: bool
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
    input_type: str
    stage: Stage
    processing_status: ProcessingStatus
    # failed 일 때만. STT_*, AUDIO_*, CLASSIFY_FAILED
    processing_error: str | None
    transcript_empty: bool
    classification_status: ClassificationStatus | None
    classified_by: SetBy | None
    text_version: int
    original_text: str | None
    current_text: str | None
    items: list[RecordItemOut]


# ── 수정 이력 ──

VersionField = Literal["text", "source", "occurred_at", "item_codes"]


class RecordSnapshotOut(BaseModel):
    text: str | None
    source: RecordSource | None
    occurred_at: datetime | None
    item_codes: list[str]
    classified_by: SetBy | None


class RecordVersionOut(BaseModel):
    # 사용자 수정 순번 (text_version과 별개)
    version: int
    edited_by: str
    edited_by_name: str | None
    is_mine: bool
    edited_at: datetime
    changed: list[VersionField]
    before: RecordSnapshotOut


class RecordVersionsOut(BaseModel):
    original_text: str | None
    current: RecordSnapshotOut
    history: list[RecordVersionOut]
