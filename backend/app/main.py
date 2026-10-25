from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.errors import register_exception_handlers


app = FastAPI(title="SilverCare API")

register_exception_handlers(app)


# 배포 헬스체크용이라 버전 경로 밖에 둔다
@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(api_router, prefix="/v1")
