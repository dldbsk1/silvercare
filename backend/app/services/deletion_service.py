"""삭제 예약·실행 (A-SET-001 동의 철회, A-SET-003 탈퇴)

예약
- 필수 동의 철회 → consent_withdrawal (내가 쓴 기록). 예정일 전 다시 동의 → cancelled
- 탈퇴 → account (내가 쓴 기록 + 혼자 쓰던 부모님 공간 + 계정)
- 열린 요청 사람·종류당 1개 (DB unique index) → 다시 철회해도 기존 예약 그대로

실행 (워커 정리 작업, DELETION_EXECUTE_ENABLED일 때만)
1. 트랜잭션: 예정일 지난 요청 선점 → approved + 지울 음성 경로
2. 트랜잭션 밖: Storage 삭제 → (account) Supabase 로그인 계정 삭제
3. 트랜잭션: DB 삭제 + completed
- 2·3 실패 → approved 유지 → 다음 실행에서 재시도 (없는 파일·계정 → 오류 아님)
- approved 뒤 다시 동의해도 취소 X (실행 확정)
- 동의 이력 유지 (동의 증거), 사용자 행 유지 (다른 가족 기록의 수정 이력·초대 기록 참조)

⚖️ 유예기간·삭제 범위: 법률 상담 후 확정. 그전에는 운영에서 실행 꺼 둠
"""
import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import auth_admin, storage
from app.repositories import deletion_repo, user_repo


logger = logging.getLogger("silvercare.deletion")

# ⚖️ 법률 확인 전 임시 (기능명세서 예시 "7일 뒤")
GRACE_DAYS = 7
BATCH_SIZE = 20
STORAGE_CHUNK = 100

CONSENT_WITHDRAWAL = "consent_withdrawal"
ACCOUNT = "account"


# ── 예약 ──

def schedule_consent_withdrawal(db: Session, user_id: str):
    """호출 전 사용자 행 잠금 (consent_repo.lock_user). 열린 요청 있음 → 그대로"""
    if deletion_repo.get_open(db, user_id, CONSENT_WITHDRAWAL) is None:
        deletion_repo.insert_request(db, user_id, CONSENT_WITHDRAWAL, GRACE_DAYS)


def cancel_consent_withdrawal(db: Session, user_id: str):
    deletion_repo.cancel_requested(db, user_id, CONSENT_WITHDRAWAL, "필수 동의 다시 함")


def consent_withdrawal_scheduled_for(db: Session, user_id: str):
    request = deletion_repo.get_open(db, user_id, CONSENT_WITHDRAWAL)
    return request["scheduled_for"] if request else None


def schedule_account(db: Session, user_id: str, sole_parent_ids: list[str]):
    """탈퇴. 철회 예약은 계정 삭제에 포함 → 취소"""
    deletion_repo.cancel_requested(db, user_id, CONSENT_WITHDRAWAL, "탈퇴 삭제에 포함")
    return deletion_repo.insert_request(db, user_id, ACCOUNT, GRACE_DAYS, sole_parent_ids)


def account_request(db: Session, user_id: str):
    return deletion_repo.get_latest(db, user_id, ACCOUNT)


# ── 실행 ──

def run(db: Session) -> int:
    """완료 건수. 설정 꺼짐 → 0"""
    if not settings.DELETION_EXECUTE_ENABLED:
        return 0

    with db.begin():
        claimed = []
        for request in deletion_repo.claim_due(db, (CONSENT_WITHDRAWAL, ACCOUNT), BATCH_SIZE):
            parent_ids = parents_of(request)
            claimed.append((
                dict(request),
                deletion_repo.audio_paths(db, str(request["requester_id"]), parent_ids),
            ))

    done = 0
    for request, paths in claimed:
        try:
            execute(db, request, paths)
            done += 1
        except Exception:
            logger.exception("삭제 실행 실패, 다음 실행에서 재시도 %s", request["id"])

    if done:
        logger.info("삭제 요청 처리 %d건", done)
    return done


def parents_of(request) -> list[str]:
    if request["request_type"] != ACCOUNT:
        return []
    return [str(p) for p in request["parent_ids"]]


def execute(db: Session, request: dict, paths: list[str]):
    user_id = str(request["requester_id"])

    for i in range(0, len(paths), STORAGE_CHUNK):
        storage.remove_objects(settings.STORAGE_AUDIO_BUCKET, paths[i:i + STORAGE_CHUNK])

    if request["request_type"] == ACCOUNT:
        auth_admin.delete_user(user_id)

    with db.begin():
        if not deletion_repo.lock_approved(db, str(request["id"])):
            return
        deletion_repo.delete_records_by(db, user_id)
        if request["request_type"] == ACCOUNT:
            deletion_repo.delete_sole_parents(db, user_id, parents_of(request))
            deletion_repo.delete_account_data(db, user_id)
            user_repo.erase_profile(db, user_id)
        deletion_repo.mark_completed(db, str(request["id"]))
