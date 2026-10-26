"""워커 상태 처리 (DB 없이): completed / superseded / 재시도 / failed + on_failure"""
import pytest

from app.workers import worker
from app.workers.tasks import TASKS, JobSuperseded, Task


class FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def rollback(self):
        pass


@pytest.fixture
def harness(monkeypatch):
    calls = {"finished": [], "retried": [], "on_failure": []}
    state = {"job": None}

    monkeypatch.setattr(worker, "new_session", lambda: FakeSession())
    monkeypatch.setattr(worker, "claim_job", lambda db: state["job"])
    monkeypatch.setattr(
        worker, "finish_job",
        lambda db, job_id, status, error=None: calls["finished"].append(status)
    )

    def fake_mark_failed(db, job, error):
        if job["attempts"] >= job["max_attempts"]:
            calls["finished"].append("failed")
            return False
        calls["retried"].append(job["attempts"])
        return True

    monkeypatch.setattr(worker, "mark_failed", fake_mark_failed)

    def run(func, attempts=1, max_attempts=3):
        TASKS["_test"] = Task(
            func=func,
            on_failure=lambda db, payload: calls["on_failure"].append(payload)
        )
        state["job"] = {
            "id": "job-1", "type": "_test", "payload": {"n": 1},
            "attempts": attempts, "max_attempts": max_attempts
        }
        try:
            worker.run_once()
        finally:
            TASKS.pop("_test", None)
        return calls

    return run


def ok(db, payload):
    pass


def superseded(db, payload):
    raise JobSuperseded("text_version 1 → 2")


def boom(db, payload):
    raise RuntimeError("AI down")


def test_success(harness):
    calls = harness(ok)

    assert calls["finished"] == ["completed"]


def test_superseded_no_retry_no_on_failure(harness):
    calls = harness(superseded)

    assert calls["finished"] == ["superseded"]
    assert calls["retried"] == [] and calls["on_failure"] == []


def test_failure_retries_without_on_failure(harness):
    calls = harness(boom, attempts=1)

    assert calls["retried"] == [1]
    assert calls["on_failure"] == []


def test_final_failure_runs_on_failure_once(harness):
    calls = harness(boom, attempts=3)

    assert calls["finished"] == ["failed"]
    assert calls["on_failure"] == [{"n": 1}]
