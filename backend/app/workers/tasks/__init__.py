"""작업 종류 등록소.

작업 함수는 (db, payload) 를 받는다. 같은 작업이 두 번 실행될 수 있으므로
(워커가 중간에 죽으면 다시 실행됨) 결과가 같도록 멱등하게 작성한다.

    @task("classify_record")
    def classify_record(db, payload): ...
"""
from collections.abc import Callable

from sqlalchemy.orm import Session


TaskFunc = Callable[[Session, dict], None]

TASKS: dict[str, TaskFunc] = {}


def task(name: str):
    def register(func: TaskFunc) -> TaskFunc:
        if name in TASKS:
            raise ValueError(f"이미 등록된 작업: {name}")
        TASKS[name] = func
        return func

    return register


def load_tasks():
    """작업 모듈을 import해서 TASKS에 등록시킨다. 새 모듈은 여기에 추가."""
    # 예: from app.workers.tasks import records, imports, reports  # noqa: F401
