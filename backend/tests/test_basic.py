from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_auth_me_requires_token():
    response = client.get("/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_unknown_path_uses_error_format():
    response = client.get("/v1/not-found")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
