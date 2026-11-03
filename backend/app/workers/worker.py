"""작업 워커. API 서버와 별도 프로세스

    cd backend
    python -m app.workers.worker

작업 상태: completed / queued(재시도 대기) / failed(재시도 소진·영구 실패 → on_failure) / superseded(결과 버림)

소유권 (lease)
- 가져올 때마다 lease_token 새로 발급 (멈춘 작업 회수 포함)
- 완료·재시도·실패 기록: lease 일치할 때만 → 회수당한 이전 워커는 아무것도 못 바꿈
- 최종 실패: 한 트랜잭션 (jobs 잠금 → failed → on_failure의 records 변경)
"""
import logging
import time

from sqlalchemy import text

from app.ai.provider import check_ai_config
from app.db.session import new_session
from app.services import upload_cleanup_service
from app.workers.tasks import (
    TASKS,
    Job,
    JobSuperseded,
    LeaseLost,
    PermanentJobError,
    Task,
    hold_lease,
    load_tasks,
)


logger = logging.getLogger("silvercare.worker")

POLL_SECONDS = 1.0
STALE_MINUTES = 10
CLEANUP_INTERVAL_SECONDS = 60 * 60


def claim_job(db) -> Job | None:
    with db.begin():
        row = db.execute(
            text(f"""
                UPDATE jobs
                SET status = 'running',
                    locked_at = now(),
                    attempts = attempts + 1,
                    lease_token = gen_random_uuid(),
                    updated_at = now()
                WHERE id = (
                    SELECT id FROM jobs
                    WHERE (status = 'queued' AND run_at <= now())
                       OR (status = 'running'
                           AND locked_at < now() - interval '{STALE_MINUTES} minutes')
                    ORDER BY run_at
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id, type, payload, lease_token, attempts, max_attempts
            """)
        ).mappings().first()

    return to_job(row) if row else None


def to_job(row) -> Job:
    return Job(
        id=str(row["id"]),
        type=row["type"],
        payload=row["payload"],
        lease_token=str(row["lease_token"]),
        attempts=row["attempts"],
        max_attempts=row["max_attempts"],
    )


def finish_job(db, job: Job, status: str, error: str | None = None) -> bool:
    """lease 일치할 때만. 불일치 → False"""
    with db.begin():
        updated = db.execute(
            text("""
                UPDATE jobs
                SET status = :status, completed_at = now(),
                    locked_at = NULL, last_error = :error, updated_at = now()
                WHERE id = :id AND lease_token = :lease AND status = 'running'
            """),
            {
                "id": job.id, "lease": job.lease_token,
                "status": status, "error": error[:2000] if error else None
            }
        ).rowcount
    if not updated:
        logger.warning("소유권 없음, %s 기록 안 함 %s %s", status, job.type, job.id)
    return bool(updated)


def retry_job(db, job: Job, error: str):
    """30초 → 2분 → 8분"""
    delay_seconds = 30 * (4 ** (job.attempts - 1))

    with db.begin():
        updated = db.execute(
            text("""
                UPDATE jobs
                SET status = 'queued',
                    run_at = now() + make_interval(secs => CAST(:delay AS double precision)),
                    locked_at = NULL,
                    last_error = :error,
                    updated_at = now()
                WHERE id = :id AND lease_token = :lease AND status = 'running'
            """),
            {
                "id": job.id, "lease": job.lease_token,
                "delay": delay_seconds, "error": error[:2000]
            }
        ).rowcount
    if not updated:
        logger.warning("소유권 없음, 재시도 예약 안 함 %s %s", job.type, job.id)


def fail_job(db, task: Task | None, job: Job, code: str | None, error: str):
    """최종 실패. jobs 잠금 → failed → on_failure (한 트랜잭션)

    on_failure 오류 → 작업만 failed (기록 상태는 그대로, 로그 확인)
    """
    try:
        with db.begin():
            hold_lease(db, job)
            set_failed(db, job, error)
            if task is not None and task.on_failure is not None:
                task.on_failure(db, job, code)
        return

    except LeaseLost:
        logger.warning("소유권 없음, 실패 처리 안 함 %s %s", job.type, job.id)
        return

    except Exception:
        db.rollback()
        logger.exception("on_failure 실패 %s %s", job.type, job.id)

    finish_job(db, job, "failed", f"{error} / on_failure 실패")


def set_failed(db, job: Job, error: str):
    db.execute(
        text("""
            UPDATE jobs
            SET status = 'failed', completed_at = now(),
                locked_at = NULL, last_error = :error, updated_at = now()
            WHERE id = :id
        """),
        {"id": job.id, "error": error[:2000]}
    )


def run_job(db, job: Job):
    task = TASKS.get(job.type)

    if task is None:
        finish_job(db, job, "failed", f"등록되지 않은 작업 종류: {job.type}")
        return

    # 마지막 시도 중 워커 중단 → 회수 → 실행 없이 실패 (무한 반복 방지)
    if job.attempts > job.max_attempts:
        fail_job(db, task, job, None, "시도 소진 (워커 중단 후 회수)")
        return

    try:
        task.func(db, job)
        db.rollback()
        if finish_job(db, job, "completed"):
            logger.info("완료 %s %s", job.type, job.id)

    except LeaseLost:
        db.rollback()
        logger.warning("소유권 없음, 결과 버림 %s %s", job.type, job.id)

    except JobSuperseded as e:
        db.rollback()
        finish_job(db, job, "superseded", str(e) or None)
        logger.info("대체됨 %s %s", job.type, job.id)

    except PermanentJobError as e:
        db.rollback()
        logger.warning("영구 실패 %s %s %s", job.type, job.id, e.code)
        fail_job(db, task, job, e.code, f"{e.code}: {e}")

    except Exception as e:
        db.rollback()
        logger.exception("실패 %s %s", job.type, job.id)
        error = f"{type(e).__name__}: {e}"
        if job.attempts >= job.max_attempts:
            fail_job(db, task, job, None, error)
        else:
            retry_job(db, job, error)


def run_once() -> bool:
    with new_session() as db:
        job = claim_job(db)

    if job is None:
        return False

    with new_session() as db:
        run_job(db, job)
    return True


def run_cleanup():
    try:
        with new_session() as db:
            upload_cleanup_service.run(db)
    except Exception:
        logger.exception("업로드 정리 실패")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    check_ai_config()
    load_tasks()
    logger.info("워커 시작 (등록된 작업: %s)", sorted(TASKS) or "없음")

    next_cleanup = 0.0
    try:
        while True:
            if time.monotonic() >= next_cleanup:
                run_cleanup()
                next_cleanup = time.monotonic() + CLEANUP_INTERVAL_SECONDS

            if not run_once():
                time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        logger.info("워커 종료")


if __name__ == "__main__":
    main()
