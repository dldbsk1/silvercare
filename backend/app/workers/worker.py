"""작업 워커. API 서버와 별도 프로세스

    cd backend
    python -m app.workers.worker

작업 상태: completed / queued(재시도 대기) / failed(재시도 소진 → on_failure) / superseded(결과 버림)
"""
import logging
import time

from sqlalchemy import text

from app.db.session import new_session
from app.workers.tasks import TASKS, JobSuperseded, load_tasks


logger = logging.getLogger("silvercare.worker")

POLL_SECONDS = 1.0
STALE_MINUTES = 10


def claim_job(db):
    with db.begin():
        return db.execute(
            text(f"""
                UPDATE jobs
                SET status = 'running',
                    locked_at = now(),
                    attempts = attempts + 1,
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
                RETURNING id, type, payload, attempts, max_attempts
            """)
        ).mappings().first()


def finish_job(db, job_id, status: str, error: str | None = None):
    with db.begin():
        db.execute(
            text("""
                UPDATE jobs
                SET status = :status, completed_at = now(),
                    locked_at = NULL, last_error = :error, updated_at = now()
                WHERE id = :id
            """),
            {"id": job_id, "status": status, "error": error}
        )


def mark_failed(db, job, error: str) -> bool:
    """재시도 예약 → True / 시도 소진 → failed, False"""
    if job["attempts"] >= job["max_attempts"]:
        finish_job(db, job["id"], "failed", error[:2000])
        return False

    delay_seconds = 30 * (4 ** (job["attempts"] - 1))

    with db.begin():
        db.execute(
            text("""
                UPDATE jobs
                SET status = 'queued',
                    run_at = now() + make_interval(secs => CAST(:delay AS double precision)),
                    locked_at = NULL,
                    last_error = :error,
                    updated_at = now()
                WHERE id = :id
            """),
            {"id": job["id"], "delay": delay_seconds, "error": error[:2000]}
        )
    return True


def run_on_failure(task, job):
    if task.on_failure is None:
        return
    try:
        with new_session() as db:
            task.on_failure(db, job["payload"])
    except Exception:
        logger.exception("on_failure 실패 %s %s", job["type"], job["id"])


def run_once() -> bool:
    with new_session() as db:
        job = claim_job(db)

    if job is None:
        return False

    task = TASKS.get(job["type"])

    with new_session() as db:
        if task is None:
            finish_job(db, job["id"], "failed",
                       f"등록되지 않은 작업 종류: {job['type']}")
            return True

        try:
            task.func(db, job["payload"])
            db.rollback()
            finish_job(db, job["id"], "completed")
            logger.info("완료 %s %s", job["type"], job["id"])

        except JobSuperseded as e:
            db.rollback()
            finish_job(db, job["id"], "superseded", str(e) or None)
            logger.info("대체됨 %s %s", job["type"], job["id"])

        except Exception as e:
            db.rollback()
            logger.exception("실패 %s %s", job["type"], job["id"])
            if not mark_failed(db, job, f"{type(e).__name__}: {e}"):
                run_on_failure(task, job)

    return True


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    load_tasks()
    logger.info("워커 시작 (등록된 작업: %s)", sorted(TASKS) or "없음")

    try:
        while True:
            if not run_once():
                time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        logger.info("워커 종료")


if __name__ == "__main__":
    main()
