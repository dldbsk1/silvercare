import json

from sqlalchemy import text
from sqlalchemy.orm import Session


COLUMNS = """
    id, target_parent_id, requested_by, status, requested_at, approval_deadline,
    scheduled_at, scheduled_for, cancelled_by, cancelled_at, completed_at
"""

# 열린 요청 (unique index parent_deletions_open 과 같은 조건)
OPEN = "status IN ('pending', 'scheduled', 'executing')"

# 읽기 전용 (데이터 쓰기 X)
LOCKED = "status IN ('scheduled', 'executing')"


def get_open(db: Session, parent_id: str, for_update: bool = False):
    return db.execute(
        text(f"""
            SELECT {COLUMNS} FROM parent_deletions
            WHERE target_parent_id = :p AND {OPEN}
            {"FOR UPDATE" if for_update else ""}
        """),
        {"p": parent_id}
    ).mappings().first()


def get_open_status(db: Session, parent_id: str) -> str | None:
    """권한 검사용 (기한 지난 pending 은 없는 것으로)"""
    return db.execute(
        text(f"""
            SELECT status FROM parent_deletions
            WHERE target_parent_id = :p AND {OPEN}
              AND NOT (status = 'pending' AND approval_deadline <= now())
        """),
        {"p": parent_id}
    ).scalar()


def expire_overdue(db: Session, parent_id: str) -> int:
    return db.execute(
        text("""
            UPDATE parent_deletions SET status = 'expired'
            WHERE target_parent_id = :p AND status = 'pending' AND approval_deadline <= now()
        """),
        {"p": parent_id}
    ).rowcount


def insert(db: Session, parent_id: str, user_id: str, approval_days: int):
    return db.execute(
        text(f"""
            INSERT INTO parent_deletions
                (target_parent_id, parent_id, requested_by, approval_deadline)
            VALUES (:p, :p, :u, now() + make_interval(days => :days))
            RETURNING {COLUMNS}
        """),
        {"p": parent_id, "u": user_id, "days": approval_days}
    ).mappings().one()


def add_approval(db: Session, deletion_id: str, user_id: str):
    db.execute(
        text("""
            INSERT INTO parent_deletion_approvals (deletion_id, user_id)
            VALUES (:d, :u) ON CONFLICT DO NOTHING
        """),
        {"d": deletion_id, "u": user_id}
    )


def approver_ids(db: Session, deletion_id: str) -> list[str]:
    return [str(u) for u in db.execute(
        text("SELECT user_id FROM parent_deletion_approvals WHERE deletion_id = :d"),
        {"d": deletion_id}
    ).scalars()]


def admin_ids(db: Session, parent_id: str) -> list[str]:
    return [str(u) for u in db.execute(
        text("SELECT user_id FROM family_members WHERE parent_id = :p AND role = 'admin'"),
        {"p": parent_id}
    ).scalars()]


def mark_scheduled(db: Session, deletion_id: str, grace_days: int):
    db.execute(
        text("""
            UPDATE parent_deletions
            SET status = 'scheduled', scheduled_at = now(),
                scheduled_for = now() + make_interval(days => :days)
            WHERE id = :d
        """),
        {"d": deletion_id, "days": grace_days}
    )


def mark_cancelled(db: Session, deletion_id: str, user_id: str):
    db.execute(
        text("""
            UPDATE parent_deletions
            SET status = 'cancelled', cancelled_by = :u, cancelled_at = now()
            WHERE id = :d
        """),
        {"d": deletion_id, "u": user_id}
    )


# ── 실행 (워커) ──

def claim_due(db: Session, limit: int):
    """예정일 지난 scheduled → executing. 지난번 미완료 executing 도 다시"""
    return db.execute(
        text(f"""
            UPDATE parent_deletions SET status = 'executing'
            WHERE id IN (
                SELECT id FROM parent_deletions
                WHERE {LOCKED} AND scheduled_for <= now()
                ORDER BY scheduled_for, id
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
            )
            RETURNING {COLUMNS}
        """),
        {"limit": limit}
    ).mappings().all()


def lock_executing(db: Session, deletion_id: str) -> bool:
    return db.execute(
        text("SELECT 1 FROM parent_deletions WHERE id = :d AND status = 'executing' FOR UPDATE"),
        {"d": deletion_id}
    ).first() is not None


def running_job_count(db: Session, parent_id: str, stale_minutes: int) -> int:
    """실행 중 AI 작업 (회수 대상 아닌 것). 끝날 때까지 삭제 미룸"""
    return db.execute(
        text("""
            SELECT count(*) FROM jobs j
            JOIN records r ON j.target_type = 'record' AND r.id = j.target_id
            WHERE r.parent_id = :p AND j.status = 'running'
              AND j.locked_at >= now() - make_interval(mins => :stale)
        """),
        {"p": parent_id, "stale": stale_minutes}
    ).scalar()


def audio_paths(db: Session, parent_id: str) -> list[str]:
    """DB 가 아는 음성 파일 (기록 + 업로드). 고아 파일은 Storage 폴더 목록으로 따로"""
    return list(db.execute(
        text("""
            SELECT audio_path FROM records WHERE parent_id = :p AND audio_path IS NOT NULL
            UNION
            SELECT audio_path FROM audio_uploads WHERE parent_id = :p
        """),
        {"p": parent_id}
    ).scalars())


def delete_space(db: Session, parent_id: str) -> dict:
    """부모님 공간 전체 (연쇄 + 연쇄로 안 지워지는 것). 순서 중요

    1. jobs: FK 없음 → 기록 대상 작업 직접
    2. idempotency_keys: 저장된 응답에 기록 내용 → 이 공간 응답 직접
    3. report_item_sources: records 참조 RESTRICT → 보고서 먼저
    4. audio_uploads: records 참조 연쇄 X → 먼저
    5. parents: 나머지 연쇄 (기록·분류·수정 이력·댓글·증상·가족·초대·알림·일정·체크리스트 …)
       deletion_requests·parent_deletions.parent_id → null (감사 기록 유지)
    """
    p = {"p": parent_id}
    counts = {
        "records": db.execute(text("SELECT count(*) FROM records WHERE parent_id = :p"), p).scalar(),
        "record_versions": db.execute(
            text("SELECT count(*) FROM record_versions v JOIN records r ON r.id = v.record_id WHERE r.parent_id = :p"),
            p
        ).scalar(),
    }
    db.execute(
        text("""
            DELETE FROM jobs
            WHERE target_type = 'record'
              AND target_id IN (SELECT id FROM records WHERE parent_id = :p)
        """),
        p
    )
    db.execute(
        text("""
            DELETE FROM idempotency_keys
            WHERE response_body -> 'data' ->> 'parent_id' = :p
               OR (endpoint = 'POST /v1/parents' AND response_body -> 'data' ->> 'id' = :p)
        """),
        p
    )
    db.execute(text("DELETE FROM reports WHERE parent_id = :p"), p)
    db.execute(text("DELETE FROM audio_uploads WHERE parent_id = :p"), p)
    counts["parents"] = db.execute(text("DELETE FROM parents WHERE id = :p"), p).rowcount
    return counts


def mark_completed(db: Session, deletion_id: str, counts: dict):
    db.execute(
        text("""
            UPDATE parent_deletions
            SET status = 'completed', completed_at = now(), deleted_counts = CAST(:c AS jsonb)
            WHERE id = :d
        """),
        {"d": deletion_id, "c": json.dumps(counts)}
    )
