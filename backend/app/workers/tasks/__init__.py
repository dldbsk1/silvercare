"""작업 종류 등록소

- 작업 함수: (db, job). 트랜잭션은 작업 함수가 직접 시작 (with db.begin())
- 잠금 순서: jobs → records. 기록을 바꾸는 트랜잭션 첫 쿼리 = hold_lease(db, job)
- 중복 실행 가능 (워커 중단 후 회수) → 멱등하게 작성
- 결과 버림 (예: 글이 바뀜) → JobSuperseded → 작업 상태 superseded
- 재시도 무의미 (예: 파일 손상) → PermanentJobError(code) → 바로 failed
- on_failure(db, job, code): 최종 실패 시 1회. 워커의 실패 트랜잭션 안에서 실행 (db.begin 금지)
  code: PermanentJobError 코드 / None = 재시도 소진

    @task("classify_record", on_failure=mark_record_failed)
    def classify_record(db, job): ...
"""
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class Job:
    id: str
    type: str
    payload: dict
    lease_token: str
    attempts: int
    max_attempts: int


TaskFunc = Callable[[Session, Job], None]
FailureFunc = Callable[[Session, Job, str | None], None]


class JobSuperseded(Exception):
    """더 새로운 작업이 대신함 → 재시도·on_failure 없이 종료"""


class PermanentJobError(Exception):
    """재시도해도 같은 결과 → 재시도 없이 failed + on_failure(code)"""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


class LeaseLost(Exception):
    """다른 워커가 회수한 작업 → 아무것도 바꾸지 않고 종료"""


def hold_lease(db: Session, job: Job):
    """jobs 행 잠금 + 소유권 확인. 트랜잭션 첫 쿼리로 호출"""
    owned = db.execute(
        text("""
            SELECT 1 FROM jobs
            WHERE id = :id AND lease_token = :lease AND status = 'running'
            FOR UPDATE
        """),
        {"id": job.id, "lease": job.lease_token}
    ).first()
    if owned is None:
        raise LeaseLost(f"{job.type} {job.id}")


@dataclass(frozen=True)
class Task:
    func: TaskFunc
    on_failure: FailureFunc | None = None


TASKS: dict[str, Task] = {}


def task(name: str, on_failure: FailureFunc | None = None):
    def register(func: TaskFunc) -> TaskFunc:
        if name in TASKS:
            raise ValueError(f"이미 등록된 작업: {name}")
        TASKS[name] = Task(func=func, on_failure=on_failure)
        return func

    return register


def load_tasks():
    """작업 모듈 import → TASKS 등록. 새 모듈은 여기에 추가"""
    from app.workers.tasks import records  # noqa: F401
