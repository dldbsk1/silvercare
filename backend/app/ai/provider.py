"""AI 구현체 선택. 서비스 코드는 이 함수들로만 사용

- AI_PROVIDER: mock(키워드·고정 받아쓰기) / stub(STT 없음) / real(AI 팀원 구현, 합칠 때 추가)
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
from app.ai.stub import (
    StubKakaoExtractor,
    StubRecordClassifier,
    StubReportSummarizer,
    StubSpeechToText,
)
from app.core.config import settings


ALLOWED_MODES = {
    "local": {"mock", "stub"},
    "test": {"mock", "stub"},
    "staging": {"stub", "real"},
    "production": {"real"},
}

DEFAULT_MODES = {"local": "mock", "test": "mock", "staging": "stub"}

# real 구현 합친 뒤 추가
IMPLEMENTED_MODES = {"mock", "stub"}


def ai_mode() -> str:
    mode = settings.AI_PROVIDER or DEFAULT_MODES.get(settings.ENV)

    if mode is None:
        raise RuntimeError(f"ENV={settings.ENV}: AI_PROVIDER 설정 필요")
    if mode not in ALLOWED_MODES[settings.ENV]:
        raise RuntimeError(f"ENV={settings.ENV}: AI_PROVIDER={mode} 사용 불가")
    if mode not in IMPLEMENTED_MODES:
        raise RuntimeError(f"AI_PROVIDER={mode}: 구현 없음")

    return mode


def check_ai_config():
    """서버·워커 시작 시. 잘못된 배포 설정 → 바로 중단"""
    ai_mode()


def stt_configured() -> bool:
    return ai_mode() != "stub"


def get_speech_to_text() -> SpeechToText:
    if ai_mode() == "mock":
        return MockSpeechToText()
    return StubSpeechToText()


def get_record_classifier() -> RecordClassifier:
    if ai_mode() == "mock":
        return MockRecordClassifier()
    return StubRecordClassifier()


def get_kakao_extractor() -> KakaoExtractor:
    return StubKakaoExtractor()


def get_report_summarizer() -> ReportSummarizer:
    return StubReportSummarizer()
