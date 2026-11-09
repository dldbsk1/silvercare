from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, StrictBool


class NotificationSettingsIn(BaseModel):
    """세 값 모두 필요 (전체 저장). true/false만 ("on"·1 X)"""

    condition_enabled: StrictBool
    tasks_enabled: StrictBool
    briefing_enabled: StrictBool

    model_config = {"extra": "forbid"}


class NotificationSettingsOut(NotificationSettingsIn):
    # 알림 동의(noti) 여부. 푸시 = 동의 + 해당 설정 켜짐
    noti_consented: bool


class DeviceIn(BaseModel):
    # 웹 푸시 X (앱만)
    platform: Literal["android", "ios"]
    push_token: str = Field(min_length=1, max_length=4096)

    model_config = {"extra": "forbid"}


class DeviceOut(BaseModel):
    device_id: str
    platform: str
    last_seen_at: datetime
