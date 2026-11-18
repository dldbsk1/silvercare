"""워커 HTTP 진입점 (Cloud Run 워커 서비스). 로컬은 python -m app.workers.worker 그대로

    python -m app.workers.http   (PORT 환경 변수, 기본 8080)

- POST /drain: 대기 작업 없을 때까지 run_once 반복
    - 시간 예산 소진 → 멈추고 바로 다시 깨움 (Cloud Run 요청 시간 제한 전에 응답)
    - 끝나면 가까운 재시도 시각에 깨우기 예약 (30초 → 2분 → 8분)
- POST /cleanup: 정리 작업 (Cloud Scheduler 1시간마다, 기존 run_cleanup)
- POST /notify: 정기 알림 (Cloud Scheduler 매시 정각, 0 * * * * Asia/Seoul) → 푸시 작업 등록 → 커밋 후 깨움
- 인증: Cloud Run IAM (--no-allow-unauthenticated). 구글 OIDC 토큰 검증은 Cloud Run이 함
"""
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.ai.provider import check_ai_config
from app.db.session import new_session
from app.workers import wake, worker
from app.workers.tasks import TASKS, load_tasks


logger = logging.getLogger("silvercare.worker")

# Cloud Run timeout(900초)보다 짧게 → 실행 중 작업 끝낼 여유
DRAIN_BUDGET_SECONDS = 10 * 60
# 이 안의 재시도만 예약 (그 뒤는 주기 drain)
NEXT_WAKE_WINDOW_MINUTES = 15


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    check_ai_config()
    load_tasks()
    logger.info("워커 서비스 시작 (등록된 작업: %s)", sorted(TASKS) or "없음")
    yield


app = FastAPI(title="SilverCare Worker", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/drain")
def drain():
    started = time.monotonic()
    processed = 0
    while worker.run_once():
        processed += 1
        if time.monotonic() - started >= DRAIN_BUDGET_SECONDS:
            wake.wake()
            return {"processed": processed, "more": True}

    schedule_next_wake()
    return {"processed": processed, "more": False}


@app.post("/cleanup")
def cleanup():
    worker.run_cleanup()
    return {"status": "ok"}


@app.post("/notify")
def notify():
    return {"created": worker.run_notify()}


def next_run_at():
    with new_session() as db:
        return db.execute(
            text(f"""
                SELECT min(run_at) FROM jobs
                WHERE status = 'queued'
                  AND run_at > now()
                  AND run_at < now() + interval '{NEXT_WAKE_WINDOW_MINUTES} minutes'
            """)
        ).scalar()


def schedule_next_wake():
    at = next_run_at()
    if at is not None:
        wake.wake(at=at, name=f"retry-{int(at.timestamp())}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
