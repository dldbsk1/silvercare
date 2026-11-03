"""AI 연동 전 임시 구현.

외부 API를 호출하지 않고, 항상 "결과 없음"을 돌려준다.
백엔드 흐름(저장 → 비동기 처리 → 상태 변경)을 AI 없이 개발·테스트하기 위한 것.
- STT: 빈 글 대신 미설정 오류 (무음 성공으로 저장 방지)
"""
from app.ai.interfaces import (
    ItemClassification,
    ItemSummary,
    KakaoCandidate,
    KakaoMessage,
    SourceRecord,
    SpeechToTextNotConfigured,
    Transcript,
)


class StubSpeechToText:
    def transcribe(self, audio: bytes, content_type: str) -> Transcript:
        raise SpeechToTextNotConfigured("STT 구현 없음 (AI_PROVIDER=stub)")


class StubRecordClassifier:
    def classify(self, text: str) -> list[ItemClassification]:
        return []


class StubKakaoExtractor:
    def extract(
        self,
        messages: list[KakaoMessage]
    ) -> list[KakaoCandidate]:
        return []


class StubReportSummarizer:
    def summarize(
        self,
        item_code: str,
        records: list[SourceRecord]
    ) -> ItemSummary | None:
        return None
