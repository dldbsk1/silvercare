"""부모님 기록 공간 삭제 (가족 자발적 삭제, 내 정보 탭)

요청·동의
- 관리자 요청 → pending. 관리자 전원 동의 (요청자 포함) → scheduled
- 관리자 1명 → 요청 즉시 scheduled
- 동의 기한 APPROVAL_DAYS 지남 → expired (다시 요청 가능)
- 열린 요청 (pending·scheduled) 동안 가족 구성 변경 X (관리자 집합 고정 → 전원 동의 판정 안정)
  초대 생성·수락·역할 변경·내보내기·나가기·관리자 넘기기 → 409 PARENT_DELETION_PENDING
- 요청 시 쓸 수 있는 초대 전부 취소

유예 (scheduled)
- 읽기 전용: 기록 작성·수정·분류·부모님 정보 수정 → 409 PARENT_DELETION_SCHEDULED
- 관리자 누구나 취소 → cancelled, 원래대로
- AI 작업: 대기 중 작업은 워커가 꺼내지 않음 (취소되면 이어서 처리) / 실행 중 작업은 끝까지

실행 (워커 정리 작업, DELETION_EXECUTE_ENABLED 일 때만)
1. 트랜잭션: 예정일 지난 요청 선점 → executing. 실행 중 AI 작업 있으면 다음 차례로
2. 트랜잭션 밖: Storage 삭제 (DB 경로 + 공간 폴더 전체 → 고아 파일 포함)
3. 트랜잭션: DB 삭제 (parent_deletion_repo.delete_space) + completed
- 2·3 실패 → executing 유지 → 다음 실행에서 재시도 (없는 파일 → 오류 아님)

⚖️ 유예 7일: 법률 자문 후 확정 (즉시 삭제 포함)
동의 철회·부모님 본인 삭제 요구 → 유예 없는 별도 경로 (여기 X)
"""
import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.db import storage
from app.repositories import family_repo, invite_repo, user_repo
from app.repositories import parent_deletion_repo as repo


logger = logging.getLogger("silvercare.parent_deletion")

# ⚖️ 법률 자문 전 임시
GRACE_DAYS = 7
# 다른 관리자 동의 기다리는 기간
APPROVAL_DAYS = 7
BATCH_SIZE = 5
# 워커 회수 기준 (worker.STALE_MINUTES 와 같게). 이보다 오래 멈춘 작업 → 기다리지 않음
JOB_STALE_MINUTES = 10
STORAGE_CHUNK = 100


def pending_error() -> AppError:
    return AppError(409, "PARENT_DELETION_PENDING", "공간 삭제 요청 중에는 가족을 바꿀 수 없어요.")


def scheduled_error() -> AppError:
    return AppError(409, "PARENT_DELETION_SCHEDULED", "삭제 예정인 공간이라 바꿀 수 없어요.")


# ── 다른 기능에서 쓰는 검사 ──

def ensure_writable(db: Session, parent_id: str):
    """데이터 쓰기 (기록·부모님 정보). scheduled·executing → 409"""
    if repo.get_open_status(db, parent_id) in ("scheduled", "executing"):
        raise scheduled_error()


def ensure_family_changeable(db: Session, parent_id: str):
    """가족 구성 변경. 열린 요청 → 409 (부모님 행 잠근 뒤 호출)"""
    status = repo.get_open_status(db, parent_id)
    if status in ("scheduled", "executing"):
        raise scheduled_error()
    if status == "pending":
        raise pending_error()


# ── 조회 ──

def to_out(db: Session, request, user_id: str) -> dict:
    admins = repo.admin_ids(db, str(request["target_parent_id"]))
    approved = set(repo.approver_ids(db, str(request["id"])))
    return {
        "id": str(request["id"]),
        "status": request["status"],
        "requested_by": str(request["requested_by"]),
        "requested_by_name": (user_repo.get_user(db, str(request["requested_by"])) or {}).get("display_name"),
        "requested_at": request["requested_at"],
        "approval_deadline": request["approval_deadline"],
        "scheduled_for": request["scheduled_for"],
        "admins_total": len(admins),
        "admins_approved": len([a for a in admins if a in approved]),
        "approved_by_me": user_id in approved,
    }


def get_status(db: Session, user_id: str, parent_id: str) -> dict | None:
    """열린 요청. 없음 → None (가족 누구나 조회)"""
    repo.expire_overdue(db, parent_id)
    request = repo.get_open(db, parent_id)
    return to_out(db, request, user_id) if request else None


# ── 요청 · 동의 · 취소 (관리자) ──

