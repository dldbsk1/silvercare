from pathlib import Path
from typing import Literal

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

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        extra="ignore"
    )


settings = Settings()
