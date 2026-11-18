"""워커 깨우기 (Cloud Run 배포용)

작업 큐 = DB jobs 그대로 (선점·재시도·실패 처리 변화 X). Cloud Tasks = "처리해" 신호만
- WORKER_WAKE=none (기본, 로컬): 아무것도 안 함 → 상시 워커 프로세스가 폴링
- WORKER_WAKE=cloud_tasks: enqueue 커밋 후 Cloud Tasks → 워커 서비스 POST /drain
- 롤백 → 안 깨움 (작업도 없으니)
- 신호 실패 → 로그만. 작업은 DB에 남아 있음 → Cloud Scheduler 주기 drain이 처리
"""
import logging
import threading
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.config import settings


logger = logging.getLogger("silvercare.wake")

FLAG = "wake_worker"
METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
)
TASKS_API = "https://cloudtasks.googleapis.com/v2"
# Cloud Tasks가 /drain 응답 기다리는 최대 시간 (워커 Cloud Run timeout과 맞춤)
DISPATCH_DEADLINE = "900s"
TIMEOUT_SECONDS = 3

_token = {"value": None, "expires": 0.0}
_token_lock = threading.Lock()


def enabled() -> bool:
    return settings.WORKER_WAKE == "cloud_tasks"


def request(db: Session):
    """enqueue 안에서 호출. 커밋 성공 후 1번 깨움"""
    if enabled():
        db.info[FLAG] = True


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session):
    if session.info.pop(FLAG, False):
        wake()


@event.listens_for(Session, "after_rollback")
def _after_rollback(session: Session):
    session.info.pop(FLAG, None)


def access_token() -> str:
    """Cloud Run 메타데이터 서버 → 실행 서비스 계정 토큰 (만료 1분 전까지 재사용)"""
    with _token_lock:
        if _token["value"] and time.monotonic() < _token["expires"] - 60:
            return _token["value"]
        response = httpx.get(
            METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"}, timeout=TIMEOUT_SECONDS
        )
        response.raise_for_status()
        data = response.json()
        _token["value"] = data["access_token"]
        _token["expires"] = time.monotonic() + data["expires_in"]
        return _token["value"]


def queue_path() -> str:
    return f"projects/{settings.GCP_PROJECT}/locations/{settings.GCP_LOCATION}/queues/{settings.TASKS_QUEUE}"


def build_task(at: datetime | None = None, name: str | None = None) -> dict:
    task = {
        "httpRequest": {
            "httpMethod": "POST",
            "url": f"{settings.WORKER_URL}/drain",
            # 워커 서비스 = 인증 필수 (Cloud Run IAM이 토큰 검증)
            "oidcToken": {
                "serviceAccountEmail": settings.TASKS_INVOKER_SA,
                "audience": settings.WORKER_URL,
            },
        },
        "dispatchDeadline": DISPATCH_DEADLINE,
    }
    if at is not None:
        task["scheduleTime"] = at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if name is not None:
        # 같은 이름 → Cloud Tasks가 중복 거절 (같은 시각 예약 1번만)
        task["name"] = f"{queue_path()}/tasks/{name}"
    return task


def wake(at: datetime | None = None, name: str | None = None):
    """워커 /drain 호출 예약. at 없음 → 바로"""
    if not enabled():
        return
    try:
        response = httpx.post(
            f"{TASKS_API}/{queue_path()}/tasks",
            json={"task": build_task(at, name)},
            headers={"Authorization": f"Bearer {access_token()}"},
            timeout=TIMEOUT_SECONDS,
        )
        if response.status_code == 409:
            return
        response.raise_for_status()
    except Exception:
        logger.exception("워커 깨우기 실패 (주기 drain이 처리)")
