from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    ENV: Literal["local", "test", "staging", "production"] = "local"

    DATABASE_URL: str
    SUPABASE_URL: str
    SUPABASE_PUBLISHABLE_KEY: str
    # 서버 전용 (Storage 서명 URL 발급, 파일 삭제). 앱/웹에 노출 금지
    SUPABASE_SECRET_KEY: str | None = None

    STORAGE_AUDIO_BUCKET: str = "audio"
    STORAGE_IMPORT_BUCKET: str = "kakao-imports"

    # mock / stub / real. 미설정 → local·test: mock, staging: stub, production: 오류
    # 허용 범위: app/ai/provider.py ALLOWED_MODES
    AI_PROVIDER: str | None = None

    # 목록 커서 서명 키 (HMAC). 미설정 → local·test: 개발용 고정값, staging·production: 시작 중단
    CURSOR_SECRET: str | None = None

    # 초대 링크 앞부분 (앱 링크 도메인 미정). 토큰은 #t= 뒤 (서버·미리보기 봇에 전송 X)
    INVITE_BASE_URL: str = "https://example.invalid/invite"

    # 앞단 프록시 수. 0 → X-Forwarded-For 무시 (위조 방지), 배포처 정해지면 설정
    TRUSTED_PROXY_HOPS: int = 0

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        extra="ignore"
    )

    @model_validator(mode="after")
    def require_deploy_secrets(self):
        if self.ENV in ("staging", "production") and not self.CURSOR_SECRET:
            raise ValueError("CURSOR_SECRET 필요 (staging·production)")
        return self


settings = Settings()
