"""카카오 연결 끊기 (실제 호출 X, httpx.post 교체)"""
import httpx
import pytest

from app.core.config import settings
from app.db import kakao_admin


@pytest.fixture
def sent(monkeypatch):
    """보낸 요청 기록 + 돌려줄 응답 (status, json)"""
    calls = []
    reply = {"status": 200, "json": {"id": 4012345678}}

    def fake_post(url, headers, data, timeout):
        calls.append({"url": url, "headers": headers, "data": data})
        return httpx.Response(reply["status"], json=reply["json"])

    monkeypatch.setattr(kakao_admin.httpx, "post", fake_post)
    monkeypatch.setattr(settings, "KAKAO_ADMIN_KEY", "admin-key")
    return calls, reply


def test_unlink_request(sent):
    calls, _ = sent
    kakao_admin.unlink("4012345678")

    assert calls == [{
        "url": "https://kapi.kakao.com/v1/user/unlink",
        "headers": {"Authorization": "KakaoAK admin-key"},
        "data": {"target_id_type": "user_id", "target_id": "4012345678"},
    }]


@pytest.mark.parametrize("code", [-101, -103])
def test_already_unlinked_is_ok(sent, code):
    _, reply = sent
    reply.update(status=400, json={"code": code, "msg": "not linked"})
    kakao_admin.unlink("4012345678")


@pytest.mark.parametrize("status, body", [(401, {"code": -401}), (500, {})])
def test_other_errors_raise(sent, status, body):
    _, reply = sent
    reply.update(status=status, json=body)
    with pytest.raises(kakao_admin.KakaoUnlinkError):
        kakao_admin.unlink("4012345678")


def test_no_admin_key_skips(sent, monkeypatch):
    calls, _ = sent
    monkeypatch.setattr(settings, "KAKAO_ADMIN_KEY", None)
    kakao_admin.unlink("4012345678")
    assert calls == []
