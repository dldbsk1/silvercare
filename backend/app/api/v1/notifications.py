from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.common import DataResponse
from app.schemas.notifications import NotificationListQuery, NotificationListResponse, NotificationOut
from app.services import notification_service


# 로그인만 (동의 철회한 사용자도 지난 알림 확인 가능)
router = APIRouter()


@router.get("/notifications", response_model=NotificationListResponse)
def list_notifications(user: CurrentUser, db: DbSession, query: Annotated[NotificationListQuery, Query()]):
    """내 알림 (POP_A_NOTI). 최신순 커서, meta.unread_count"""
    with db.begin():
        return notification_service.list_notifications(db, user.id, query.limit, query.cursor)


@router.patch("/notifications/{notification_id}/read", response_model=DataResponse[NotificationOut])
def read_notification(notification_id: UUID, user: CurrentUser, db: DbSession):
    """읽음. 이미 읽음 → 그대로"""
    with db.begin():
        return {"data": notification_service.mark_read(db, user.id, str(notification_id))}


@router.post("/notifications/read-all", status_code=status.HTTP_204_NO_CONTENT)
def read_all_notifications(user: CurrentUser, db: DbSession):
    with db.begin():
        notification_service.mark_all_read(db, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
