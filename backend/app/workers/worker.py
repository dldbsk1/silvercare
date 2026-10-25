"""작업 워커. API 서버와 별도 프로세스로 실행한다.

    cd backend
    python -m app.workers.worker
"""
import logging
import time

from sqlalchemy import text

from app.db.session import new_session
from app.workers.tasks import TASKS, load_tasks


logger = logging.getLogger("silvercare.worker")

POLL_SECONDS = 1.0
# running 상태로 이 시간 넘게 멈춘 작업은 워커가 죽은 것으로 보고 다시 가져간다
STALE_MINUTES = 10


def claim_job(db):
    """실행할 작업 하나를 잠그고 running으로 바꾼다. 여러 워커가 동시에 돌아도 겹치지 않는다."""
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


def mark_completed(db, job_id):
    with db.begin():
        db.execute(
            text("""
                UPDATE jobs
                SET status = 'completed', completed_at = now(),
                    locked_at = NULL, last_error = NULL, updated_at = now()
                WHERE id = :id
            """),
            {"id": job_id}
        )


def mark_failed(db, job, error: str):
    """남은 시도가 있으면 잠시 뒤 다시 실행, 없으면 failed"""
    retry = job["attempts"] < job["max_attempts"]
    # 재시도 간격: 30초, 2분, 8분 ...
    delay_seconds = 30 * (4 ** (job["attempts"] - 1))

    with db.begin():
        db.execute(
            text("""
                UPDATE jobs
                SET status = :status,
                    run_at = CASE WHEN :retry
                        THEN now() + make_interval(secs => CAST(:delay AS double precision))
                        ELSE run_at END,
                    locked_at = NULL,
                    last_error = :error,
                    updated_at = now()
                WHERE id = :id
            """),
            {
                "id": job["id"],
                "status": "queued" if retry else "failed",
                "retry": retry,
                "delay": delay_seconds,
                "error": error[:2000]
            }
        )


def run_once() -> bool:
    """작업 하나를 처리했으면 True, 할 일이 없으면 False"""
    with new_session() as db:
        job = claim_job(db)

    if job is None:
        return False

    func = TASKS.get(job["type"])

    with new_session() as db:
        if func is None:
            mark_failed(db, {**job, "max_attempts": 0},
                        f"등록되지 않은 작업 종류: {job['type']}")
            return True

        try:
            func(db, job["payload"])
            # 작업 함수가 커밋하지 않은 변경은 버린다
            db.rollback()
            mark_completed(db, job["id"])
            logger.info("완료 %s %s", job["type"], job["id"])

        except Exception as e:
            db.rollback()
            logger.exception("실패 %s %s", job["type"], job["id"])
            mark_failed(db, job, f"{type(e).__name__}: {e}")

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
