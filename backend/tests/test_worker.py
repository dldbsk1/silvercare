"""워커 상태 처리 (DB 없이): completed / superseded / 재시도 / failed / 영구 실패 / lease 잃음"""
import pytest

from app.workers import worker
from app.workers.tasks import TASKS, Job, JobSuperseded, LeaseLost, PermanentJobError, Task


class FakeSession:
    def rollback(self):
        pass


@pytest.fixture
def harness(monkeypatch):
    calls = {"finished": [], "retried": [], "failed": []}

    monkeypatch.setattr(
        worker, "finish_job",
        lambda db, job, status, error=None: calls["finished"].append(status) or True
    )
    monkeypatch.setattr(
        worker, "retry_job",
        lambda db, job, error: calls["retried"].append(job.attempts)
    )
    monkeypatch.setattr(
        worker, "fail_job",
        lambda db, task, job, code, error: calls["failed"].append(code)
    )

    def run(func, attempts=1, max_attempts=3):
        TASKS["_test"] = Task(func=func)
        job = Job(
            id="job-1", type="_test", payload={"n": 1}, lease_token="lease-1",
            attempts=attempts, max_attempts=max_attempts
        )
        try:
            worker.run_job(FakeSession(), job)
        finally:
            TASKS.pop("_test", None)
        return calls

    return run


def ok(db, job):
    pass


def superseded(db, job):
    raise JobSuperseded("text_version 1 → 2")


def boom(db, job):
    raise RuntimeError("AI down")


def broken_file(db, job):
    raise PermanentJobError("AUDIO_UNREADABLE")


def lease_lost(db, job):
    raise LeaseLost("회수됨")


def test_success(harness):
    assert harness(ok)["finished"] == ["completed"]


def test_superseded_no_retry_no_failure(harness):
    calls = harness(superseded)

    assert calls["finished"] == ["superseded"]
    assert calls["retried"] == [] and calls["failed"] == []


def test_failure_retries(harness):
    calls = harness(boom, attempts=1)

    assert calls["retried"] == [1]
    assert calls["failed"] == []


def test_final_failure_without_code(harness):
    calls = harness(boom, attempts=3)

    assert calls["failed"] == [None]
    assert calls["retried"] == []


def test_permanent_error_fails_immediately(harness):
    calls = harness(broken_file, attempts=1)

    assert calls["failed"] == ["AUDIO_UNREADABLE"]
    assert calls["retried"] == []


def test_lease_lost_changes_nothing(harness):
    calls = harness(lease_lost)

    assert calls == {"finished": [], "retried": [], "failed": []}


def test_reclaimed_after_last_attempt_fails_without_running(harness):
    ran = []
    calls = harness(lambda db, job: ran.append(1), attempts=4, max_attempts=3)

    assert ran == []
    assert calls["failed"] == [None]
