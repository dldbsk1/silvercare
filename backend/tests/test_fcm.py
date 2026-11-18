"""FCM 발송 결과 분류 · 메시지 모양 · 푸시 전달 (DB 없음)"""
import httpx
import pytest

from app.db import fcm
from app.services import notification_service
from app.services.notification_service import PushRetry, PushTarget


def response(status, error_code=None):
    body = {"error": {"details": [{"errorCode": error_code}]}} if error_code else {}
    return httpx.Response(status, json=body)


@pytest.mark.parametrize("status, code, expected", [
    (200, None, fcm.Result.SENT),
    (404, "UNREGISTERED", fcm.Result.INVALID),
    (400, "UNREGISTERED", fcm.Result.INVALID),
    (403, "SENDER_ID_MISMATCH", fcm.Result.INVALID),
    (429, "QUOTA_EXCEEDED", fcm.Result.RETRY),
    (503, "UNAVAILABLE", fcm.Result.RETRY),
    (401, None, fcm.Result.RETRY),
    (400, "INVALID_ARGUMENT", fcm.Result.REJECTED),
])
def test_classify(status, code, expected):
    assert fcm.classify(response(status, code)) == expected


def test_build_message():
    message = fcm.build_message("tok", "제목", None, {"type": "x"})["message"]
    assert message["token"] == "tok"
    assert message["notification"] == {"title": "제목"}
    assert message["data"] == {"type": "x"}
    assert message["android"] == {"priority": "high"}


def test_send_connection_error_retries(monkeypatch):
    monkeypatch.setattr(fcm.wake, "access_token", lambda: "t")

    def boom(*a, **kw):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(fcm.httpx, "post", boom)
    assert fcm.send("tok", "제목", None, {}) == fcm.Result.RETRY


def target(*tokens):
    return PushTarget("n1", "제목", None, {}, [(f"d-{t}", t) for t in tokens])


def test_deliver_partial_success(monkeypatch):
    results = {"a": fcm.Result.SENT, "b": fcm.Result.INVALID, "c": fcm.Result.RETRY}
    monkeypatch.setattr(fcm, "send", lambda token, *a: results[token])
    assert notification_service.deliver(target("a", "b", "c")) == (True, ["d-b"])


def test_deliver_all_retry(monkeypatch):
    monkeypatch.setattr(fcm, "send", lambda *a: fcm.Result.RETRY)
    with pytest.raises(PushRetry):
        notification_service.deliver(target("a"))


def test_deliver_all_invalid(monkeypatch):
    monkeypatch.setattr(fcm, "send", lambda *a: fcm.Result.INVALID)
    assert notification_service.deliver(target("a", "b")) == (False, ["d-a", "d-b"])


def test_push_data_strings():
    row = {"id": "n1", "type": "record_comment", "parent_id": "p1",
           "payload": {"record_id": "r1", "count": 3, "none": None}}
    assert notification_service.push_data(row) == {
        "notification_id": "n1", "type": "record_comment", "parent_id": "p1",
        "record_id": "r1", "count": "3",
    }


def test_comment_preview():
    from app.services.comment_service import preview
    assert preview("짧은\n댓글") == "짧은 댓글"
    assert preview("가" * 50) == "가" * 40 + "…"
