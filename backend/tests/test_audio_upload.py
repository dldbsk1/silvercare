"""음성 서명 업로드 URL API 테스트 (Storage·DB 없이)"""
from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient

from app.core.security import AuthUser, get_auth_user
from app.db import storage
from app.db.session import get_db
from app.main import app
from app.repositories import family_repo, user_repo
from app.services import consent_service
from app.services.idempotency import hash_request


USER_ID = "00000000-0000-0000-0000-000000000001"
PARENT_ID = "00000000-0000-0000-0000-0000000000aa"
URL = f"/v1/parents/{PARENT_ID}/records/audio/upload-url"


class FakeSession:
    def begin(self):
        return nullcontext()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(user_repo, "ensure_user", lambda *args: None)
    monkeypatch.setattr(consent_service, "ensure_completed", lambda *args: None)
    monkeypatch.setattr(
        storage, "create_signed_upload_url",
        lambda bucket, path: {
            "signed_url": f"https://storage.test/{bucket}/{path}?token=t",
            "token": "t",
            "path": path
        }
    )
    app.dependency_overrides[get_auth_user] = lambda: AuthUser(
        id=USER_ID, provider="email", phone=None
    )
    app.dependency_overrides[get_db] = lambda: FakeSession()
    yield TestClient(app)
    app.dependency_overrides.clear()


def set_role(monkeypatch, role):
    monkeypatch.setattr(family_repo, "get_role", lambda *args: role)


def test_writer_gets_upload_url(client, monkeypatch):
    set_role(monkeypatch, "writer")

    response = client.post(URL, json={"content_type": "audio/mp4"})

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["audio_path"].startswith(f"{PARENT_ID}/{USER_ID}/")
    assert data["audio_path"].endswith(".m4a")
    assert data["token"] == "t"


def test_viewer_cannot_upload(client, monkeypatch):
    set_role(monkeypatch, "viewer")

    response = client.post(URL, json={})

    assert response.status_code == 403


def test_unsupported_type(client, monkeypatch):
    set_role(monkeypatch, "writer")

    response = client.post(URL, json={"content_type": "video/mp4"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_FILE_TYPE"


def test_request_hash_ignores_key_order():
    assert hash_request({"a": 1, "b": 2}) == hash_request({"b": 2, "a": 1})
    assert hash_request({"a": 1}) != hash_request({"a": 2})
