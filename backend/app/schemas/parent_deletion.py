from datetime import datetime
from typing import Literal

from pydantic import BaseModel


ParentDeletionStatus = Literal["pending", "scheduled", "executing"]


class ParentDeletionOut(BaseModel):
    """열린 공간 삭제 요청 (가족 누구나 조회)"""

    id: str
    # pending: 관리자 동의 대기 / scheduled: 유예 중 (읽기 전용) / executing: 삭제 중
    status: ParentDeletionStatus
    requested_by: str
    requested_by_name: str | None
    requested_at: datetime
    # pending 일 때 동의 기한 (지나면 요청 사라짐)
    approval_deadline: datetime
    # scheduled 부터. 이 시각 뒤 삭제
    scheduled_for: datetime | None
    admins_total: int
    admins_approved: int
    approved_by_me: bool
