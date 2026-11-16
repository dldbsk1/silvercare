from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.parents import FamilyRole


# 초대로 줄 수 있는 역할 (관리자는 가족이 된 뒤 역할 변경으로)
InviteRole = Literal["writer", "viewer"]

# 초대 코드 8자리 (XXXX-XXXX). 예전 43자 토큰도 받음
TOKEN_MAX_LENGTH = 100


# ── 초대 ──

class InviteCreateIn(BaseModel):
    role: InviteRole = "writer"
    # 부모님(또는 대리인)에게 가족 공유 동의 받았음 확인. true만
    share_confirmed: Literal[True]

    model_config = {"extra": "forbid"}


class InviteCreatedOut(BaseModel):
    invite_id: str
    # {INVITE_BASE_URL}#t={하이픈 뺀 코드}. 코드는 이 응답에서만 (DB엔 해시)
    invite_url: str
    # 초대 코드 XXXX-XXXX (베타: 링크 대신 이것만 공유)
    token: str
    role: InviteRole
    expires_at: datetime


class InviteOut(BaseModel):
    invite_id: str
    role: InviteRole
    invited_by: str
    inviter_name: str | None
    created_at: datetime
    expires_at: datetime


class InviteTokenIn(BaseModel):
    """초대 코드: URL 경로·쿼리 X, 본문으로만 (접속 기록 노출 방지). 대소문자·하이픈·공백 무시"""

    token: str = Field(min_length=1, max_length=TOKEN_MAX_LENGTH)

    model_config = {"extra": "forbid"}


class InviteAcceptIn(InviteTokenIn):
    # 미리보기에서 보여준 가족 공유 동의 문서 버전
    share_doc_version: str = Field(min_length=1, max_length=50)


class ShareDocumentOut(BaseModel):
    doc_version: str
    title: str
    content: str


class InvitePreviewOut(BaseModel):
    """수락 전 화면용. 부모님 연령대·조사일·기록 등 X"""

    inviter_name: str | None
    parent_nickname: str
    role: InviteRole
    expires_at: datetime
    already_member: bool
    share_document: ShareDocumentOut


class InviteAcceptedOut(BaseModel):
    parent_id: str
    role: FamilyRole


# ── 구성원 ──

class FamilyMemberOut(BaseModel):
    member_id: str
    user_id: str
    # 미설정 → null (앱: "가족")
    display_name: str | None
    role: FamilyRole
    joined_at: datetime
    is_me: bool


class RoleUpdateIn(BaseModel):
    role: FamilyRole

    model_config = {"extra": "forbid"}


class AdminTransferIn(BaseModel):
    # 넘긴 뒤 내 역할 (관리자 X)
    my_role: InviteRole = "writer"

    model_config = {"extra": "forbid"}
