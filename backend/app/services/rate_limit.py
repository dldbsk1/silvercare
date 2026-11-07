"""요청 횟수 제한 (고정 구간, DB 카운터 → 서버 여러 대 공유)

- 호출하는 쪽: 본 작업과 별도 트랜잭션에서 먼저 (실패한 요청도 횟수에 남게)
- 초과 → 429 RATE_LIMITED + Retry-After 헤더 (details에도 초)
- 지난 구간 삭제: 워커 정리 작업
"""
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError


@dataclass(frozen=True)
class Limit:
    name: str
    max_count: int
    window_seconds: int


# 초대 미리보기 + 수락 합산
INVITE_PER_USER = Limit("invite:user", 20, 600)
INVITE_PER_IP = Limit("invite:ip", 60, 600)

KEEP_SECONDS = 24 * 60 * 60


def client_ip(request: Request) -> str:
    """프록시 뒤: X-Forwarded-For 오른쪽에서 TRUSTED_PROXY_HOPS번째. 미설정 → 직접 연결 주소"""
    hops = settings.TRUSTED_PROXY_HOPS
    forwarded = request.headers.get("x-forwarded-for")
    if hops > 0 and forwarded:
        entries = [e.strip() for e in forwarded.split(",") if e.strip()]
        if len(entries) >= hops:
            return entries[-hops]
    return request.client.host if request.client else "unknown"


def hit(db: Session, limit: Limit, subject: str):
    row = db.execute(
        text("""
            INSERT INTO rate_limits (key, window_start)
            VALUES (:key, date_bin(make_interval(secs => :w), now(), timestamptz 'epoch'))
            ON CONFLICT (key, window_start)
                DO UPDATE SET count = rate_limits.count + 1
            RETURNING count,
                      ceil(extract(epoch FROM
                          window_start + make_interval(secs => :w) - now()))::int AS retry_after
        """),
        {"key": f"{limit.name}:{subject}", "w": limit.window_seconds}
    ).one()

    if row.count > limit.max_count:
        retry_after = max(row.retry_after, 1)
        raise AppError(
            429, "RATE_LIMITED", "요청이 너무 많아요. 잠시 후 다시 시도해 주세요.",
            details={"retry_after_seconds": retry_after},
            headers={"Retry-After": str(retry_after)}
        )


def cleanup(db: Session) -> int:
    return db.execute(
        text("DELETE FROM rate_limits WHERE window_start < now() - make_interval(secs => :s)"),
        {"s": KEEP_SECONDS}
    ).rowcount