def lock_as_admin(db: Session, parent_id: str, user_id: str):
    if not family_repo.lock_parent(db, parent_id):
        raise AppError(404, "NOT_FOUND", "부모님 정보를 찾을 수 없어요.")
    role = family_repo.get_role(db, parent_id, user_id)
    if role is None:
        raise AppError(404, "NOT_FOUND", "부모님 정보를 찾을 수 없어요.")
    if role != "admin":
        raise AppError(403, "PERMISSION_DENIED", "관리자만 할 수 있어요.")


def schedule_if_all_approved(db: Session, request) -> None:
    admins = set(repo.admin_ids(db, str(request["target_parent_id"])))
    if admins <= set(repo.approver_ids(db, str(request["id"]))):
        repo.mark_scheduled(db, str(request["id"]), GRACE_DAYS)


def request_deletion(db: Session, user_id: str, parent_id: str) -> dict:
    lock_as_admin(db, parent_id, user_id)
    repo.expire_overdue(db, parent_id)
    if repo.get_open(db, parent_id) is not None:
        raise AppError(409, "PARENT_DELETION_EXISTS", "이미 삭제 요청이 있어요.")

    request = repo.insert(db, parent_id, user_id, APPROVAL_DAYS)
    repo.add_approval(db, str(request["id"]), user_id)
    invite_repo.revoke_all(db, parent_id)
    schedule_if_all_approved(db, request)
    return to_out(db, repo.get_open(db, parent_id), user_id)


def approve(db: Session, user_id: str, parent_id: str) -> dict:
    lock_as_admin(db, parent_id, user_id)
    repo.expire_overdue(db, parent_id)
    request = repo.get_open(db, parent_id, for_update=True)
    if request is None or request["status"] != "pending":
        raise AppError(409, "PARENT_DELETION_NOT_PENDING", "동의를 기다리는 삭제 요청이 없어요.")

    repo.add_approval(db, str(request["id"]), user_id)
    schedule_if_all_approved(db, request)
    return to_out(db, repo.get_open(db, parent_id), user_id)


def cancel(db: Session, user_id: str, parent_id: str):
    """pending·scheduled → 관리자 누구나 취소 (동의 거절 포함). executing → 409"""
    lock_as_admin(db, parent_id, user_id)
    request = repo.get_open(db, parent_id, for_update=True)
    if request is None:
        raise AppError(409, "PARENT_DELETION_NOT_FOUND", "취소할 삭제 요청이 없어요.")
    if request["status"] == "executing":
        raise AppError(409, "PARENT_DELETION_EXECUTING", "이미 삭제를 진행하고 있어요.")
    repo.mark_cancelled(db, str(request["id"]), user_id)


# ── 실행 (워커) ──

def run(db: Session) -> int:
    """예정일 지난 공간 삭제. 처리 건수"""
    if not settings.DELETION_EXECUTE_ENABLED:
        return 0

    with db.begin():
        claimed = repo.claim_due(db, BATCH_SIZE)

    done = 0
    for request in claimed:
        parent_id = str(request["target_parent_id"])
        try:
            with db.begin():
                if repo.running_job_count(db, parent_id, JOB_STALE_MINUTES) > 0:
                    logger.info("AI 작업 실행 중, 다음 차례 %s", request["id"])
                    continue
                paths = repo.audio_paths(db, parent_id)
            execute(db, request, paths)
            done += 1
        except Exception:
            db.rollback()
            logger.exception("공간 삭제 실패, 다음 실행에서 재시도 %s", request["id"])
    return done


def execute(db: Session, request, db_paths: list[str]):
    parent_id = str(request["target_parent_id"])
    removed = remove_space_files(parent_id, db_paths)

    with db.begin():
        if not repo.lock_executing(db, str(request["id"])):
            return
        counts = repo.delete_space(db, parent_id)
        counts["files"] = removed
        repo.mark_completed(db, str(request["id"]), counts)
    logger.info("공간 삭제 완료 %s %s", request["id"], counts)


def remove_space_files(parent_id: str, db_paths: list[str]) -> int:
    """공간 파일 전부: DB 경로 + Storage 폴더 {parent_id}/ 아래 (DB 에 없는 고아 파일 포함)
    탈퇴 삭제(혼자 쓰던 공간)도 사용. 지운 파일 수"""
    removed = 0
    for bucket in (settings.STORAGE_AUDIO_BUCKET, settings.STORAGE_IMPORT_BUCKET):
        paths = set(storage.list_files(bucket, parent_id))
        if bucket == settings.STORAGE_AUDIO_BUCKET:
            paths |= set(db_paths)
        paths = sorted(paths)
        for i in range(0, len(paths), STORAGE_CHUNK):
            storage.remove_objects(bucket, paths[i:i + STORAGE_CHUNK])
        removed += len(paths)
    return removed
