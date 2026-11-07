"""목록 커서 (DB 없이): 왕복 · 조건 변경 · 위조 · 서명 키"""
import base64
import json

import pytest

from app.core.config import settings
from app.core.errors import AppError
from app.services import pagination


SCOPE = {"parent_id": "p1", "q": "밥", "status": "normal"}
POSITION = ["2026-11-03T09:00:00+09:00", "00000000-0000-0000-0000-000000000001"]


def rejected(cursor, scope=SCOPE):
    with pytest.raises(AppError) as e:
        pagination.decode_cursor(cursor, scope)
    return e.value.code == "INVALID_CURSOR" and e.value.status_code == 400


def test_round_trip():
    cursor = pagination.encode_cursor(POSITION, SCOPE)

    assert pagination.decode_cursor(cursor, SCOPE) == POSITION
    # 키 순서 무관
    assert pagination.decode_cursor(cursor, dict(reversed(SCOPE.items()))) == POSITION


def test_no_search_text_in_cursor():
    body = pagination.encode_cursor(POSITION, SCOPE).split(".")[0]

    assert "밥" not in pagination.b64decode(body).decode()


@pytest.mark.parametrize("change", [
    {"q": "국"}, {"parent_id": "p2"}, {"status": "all"}, {"area": "physical"},
])
def test_scope_change_rejected(change):
    cursor = pagination.encode_cursor(POSITION, SCOPE)

    assert rejected(cursor, {**SCOPE, **change})


def test_forged_payload_rejected():
    cursor = pagination.encode_cursor(POSITION, SCOPE)
    _, signature = cursor.split(".")
    payload = json.loads(base64.urlsafe_b64decode(cursor.split(".")[0] + "=="))
    payload["p"][1] = "00000000-0000-0000-0000-000000000002"
    forged = pagination.b64encode(json.dumps(payload, separators=(",", ":")).encode())

    assert rejected(f"{forged}.{signature}")


@pytest.mark.parametrize("cursor", ["abc", "a.b.c", "!!!.???", "e30.AAAA"])
def test_garbage_rejected(cursor):
    assert rejected(cursor)


def test_other_secret_rejected(monkeypatch):
    cursor = pagination.encode_cursor(POSITION, SCOPE)
    monkeypatch.setattr(settings, "CURSOR_SECRET", "rotated")

    assert rejected(cursor)
