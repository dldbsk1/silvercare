"""목록 커서 (페이지 넘기기). 앱: 내용 해석 X, 받은 그대로 돌려보냄

형식: base64url(JSON {"p": 위치, "f": 조건 해시}) + "." + base64url(HMAC-SHA256)
- 위치: 이전 페이지 마지막 항목의 정렬 키
- 조건 해시: HMAC(목록 범위 + 필터). 검색어 원문 X
- 서명 불일치 / 형식 오류 / 조건 변경 → 400 INVALID_CURSOR (앱: 첫 페이지부터 다시)
"""
import base64
import binascii
import hashlib
import hmac
import json

from app.core.config import settings
from app.core.errors import AppError


# local·test 전용 (staging·production: 설정 필수, config 검사)
DEV_CURSOR_SECRET = "silvercare-dev-cursor-secret"

SIGNATURE_BYTES = 16


def secret() -> bytes:
    return (settings.CURSOR_SECRET or DEV_CURSOR_SECRET).encode()


def sign(data: bytes) -> bytes:
    return hmac.new(secret(), data, hashlib.sha256).digest()


def b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def scope_hash(scope: dict) -> str:
    """같은 조건 → 같은 값. 값 정리(공백 제거 등)는 호출하는 쪽에서"""
    canonical = json.dumps(scope, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return b64encode(sign(b"scope:" + canonical.encode())[:SIGNATURE_BYTES])


def invalid_cursor() -> AppError:
    return AppError(
        400, "INVALID_CURSOR",
        "목록이 바뀌었어요. 처음부터 다시 불러와 주세요."
    )


def encode_cursor(position: list[str], scope: dict) -> str:
    payload = json.dumps(
        {"p": position, "f": scope_hash(scope)}, separators=(",", ":")
    ).encode()
    body = b64encode(payload)
    return f"{body}.{b64encode(sign(body.encode())[:SIGNATURE_BYTES])}"


def decode_cursor(cursor: str, scope: dict) -> list[str]:
    try:
        body, signature = cursor.split(".")
        expected = sign(body.encode())[:SIGNATURE_BYTES]
        if not hmac.compare_digest(b64decode(signature), expected):
            raise invalid_cursor()
        payload = json.loads(b64decode(body))
    except (ValueError, binascii.Error, UnicodeDecodeError):
        raise invalid_cursor()

    if not isinstance(payload, dict) or payload.get("f") != scope_hash(scope):
        raise invalid_cursor()

    position = payload.get("p")
    if not isinstance(position, list) or not all(isinstance(v, str) for v in position):
        raise invalid_cursor()
    return position
