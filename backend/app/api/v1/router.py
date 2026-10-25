from fastapi import APIRouter

from app.api.v1 import auth, consents, dev, parents, records
from app.core.config import settings


api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(consents.router, prefix="/consents", tags=["consents"])
api_router.include_router(parents.router, prefix="/parents", tags=["parents"])
api_router.include_router(records.router, tags=["records"])

# 로컬 개발 확인용
if settings.ENV == "local":
    api_router.include_router(dev.router, prefix="/dev", tags=["dev"])
