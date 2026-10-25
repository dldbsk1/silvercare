"""서비스 코드는 여기 함수로만 AI 구현체를 가져온다.

AI 담당자 구현이 합쳐지면 이 파일의 반환값만 바꾸면 된다.
"""
from app.ai.interfaces import (
    KakaoExtractor,
    RecordClassifier,
    ReportSummarizer,
    SpeechToText,
)
from app.ai.stub import (
    StubKakaoExtractor,
    StubRecordClassifier,
    StubReportSummarizer,
    StubSpeechToText,
)


def get_speech_to_text() -> SpeechToText:
    return StubSpeechToText()


def get_record_classifier() -> RecordClassifier:
    return StubRecordClassifier()


def get_kakao_extractor() -> KakaoExtractor:
    return StubKakaoExtractor()


def get_report_summarizer() -> ReportSummarizer:
    return StubReportSummarizer()
