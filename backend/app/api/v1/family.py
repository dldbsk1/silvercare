from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from app.api.deps import AdminAccess, ConsentedUser, CurrentUser, DbSession, ReadAccess
from app.schemas.common import DataResponse
from app.schemas.family import (
    FamilyMemberOut,
    InviteAcceptedOut,
    InviteAcceptIn,
    InviteCreatedOut,
    InviteCreateIn,
    InviteOut,
    InvitePreviewOut,
    InviteTokenIn,
    RoleUpdateIn,
)
from app.services import family_service, rate_limit


router = APIRouter()


def limit_invite_requests(db, request: Request, user_id: str):
    """미리보기·수락 공통. 별도 트랜잭션 먼저 → 실패한 시도도 횟수에 남음"""
    with db.begin():
        rate_limit.hit(db, rate_limit.INVITE_PER_USER, user_id)
        rate_limit.hit(db, rate_limit.INVITE_PER_IP, rate_limit.client_ip(request))


# ── 초대 (관리자) ──

@router.post(
    "/parents/{parent_id}/invites",
    status_code=status.HTTP_201_CREATED,
    response_model=DataResponse[InviteCreatedOut]
)
def create_invite(parent_id: UUID, body: InviteCreateIn, access: AdminAccess, db: DbSession):
    """초대 링크 (A-FAM-001). 7일, 1회, 활성 10개까지. 토큰 원문은 이 응답에만"""
    with db.begin():
        return {"data": family_service.create_invite(db, access, body)}


@router.get("/parents/{parent_id}/invites", response_model=DataResponse[list[InviteOut]])
def list_invites(parent_id: UUID, access: AdminAccess, db: DbSession):
    """쓸 수 있는 초대 (수락·취소·만료 X). 취소 화면용"""
    with db.begin():
        return {"data": family_service.list_invites(db, access)}


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invite(invite_id: UUID, user: ConsentedUser, db: DbSession):
    with db.begin():
        family_service.revoke_invite(db, user.id, str(invite_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── 초대받은 사람 ──

@router.post("/invites/preview", response_model=DataResponse[InvitePreviewOut])
def preview_invite(body: InviteTokenIn, request: Request, user: CurrentUser, db: DbSession):
    """수락 전 확인. 로그인만 (동의 전에도 누가 초대했는지 확인 가능)"""
    limit_invite_requests(db, request, user.id)
    with db.begin():
        return {"data": family_service.preview(db, user.id, body.token)}


@router.post("/invites/accept", response_model=DataResponse[InviteAcceptedOut])
def accept_invite(body: InviteAcceptIn, request: Request, user: ConsentedUser, db: DbSession):
    """가족 추가 + 가족 공유 동의 기록. 같은 토큰 재요청 (지금도 가족) → 같은 결과"""
    limit_invite_requests(db, request, user.id)
    with db.begin():
        return {"data": family_service.accept(db, user.id, body)}


# ── 구성원 ──

@router.get("/parents/{parent_id}/family", response_model=DataResponse[list[FamilyMemberOut]])
def list_members(parent_id: UUID, access: ReadAccess, db: DbSession):
    with db.begin():
        return {"data": family_service.list_members(db, access)}


@router.patch("/family/{member_id}/role", response_model=DataResponse[FamilyMemberOut])
def change_role(member_id: UUID, body: RoleUpdateIn, user: ConsentedUser, db: DbSession):
    """관리자만 (A-FAM-002). 마지막 관리자 강등 → 409 LAST_ADMIN"""
    with db.begin():
        return {"data": family_service.change_role(db, user.id, str(member_id), body)}


@router.delete("/family/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(member_id: UUID, user: ConsentedUser, db: DbSession):
    """본인 → 나가기, 다른 사람 → 내보내기 (관리자). 작성 기록은 유지"""
    with db.begin():
        family_service.remove_member(db, user.id, str(member_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
