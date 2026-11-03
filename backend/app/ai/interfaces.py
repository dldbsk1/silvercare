"""AI 모듈 계약 (AI 담당 팀원과 맞추는 지점).

백엔드는 이 파일의 타입과 함수 모양만 보고 호출한다.
AI 담당자는 같은 모양으로 구현체를 만들어 app/ai/provider.py에서 바꿔 끼운다.

규칙 (기능명세서 POL-03/06, API 명세서 4.3·11장)
- item_code는 반드시 survey_items.code 값. 확신이 낮으면 결과에서 빼서 "미분류"로 둔다.
- confidence는 0~1.
- 점수·등급을 만들지 않는다.
- 기록지 요약은 받은 기록에 없는 내용을 만들지 않는다. 근거 record_id를 반드시 돌려준다.
"""
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, Field


class SpeechToTextNotConfigured(Exception):
    """STT 구현·키 없음. 재시도 무의미 → STT_NOT_CONFIGURED"""


class Transcript(BaseModel):
    # "" = 말소리 없음 (정상 성공). 실패는 반드시 예외
    text: str


class ItemClassification(BaseModel):
    item_code: str
    confidence: float = Field(ge=0, le=1)


class KakaoMessage(BaseModel):
    message_at: datetime | None
    sender_label: str
    body: str


class KakaoCandidate(BaseModel):
    # 입력 messages 리스트에서의 위치
    message_index: int
    suggested_item_code: str | None


class SourceRecord(BaseModel):
    record_id: str
    text: str
    recorded_at: datetime


class ItemSummary(BaseModel):
    item_code: str
    summary_text: str
    source_record_ids: list[str]


class SpeechToText(Protocol):
    def transcribe(self, audio: bytes, content_type: str) -> Transcript:
        """음성 파일 → 받아쓴 원문

        - 말소리 없음 → Transcript(text="")
        - 오류 → 예외 (빈 글로 돌려주기 금지). 미설정 → SpeechToTextNotConfigured
        - 5분 안에 끝나거나 타임아웃 예외 (워커 회수 기준 10분보다 짧게)
        """
        ...


class RecordClassifier(Protocol):
    def classify(self, text: str) -> list[ItemClassification]:
        """기록 문장 → 52항목 분류 (여러 개 가능, 없으면 빈 리스트 = 미분류)"""
        ...


class KakaoExtractor(Protocol):
    def extract(
        self,
        messages: list[KakaoMessage]
    ) -> list[KakaoCandidate]:
        """단톡방 메시지 → 부모님 상태 관련 문장만 후보로"""
        ...


class ReportSummarizer(Protocol):
    def summarize(
        self,
        item_code: str,
        records: list[SourceRecord]
    ) -> ItemSummary | None:
        """항목별 기록 → 평소 모습 한 줄 요약. 근거가 없으면 None"""
        ...
