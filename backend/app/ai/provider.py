"""AI 구현체 선택. 서비스 코드는 이 함수들로만 사용

- AI_PROVIDER: mock(키워드·고정 받아쓰기) / stub(STT 없음) / real(Gemini, GEMINI_API_KEY 필요)
- 미설정 → local·test: mock, staging: stub, production: 오류
- 허용 범위 벗어남 → 서버·워커 시작 시 중단 (check_ai_config)
"""
from app.ai.interfaces import (
    KakaoExtractor,
    RecordClassifier,
    ReportSummarizer,
    SpeechToText,
)
from app.ai.mock import MockRecordClassifier, MockSpeechToText
from app.ai.real import (
    GeminiKakaoExtractor, GeminiRecordClassifier, GeminiReportSummarizer, GeminiSpeechToText,
)
from app.ai.stub import (
    StubKakaoExtractor,
    StubRecordClassifier,
    StubReportSummarizer,
    StubSpeechToText,
)
from app.core.config import settings


ALLOWED_MODES = {
    "local": {"mock", "stub", "real"},
    "test": {"mock", "stub"},
    "staging": {"stub", "real"},
    "production": {"real"},
}

DEFAULT_MODES = {"local": "mock", "test": "mock", "staging": "stub"}

IMPLEMENTED_MODES = {"mock", "stub", "real"}


def ai_mode() -> str:
    mode = settings.AI_PROVIDER or DEFAULT_MODES.get(settings.ENV)

    if mode is None:
        raise RuntimeError(f"ENV={settings.ENV}: AI_PROVIDER 설정 필요")
    if mode not in ALLOWED_MODES[settings.ENV]:
        raise RuntimeError(f"ENV={settings.ENV}: AI_PROVIDER={mode} 사용 불가")
    if mode not in IMPLEMENTED_MODES:
        raise RuntimeError(f"AI_PROVIDER={mode}: 구현 없음")
    if mode == "real" and not settings.GEMINI_API_KEY:
        raise RuntimeError("AI_PROVIDER=real: GEMINI_API_KEY 필요")

    return mode


def check_ai_config():
    """서버·워커 시작 시. 잘못된 배포 설정 → 바로 중단"""
    ai_mode()


def stt_configured() -> bool:
    return ai_mode() != "stub"


def get_speech_to_text() -> SpeechToText:
    if ai_mode() == "mock":
        return MockSpeechToText()
    if ai_mode() == "real":
        return GeminiSpeechToText()
    return StubSpeechToText()


def get_record_classifier() -> RecordClassifier:
    if ai_mode() == "mock":
        return MockRecordClassifier()
    if ai_mode() == "real":
        return GeminiRecordClassifier()
    return StubRecordClassifier()


def get_kakao_extractor() -> KakaoExtractor:
    if ai_mode() == "real":
        return GeminiKakaoExtractor()
    return StubKakaoExtractor()


def get_report_summarizer() -> ReportSummarizer:
    if ai_mode() == "real":
        return GeminiReportSummarizer()
    return StubReportSummarizer()
