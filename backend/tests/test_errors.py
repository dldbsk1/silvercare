"""예상 못 한 오류·외부 서비스 장애도 공통 오류 형식으로 나가는지"""
import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from supabase_auth.errors import AuthApiError, AuthRetryableError

from app.core import security
from app.core.errors import register_exception_handlers
from app.db import storage


def build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def boom():
        raise RuntimeError("내부 정보")

    @app.get("/db-down")
    def db_down():
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    @app.get("/storage-down")
    def storage_down():
        with storage.storage_call("test"):
            raise httpx.ConnectError("unreachable")

    @app.get("/me")
    def me(user: security.AuthUser = Depends(security.get_auth_user)):
        return {"id": user.id}

    return app


@pytest.fixture
def client():
    # 실제 서버처럼 500 응답을 받기 위해 예외를 테스트로 다시 올리지 않는다
    return TestClient(build_app(), raise_server_exceptions=False)


def test_unexpected_error_hides_details(client):
    response = client.get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "내부 정보" not in response.text


def test_database_down_is_503(client):
    response = client.get("/db-down")

    assert response.status_code == 503
    assert response.json()["error"]["details"] == {"service": "database"}


def test_storage_down_is_503(client):
    response = client.get("/storage-down")

    assert response.status_code == 503
    assert response.json()["error"]["details"] == {"service": "storage"}


def raise_error(error):
    def get_user(token):
        raise error
    return get_user


def test_auth_server_down_is_503_not_logout(client, monkeypatch):
    monkeypatch.setattr(
        security.supabase.auth, "get_user",
        raise_error(AuthRetryableError("timeout", 503))
    )

    response = client.get("/me", headers={"Authorization": "Bearer x"})

    assert response.status_code == 503


def test_auth_network_error_is_503(client, monkeypatch):
    monkeypatch.setattr(
        security.supabase.auth, "get_user",
        raise_error(httpx.ConnectError("unreachable"))
    )

    response = client.get("/me", headers={"Authorization": "Bearer x"})

    assert response.status_code == 503


def test_invalid_token_is_401(client, monkeypatch):
    monkeypatch.setattr(
        security.supabase.auth, "get_user",
        raise_error(AuthApiError("invalid JWT", 403, "bad_jwt"))
    )

    response = client.get("/me", headers={"Authorization": "Bearer x"})

    assert response.status_code == 401
