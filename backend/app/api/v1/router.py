from fastapi import APIRouter

from app.api.v1 import auth, consents, dev, family, parents, records, settings as settings_api, users
from app.core.config import settings


api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(consents.router, prefix="/consents", tags=["consents"])
api_router.include_router(parents.router, prefix="/parents", tags=["parents"])
api_router.include_router(records.router, tags=["records"])
api_router.include_router(family.router, tags=["family"])
api_router.include_router(settings_api.router, tags=["settings"])
api_router.include_router(users.router, prefix="/users", tags=["users"])

# 로컬 개발 확인용
if settings.ENV == "local":
    api_router.include_router(dev.router, prefix="/dev", tags=["dev"])
