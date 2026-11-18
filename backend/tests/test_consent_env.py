"""개발용 동의 문구 허용 범위 (DB 없이): local 항상 / staging 설정 시 / production 불가"""
import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.services import consent_service


@pytest.mark.parametrize("env, allow, expected", [
    ("local", False, True),
    ("staging", False, False),
    ("staging", True, True),
    ("production", False, False),
])
def test_dev_documents_allowed(monkeypatch, env, allow, expected):
    monkeypatch.setattr(settings, "ENV", env)
    monkeypatch.setattr(settings, "ALLOW_DEV_CONSENTS", allow)
    assert consent_service.dev_documents_allowed() is expected


def test_production_rejects_dev_consents():
    with pytest.raises(ValidationError, match="ALLOW_DEV_CONSENTS"):
        Settings(ENV="production", CURSOR_SECRET="x", ALLOW_DEV_CONSENTS=True)
