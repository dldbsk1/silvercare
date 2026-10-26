"""작업 종류 등록소

- 작업 함수: (db, payload). 트랜잭션은 작업 함수가 직접 시작 (with db.begin())
- 중복 실행 가능 (워커 중단 후 재실행) → 멱등하게 작성
- 결과를 버려야 할 때 (예: 글이 바뀜) → JobSuperseded 발생 → 작업 상태 superseded
- on_failure: 재시도까지 모두 실패했을 때 1회 실행 (예: 기록 processing_status=failed)

    @task("classify_record", on_failure=mark_record_failed)
    def classify_record(db, payload): ...
"""
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session


TaskFunc = Callable[[Session, dict], None]


class JobSuperseded(Exception):
    """더 새로운 작업이 대신함 → 재시도·on_failure 없이 종료"""


@dataclass(frozen=True)
class Task:
    func: TaskFunc
    on_failure: TaskFunc | None = None


TASKS: dict[str, Task] = {}


def task(name: str, on_failure: TaskFunc | None = None):
    def register(func: TaskFunc) -> TaskFunc:
        if name in TASKS:
            raise ValueError(f"이미 등록된 작업: {name}")
        TASKS[name] = Task(func=func, on_failure=on_failure)
        return func

    return register


def load_tasks():
    """작업 모듈 import → TASKS 등록. 새 모듈은 여기에 추가"""
    from app.workers.tasks import records  # noqa: F401
