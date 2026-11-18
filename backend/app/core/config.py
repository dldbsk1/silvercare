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

    # AI_PROVIDER=real (Gemini). 모델명은 바뀌므로 .env에서 교체. 무료 등급은 실사용자 데이터 금지
    GEMINI_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-3.1-flash-lite"

    # 목록 커서 서명 키 (HMAC). 미설정 → local·test: 개발용 고정값, staging·production: 시작 중단
    CURSOR_SECRET: str | None = None

    # 초대 링크 앞부분 (앱 링크 도메인 미정). 토큰은 #t= 뒤 (서버·미리보기 봇에 전송 X)
    INVITE_BASE_URL: str = "https://example.invalid/invite"

    # 앞단 프록시 수. 0 → X-Forwarded-For 무시 (위조 방지), 배포처 정해지면 설정
    TRUSTED_PROXY_HOPS: int = 0

    # 카카오 Admin 키 (서버 전용). 탈퇴 삭제 실행 때 카카오 연결 끊기. 없음 → 건너뜀
    KAKAO_ADMIN_KEY: str | None = None

    # 탈퇴·동의 철회 삭제 실행 (워커). ⚖️ 법률 상담 전 운영 false, 개발 DB에서만 켜서 확인
    DELETION_EXECUTE_ENABLED: bool = False

    # 개발용(dev-) 동의 문구 허용. local → 항상 허용 / staging → 이 값 / production → 켜면 시작 중단
    # 팀 내부 베타 (실제 문구 발행 전)용
    ALLOW_DEV_CONSENTS: bool = False

    # 웹 앱(브라우저) 허용 주소. 쉼표 구분. 비움 + local → localhost·127.0.0.1 모든 포트 허용 (flutter run -d chrome)
    CORS_ORIGINS: str = ""

    # 워커 깨우기 (app/workers/wake.py)
    # none: 상시 워커 프로세스 폴링 (로컬) / cloud_tasks: Cloud Run 워커 서비스를 작업 등록 때 깨움
    WORKER_WAKE: Literal["none", "cloud_tasks"] = "none"
    GCP_PROJECT: str | None = None
    GCP_LOCATION: str = "asia-northeast1"
    TASKS_QUEUE: str = "worker-wake"
    # 워커 서비스 주소 (끝 / 없이). 예: https://silvercare-worker-123456789.asia-northeast1.run.app
    WORKER_URL: str | None = None
    # Cloud Tasks·Scheduler가 워커 호출할 때 쓰는 서비스 계정 (워커 run.invoker 권한)
    TASKS_INVOKER_SA: str | None = None

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        extra="ignore"
    )

    @model_validator(mode="after")
    def require_deploy_secrets(self):
        if self.ENV in ("staging", "production") and not self.CURSOR_SECRET:
            raise ValueError("CURSOR_SECRET 필요 (staging·production)")
        if self.ENV == "production" and self.ALLOW_DEV_CONSENTS:
            raise ValueError("ALLOW_DEV_CONSENTS=true 는 production 불가 (staging만)")
        if self.WORKER_WAKE == "cloud_tasks":
            missing = [k for k in ("GCP_PROJECT", "WORKER_URL", "TASKS_INVOKER_SA") if not getattr(self, k)]
            if missing:
                raise ValueError(f"WORKER_WAKE=cloud_tasks → {', '.join(missing)} 필요")
        return self


settings = Settings()
