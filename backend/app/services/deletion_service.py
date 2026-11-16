"""삭제 예약·실행 (A-SET-001 동의 철회, A-SET-003 탈퇴)

예약
- 필수 동의 철회 + "내 기록도 모두 지우기" → consent_withdrawal (내가 쓴 기록, 7일). 예정일 전 다시 동의 → cancelled
  안 고름 → 예약 X, 기록 유지
- 탈퇴 → account (즉시, 워커 작업 바로 등록): 로그인 계정 · 이름·전화번호 · 내 음성 파일
  delete_records → 내가 쓴 기록도 삭제 / 아니면 글은 가족 공간에 유지, 작성자 '탈퇴한 사용자'
  혼자 쓰던 부모님 공간 → 공간 삭제 (parent_deletion, 7일 유예)로 따로
  (예전 요청 parent_ids 있음 → 계정 실행 때 공간 삭제, 호환)
- 열린 요청 사람·종류당 1개 (DB unique index) → 다시 철회해도 기존 예약 그대로

실행 (워커 정리 작업, DELETION_EXECUTE_ENABLED일 때만)
1. 트랜잭션: 예정일 지난 요청 선점 → approved + 지울 음성 경로
2. 트랜잭션 밖: Storage 삭제 → (account) 카카오 연결 끊기 → Supabase 로그인 계정 삭제
   카카오 회원번호는 1에서 미리 (계정 삭제 뒤엔 연결 정보 없음)
3. 트랜잭션: DB 삭제 + completed
- 2·3 실패 → approved 유지 → 다음 실행에서 재시도 (없는 파일·계정 → 오류 아님)
- approved 뒤 다시 동의해도 취소 X (실행 확정)
- 동의 이력 유지 (동의 증거), 사용자 행 유지 (다른 가족 기록의 수정 이력·초대 기록 참조)

⚖️ 유예기간·삭제·보관 범위: 법률 상담 후 확정. 그전에는 운영에서 실행 꺼 둠
"""
import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import auth_admin, kakao_admin, storage
from app.repositories import deletion_repo, parent_deletion_repo, user_repo
from app.services import parent_deletion_service
from app.workers import queue


logger = logging.getLogger("silvercare.deletion")

# ⚖️ 법률 확인 전 임시 (기능명세서 예시 "7일 뒤"). 동의 철회 기록 삭제용
GRACE_DAYS = 7
# 탈퇴: 즉시
ACCOUNT_GRACE_DAYS = 0
RUN_JOB = "run_deletions"
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


def schedule_account(db: Session, user_id: str, delete_records: bool):
    """호출 전 사용자 행 잠금. 즉시 실행 예약 + 워커 작업
    동의 철회 예약 있음 → 취소 (탈퇴 때 고른 기록 처리로 대신)"""
    deletion_repo.cancel_requested(db, user_id, CONSENT_WITHDRAWAL, "탈퇴 요청으로 대체")
    request = deletion_repo.insert_request(
        db, user_id, ACCOUNT, ACCOUNT_GRACE_DAYS, delete_records=delete_records
    )
    enqueue_run(db)
    return request


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
            user_id = str(request["requester_id"])
            item = dict(request)
            if request["request_type"] == ACCOUNT:
                item["kakao_user_id"] = deletion_repo.kakao_user_id(db, user_id)
            claimed.append((item, deletion_repo.audio_paths(db, user_id, parent_ids)))

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


def enqueue_run(db: Session):
    """탈퇴 즉시 처리: 워커 작업 등록 (요청 트랜잭션 안). 실패·꺼짐 → 정리 주기에서 다시"""
    queue.enqueue(db, RUN_JOB, {})


def execute(db: Session, request: dict, paths: list[str]):
    user_id = str(request["requester_id"])

    for i in range(0, len(paths), STORAGE_CHUNK):
        storage.remove_objects(settings.STORAGE_AUDIO_BUCKET, paths[i:i + STORAGE_CHUNK])

    # 혼자 쓰던 공간: 폴더 전체 (DB 에 없는 고아 파일 포함)
    with db.begin():
        sole = deletion_repo.sole_parent_ids(db, user_id, parents_of(request))
    for parent_id in sole:
        parent_deletion_service.remove_space_files(parent_id, [])

    if request["request_type"] == ACCOUNT:
        if request.get("kakao_user_id"):
            kakao_admin.unlink(request["kakao_user_id"])
        auth_admin.delete_user(user_id)

    with db.begin():
        if not deletion_repo.lock_approved(db, str(request["id"])):
            return
        if request["delete_records"]:
            deletion_repo.delete_records_by(db, user_id)
        else:
            # 글은 유지, 음성 파일만 (위에서 지움)
            deletion_repo.mark_audio_deleted(db, user_id)
        if request["request_type"] == ACCOUNT:
            # 그사이 다른 가족 생김 → 남김 (다시 확인)
            for parent_id in deletion_repo.sole_parent_ids(db, user_id, parents_of(request)):
                parent_deletion_repo.delete_space(db, parent_id)
            deletion_repo.delete_account_data(db, user_id)
            user_repo.erase_profile(db, user_id)
        deletion_repo.mark_completed(db, str(request["id"]))
