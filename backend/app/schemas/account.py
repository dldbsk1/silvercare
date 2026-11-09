from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class TransferCandidateOut(BaseModel):
    member_id: str
    display_name: str | None
    role: str


class WithdrawalParentOut(BaseModel):
    parent_id: str
    nickname: str
    my_role: str
    # ok: 바로 나가기 / transfer_required: 관리자 넘길 사람 선택 / sole_member: 부모님 기록도 삭제 확인
    status: Literal["ok", "transfer_required", "sole_member"]
    # transfer_required일 때만
    candidates: list[TransferCandidateOut]


class WithdrawalCheckOut(BaseModel):
    parents: list[WithdrawalParentOut]


class AdminTransferIn(BaseModel):
    parent_id: UUID
    member_id: UUID

    model_config = {"extra": "forbid"}


class WithdrawalIn(BaseModel):
    confirm: Literal[True]
    admin_transfers: list[AdminTransferIn] = Field(default_factory=list, max_length=50)
    # sole_member 부모님 공간 삭제 확인
    delete_sole_parents: bool = False

    model_config = {"extra": "forbid"}


class WithdrawalOut(BaseModel):
    request_id: str
    status: str
    # 삭제 예정 시각. ⚖️ 유예기간 법률 확인 전 임시 7일
    scheduled_for: datetime
