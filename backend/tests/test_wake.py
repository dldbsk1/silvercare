"""워커 깨우기 (DB·네트워크 없이): 커밋 후 1번 / 롤백 → X / 꺼짐 → X / Cloud Tasks 요청 모양 / drain"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.workers import http, wake


@pytest.fixture
def cloud_tasks(monkeypatch):
    monkeypatch.setattr(settings, "WORKER_WAKE", "cloud_tasks")
    monkeypatch.setattr(settings, "GCP_PROJECT", "proj")
    monkeypatch.setattr(settings, "GCP_LOCATION", "asia-northeast1")
    monkeypatch.setattr(settings, "TASKS_QUEUE", "worker-wake")
    monkeypatch.setattr(settings, "WORKER_URL", "https://worker.example")
    monkeypatch.setattr(settings, "TASKS_INVOKER_SA", "invoker@proj.iam.gserviceaccount.com")


@pytest.fixture
def woken(monkeypatch):
    calls = []
    monkeypatch.setattr(wake, "wake", lambda at=None, name=None: calls.append((at, name)))
    return calls


@pytest.fixture
def db():
    with Session(create_engine("sqlite://")) as session:
        yield session


def test_wake_after_commit_once(cloud_tasks, woken, db):
    with db.begin():
        wake.request(db)
        wake.request(db)
    assert woken == [(None, None)]

    # 다음 트랜잭션: 작업 등록 없음 → 안 깨움
    with db.begin():
        pass
    assert len(woken) == 1


def test_no_wake_on_rollback(cloud_tasks, woken, db):
    with pytest.raises(RuntimeError):
        with db.begin():
            wake.request(db)
            raise RuntimeError
    with db.begin():
        pass
    assert woken == []


def test_no_wake_when_disabled(monkeypatch, woken, db):
    monkeypatch.setattr(settings, "WORKER_WAKE", "none")
    with db.begin():
        wake.request(db)
    assert woken == []


def test_build_task(cloud_tasks):
    at = datetime(2026, 11, 18, 3, 0, 30, tzinfo=timezone.utc)
    task = wake.build_task(at, "retry-1")
    assert task["httpRequest"]["url"] == "https://worker.example/drain"
    assert task["httpRequest"]["oidcToken"] == {
        "serviceAccountEmail": "invoker@proj.iam.gserviceaccount.com",
        "audience": "https://worker.example",
    }
    assert task["scheduleTime"] == "2026-11-18T03:00:30.000000Z"
    assert task["name"] == "projects/proj/locations/asia-northeast1/queues/worker-wake/tasks/retry-1"


def test_wake_failure_is_swallowed(cloud_tasks, monkeypatch):
    def boom():
        raise OSError("metadata server 없음")
    monkeypatch.setattr(wake, "access_token", boom)
    wake.wake()  # 예외 X (로그만)


@pytest.fixture
def worker_client(monkeypatch):
    monkeypatch.setattr(http, "check_ai_config", lambda: None)
    monkeypatch.setattr(http, "load_tasks", lambda: None)
    with TestClient(http.app) as client:
        yield client


def test_drain_until_empty(monkeypatch, worker_client, woken):
    jobs = [True, True, False]
    monkeypatch.setattr(http.worker, "run_once", lambda: jobs.pop(0))
    at = datetime(2026, 11, 18, 3, 2, tzinfo=timezone.utc)
    monkeypatch.setattr(http, "next_run_at", lambda: at)

    response = worker_client.post("/drain")
    assert response.json() == {"processed": 2, "more": False}
    assert woken == [(at, f"retry-{int(at.timestamp())}")]


def test_drain_budget_exceeded(monkeypatch, worker_client, woken):
    monkeypatch.setattr(http, "DRAIN_BUDGET_SECONDS", 0)
    monkeypatch.setattr(http.worker, "run_once", lambda: True)

    response = worker_client.post("/drain")
    assert response.json() == {"processed": 1, "more": True}
    assert woken == [(None, None)]


def test_cleanup(monkeypatch, worker_client):
    ran = []
    monkeypatch.setattr(http.worker, "run_cleanup", lambda: ran.append(1))
    assert worker_client.post("/cleanup").status_code == 200
    assert ran == [1]
