"""AI 설정 검사 (서버·워커 시작 시)"""
import pytest

from app.ai import provider
from app.ai.interfaces import SpeechToTextNotConfigured
from app.ai.stub import StubSpeechToText
from app.core.config import settings


@pytest.fixture
def configure(monkeypatch):
    def set_config(env, ai_provider):
        monkeypatch.setattr(settings, "ENV", env)
        monkeypatch.setattr(settings, "AI_PROVIDER", ai_provider)
    return set_config


@pytest.mark.parametrize("env, ai_provider, mode", [
    ("local", None, "mock"),
    ("test", None, "mock"),
    ("local", "stub", "stub"),
    ("staging", None, "stub"),
])
def test_allowed(configure, env, ai_provider, mode):
    configure(env, ai_provider)

    provider.check_ai_config()
    assert provider.ai_mode() == mode


@pytest.mark.parametrize("env, ai_provider", [
    ("production", None),
    ("production", "mock"),
    ("production", "stub"),
    ("staging", "mock"),
    ("production", "real"),
    ("local", "unknown"),
])
def test_blocked_at_startup(configure, env, ai_provider):
    configure(env, ai_provider)

    with pytest.raises(RuntimeError):
        provider.check_ai_config()


def test_stub_stt_raises_not_configured():
    with pytest.raises(SpeechToTextNotConfigured):
        StubSpeechToText().transcribe(b"audio", "audio/mp4")


def test_stt_configured(configure):
    configure("local", "mock")
    assert provider.stt_configured() is True

    configure("local", "stub")
    assert provider.stt_configured() is False
