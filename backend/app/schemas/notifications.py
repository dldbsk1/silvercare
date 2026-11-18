from datetime import datetime

from pydantic import BaseModel, Field


class NotificationOut(BaseModel):
    notification_id: str
    # checklist_received · checklist_submitted · checklist_cancelled · checklist_overdue
    # survey_briefing · condition_reminder · family_joined · record_comment · record_failed
    type: str
    parent_id: str | None
    title: str
    body: str | None
    # 화면 이동용 (checklist_id · record_id 등)
    payload: dict
    created_at: datetime
    read_at: datetime | None


class NotificationListMeta(BaseModel):
    next_cursor: str | None = None
    has_more: bool = False
    # 안 읽은 알림 수 (나간 공간 알림 제외)
    unread_count: int = 0


class NotificationListResponse(BaseModel):
    data: list[NotificationOut]
    meta: NotificationListMeta = Field(default_factory=NotificationListMeta)


class NotificationListQuery(BaseModel):
    cursor: str | None = Field(default=None, max_length=512)
    limit: int = Field(default=20, ge=1, le=50)

    model_config = {"extra": "forbid"}
