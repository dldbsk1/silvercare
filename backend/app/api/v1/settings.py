from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.common import DataResponse
from app.schemas.settings import (
    DeviceIn,
    DeviceOut,
    NotificationSettingsIn,
    NotificationSettingsOut,
)
from app.services import notification_service


# 로그인만 (동의 철회한 사용자도 알림 끄기·로그아웃 가능)
router = APIRouter()


@router.get("/settings/notifications", response_model=DataResponse[NotificationSettingsOut])
def get_notification_settings(user: CurrentUser, db: DbSession):
    with db.begin():
        return {"data": notification_service.get_settings(db, user.id)}


@router.put("/settings/notifications", response_model=DataResponse[NotificationSettingsOut])
def save_notification_settings(body: NotificationSettingsIn, user: CurrentUser, db: DbSession):
    """컨디션·할 일·브리핑 켜기/끄기 (A-SET-002). 세 값 모두"""
    with db.begin():
        return {"data": notification_service.save_settings(db, user.id, body)}


@router.post("/devices", response_model=DataResponse[DeviceOut])
def register_device(body: DeviceIn, user: CurrentUser, db: DbSession):
    """앱 실행·FCM 토큰 바뀔 때. 같은 토큰 → 갱신"""
    with db.begin():
        return {"data": notification_service.register_device(db, user.id, body)}


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_device(device_id: UUID, user: CurrentUser, db: DbSession):
    """로그아웃 전. 내 기기만"""
    with db.begin():
        notification_service.revoke_device(db, user.id, str(device_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
