from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ai.provider import check_ai_config
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import register_exception_handlers


# 잘못된 AI 설정 → 시작 중단
check_ai_config()

app = FastAPI(title="SilverCare API")

register_exception_handlers(app)

# 브라우저 앱 (Flutter web 개발 · 이후 웹 대시보드). 앱(Android·iOS)은 CORS 무관
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?" if settings.ENV == "local" else None,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)


# 배포 헬스체크용이라 버전 경로 밖에 둔다
@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(api_router, prefix="/v1")
