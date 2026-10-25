"""작업 등록·조회 (API 쪽에서 사용).

enqueue는 호출한 쪽의 트랜잭션 안에서 INSERT만 한다.
기록 저장과 작업 등록이 같이 커밋되므로 "저장은 됐는데 작업이 빠지는" 일이 없다.
"""
import json
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session


def enqueue(
    db: Session,
    job_type: str,
    payload: dict,
    target_type: str | None = None,
    target_id: str | None = None,
    run_at: datetime | None = None,
    max_attempts: int = 3
) -> str:
    return str(db.execute(
        text("""
            INSERT INTO jobs (
                type, payload, target_type, target_id,
                run_at, max_attempts
            )
            VALUES (
                :type, CAST(:payload AS jsonb), :target_type, :target_id,
                COALESCE(:run_at, now()), :max_attempts
            )
            RETURNING id
        """),
        {
            "type": job_type,
            "payload": json.dumps(payload),
            "target_type": target_type,
            "target_id": target_id,
            "run_at": run_at,
            "max_attempts": max_attempts
        }
    ).scalar_one())


def get_latest_job(db: Session, target_type: str, target_id: str):
    """리소스의 가장 최근 작업 (예: 기록지 생성 상태 조회)"""
    return db.execute(
        text("""
            SELECT id, type, status, attempts, max_attempts,
                   last_error, created_at, completed_at
            FROM jobs
            WHERE target_type = :target_type AND target_id = :target_id
            ORDER BY created_at DESC
            LIMIT 1
        """),
        {"target_type": target_type, "target_id": target_id}
    ).mappings().first()
