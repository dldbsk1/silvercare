"""Idempotency-Key 처리 (API 명세서 0.5, 오프라인 재전송 중복 방지).

    status_code, body = run_idempotent(
        db, access.user_id, "POST /v1/parents/{parent_id}/records/text", key,
        request_body={"parent_id": access.parent_id, **body.model_dump(mode="json")},
        handler=lambda: (201, {"data": record_service.create_text(db, access, body)})
    )
    return JSONResponse(body, status_code=status_code)

- 같은 키 + 같은 요청: 처음 응답을 그대로 돌려준다 (새로 저장하지 않음)
- 같은 키 + 다른 요청: 409 IDEMPOTENCY_CONFLICT
- 처음 요청이 아직 처리 중: 409 IDEMPOTENCY_CONFLICT
- 처리 실패: 같은 키로 다시 시도할 수 있다

handler는 run_idempotent가 연 트랜잭션 안에서 실행된다 (handler 안에서 db.begin() 금지).
기록 저장과 "완료" 표시가 같이 커밋되므로, 저장됐는데 키만 처리 중으로 남는 일이 없다.
"""
import hashlib
import json
from collections.abc import Callable

from fastapi.encoders import jsonable_encoder
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import AppError


# 오프라인으로 며칠 뒤 재전송될 수 있어 넉넉하게 둔다
KEY_TTL = "7 days"
# 이 시간 넘게 processing이면 서버가 중간에 죽은 것으로 보고 다시 처리한다
PROCESSING_TIMEOUT = "5 minutes"

Handler = Callable[[], tuple[int, dict]]


def hash_request(request_body: dict) -> str:
    canonical = json.dumps(
        jsonable_encoder(request_body),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run_idempotent(
    db: Session,
    user_id: str,
    endpoint: str,
    key: str | None,
    request_body: dict,
    handler: Handler
) -> tuple[int, dict]:

    if key is None:
        with db.begin():
            status_code, body = handler()
        return status_code, jsonable_encoder(body)

    request_hash = hash_request(request_body)
    cached = claim_key(db, user_id, endpoint, key, request_hash)

    if cached is not None:
        return cached

    try:
        with db.begin():
            status_code, body = handler()
            body = jsonable_encoder(body)
            complete_key(db, user_id, endpoint, key, status_code, body)

    except Exception:
        with db.begin():
            fail_key(db, user_id, endpoint, key)
        raise

    return status_code, body


def claim_key(
    db: Session,
    user_id: str,
    endpoint: str,
    key: str,
    request_hash: str
) -> tuple[int, dict] | None:
    """이 요청을 처리할 권리를 얻으면 None, 이미 끝난 요청이면 저장된 응답"""
    params = {
        "user_id": user_id,
        "endpoint": endpoint,
        "key": key,
        "request_hash": request_hash
    }

    with db.begin():
        inserted = db.execute(
            text(f"""
                INSERT INTO idempotency_keys
                    (user_id, endpoint, key, request_hash, expires_at)
                VALUES
                    (:user_id, :endpoint, :key, :request_hash,
                     now() + interval '{KEY_TTL}')
                ON CONFLICT (user_id, endpoint, key) DO NOTHING
                RETURNING id
            """),
            params
        ).first()

        if inserted is not None:
            return None

        existing = db.execute(
            text(f"""
                SELECT request_hash, state, response_code, response_body,
                       expires_at <= now() AS expired,
                       created_at < now() - interval '{PROCESSING_TIMEOUT}'
                           AS stale
                FROM idempotency_keys
                WHERE user_id = :user_id AND endpoint = :endpoint
                  AND key = :key
                FOR UPDATE
            """),
            params
        ).mappings().one()

        if not existing["expired"]:
            if existing["request_hash"] != request_hash:
                raise AppError(
                    409, "IDEMPOTENCY_CONFLICT",
                    "같은 요청 키로 다른 내용이 전송됐어요."
                )

            if existing["state"] == "completed":
                return existing["response_code"], existing["response_body"]

            if existing["state"] == "processing" and not existing["stale"]:
                raise AppError(
                    409, "IDEMPOTENCY_CONFLICT", "같은 요청을 처리하고 있어요."
                )

        # 만료됐거나, 실패했거나, 처리 중에 멈춘 키 → 새로 처리
        db.execute(
            text(f"""
                UPDATE idempotency_keys
                SET request_hash = :request_hash,
                    state = 'processing',
                    response_code = NULL,
                    response_body = NULL,
                    created_at = now(),
                    expires_at = now() + interval '{KEY_TTL}'
                WHERE user_id = :user_id AND endpoint = :endpoint
                  AND key = :key
            """),
            params
        )

    return None


def complete_key(
    db: Session,
    user_id: str,
    endpoint: str,
    key: str,
    status_code: int,
    body: dict
):
    db.execute(
        text("""
            UPDATE idempotency_keys
            SET state = 'completed',
                response_code = :status_code,
                response_body = CAST(:body AS jsonb)
            WHERE user_id = :user_id AND endpoint = :endpoint AND key = :key
        """),
        {
            "user_id": user_id,
            "endpoint": endpoint,
            "key": key,
            "status_code": status_code,
            "body": json.dumps(body, ensure_ascii=False)
        }
    )


def fail_key(db: Session, user_id: str, endpoint: str, key: str):
    db.execute(
        text("""
            UPDATE idempotency_keys
            SET state = 'failed'
            WHERE user_id = :user_id AND endpoint = :endpoint AND key = :key
        """),
        {"user_id": user_id, "endpoint": endpoint, "key": key}
    )
