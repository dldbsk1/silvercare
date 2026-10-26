"""AI 구현체 선택. 서비스 코드는 이 함수들로만 사용

- AI_PROVIDER: mock(키워드) / stub(항상 빈 결과) / real(AI 팀원 구현, 합칠 때 추가)
- 미설정 → local: mock, 그 외: stub
- mock: local 전용 (운영 사용 시 오류)
"""
from app.ai.interfaces import (
    KakaoExtractor,
    RecordClassifier,
    ReportSummarizer,
    SpeechToText,
)
from app.ai.mock import MockRecordClassifier
from app.ai.stub import (
    StubKakaoExtractor,
    StubRecordClassifier,
    StubReportSummarizer,
    StubSpeechToText,
)
from app.core.config import settings


def ai_mode() -> str:
    mode = settings.AI_PROVIDER or ("mock" if settings.ENV == "local" else "stub")

    if mode == "mock" and settings.ENV != "local":
        raise RuntimeError(f"ENV={settings.ENV}: AI_PROVIDER=mock 사용 불가")
    if mode not in ("mock", "stub"):
        raise RuntimeError(f"AI_PROVIDER={mode}: 구현 없음")

    return mode


def get_speech_to_text() -> SpeechToText:
    return StubSpeechToText()


def get_record_classifier() -> RecordClassifier:
    if ai_mode() == "mock":
        return MockRecordClassifier()
    return StubRecordClassifier()


def get_kakao_extractor() -> KakaoExtractor:
    return StubKakaoExtractor()


def get_report_summarizer() -> ReportSummarizer:
    return StubReportSummarizer()
