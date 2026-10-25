"""가족 권한 의존성 테스트 (DB 없이 가짜 저장소로)"""
from contextlib import nullcontext

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import AdminAccess, ReadAccess, WriteAccess
from app.core.errors import register_exception_handlers
from app.core.security import AuthUser, get_auth_user
from app.db.session import get_db
from app.core.errors import AppError
from app.repositories import family_repo, user_repo
from app.services import consent_service


USER_ID = "00000000-0000-0000-0000-000000000001"
PARENT_ID = "00000000-0000-0000-0000-0000000000aa"


class FakeSession:
    def begin(self):
        return nullcontext()


def build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/parents/{parent_id}/read")
    def read(parent_id: str, access: ReadAccess):
        return {"role": access.role}

    @app.post("/parents/{parent_id}/write")
    def write(parent_id: str, access: WriteAccess):
        return {"role": access.role}

    @app.post("/parents/{parent_id}/admin")
    def admin(parent_id: str, access: AdminAccess):
        return {"role": access.role}

    app.dependency_overrides[get_auth_user] = lambda: AuthUser(
        id=USER_ID, provider="email", phone=None
    )
    app.dependency_overrides[get_db] = lambda: FakeSession()
    return app


@pytest.fixture
def client(monkeypatch):
    created = []
    monkeypatch.setattr(
        user_repo, "ensure_user",
        lambda db, user_id, provider, phone: created.append(user_id)
    )
    monkeypatch.setattr(consent_service, "ensure_completed", lambda db, user_id: None)
    client = TestClient(build_app())
    client.created_users = created
    return client


def set_role(monkeypatch, role):
    monkeypatch.setattr(
        family_repo, "get_role",
        lambda db, parent_id, user_id: role
    )


@pytest.mark.parametrize("role, read, write, admin", [
    ("admin", 200, 200, 200),
    ("writer", 200, 200, 403),
    ("viewer", 200, 403, 403),
    (None, 404, 404, 404),
])
def test_role_rules(client, monkeypatch, role, read, write, admin):
    set_role(monkeypatch, role)

    assert client.get(f"/parents/{PARENT_ID}/read").status_code == read
    assert client.post(f"/parents/{PARENT_ID}/write").status_code == write
    assert client.post(f"/parents/{PARENT_ID}/admin").status_code == admin


def test_not_member_hides_parent(client, monkeypatch):
    set_role(monkeypatch, None)

    response = client.get(f"/parents/{PARENT_ID}/read")

    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_viewer_write_error_code(client, monkeypatch):
    set_role(monkeypatch, "viewer")

    response = client.post(f"/parents/{PARENT_ID}/write")

    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


def test_invalid_parent_id_is_validation_error(client, monkeypatch):
    set_role(monkeypatch, "admin")

    response = client.get("/parents/not-a-uuid/read")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_profile_is_ensured(client, monkeypatch):
    set_role(monkeypatch, "admin")

    client.get(f"/parents/{PARENT_ID}/read")

    assert client.created_users == [USER_ID]


def test_consent_required_before_parent_access(client, monkeypatch):
    set_role(monkeypatch, "admin")

    def not_consented(db, user_id):
        raise AppError(403, "CONSENT_REQUIRED", "필수 동의를 완료해 주세요.")

    monkeypatch.setattr(consent_service, "ensure_completed", not_consented)

    response = client.get(f"/parents/{PARENT_ID}/read")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CONSENT_REQUIRED"
