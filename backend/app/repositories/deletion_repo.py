from sqlalchemy import text
from sqlalchemy.orm import Session


REQUEST_COLUMNS = """
    id, requester_id, request_type, status::text AS status,
    requested_at, scheduled_for, parent_ids
"""

# 열린 요청: 접수됨 · 실행 중 (unique index deletion_requests_open과 같은 조건)
OPEN = "status IN ('requested', 'approved')"


def get_open(db: Session, user_id: str, request_type: str):
    return db.execute(
        text(f"""
            SELECT {REQUEST_COLUMNS} FROM deletion_requests
            WHERE requester_id = :u AND request_type = :t AND {OPEN}
        """),
        {"u": user_id, "t": request_type}
    ).mappings().first()


def get_latest(db: Session, user_id: str, request_type: str):
    """취소 제외 최근 요청 (완료 포함)"""
    return db.execute(
        text(f"""
            SELECT {REQUEST_COLUMNS} FROM deletion_requests
            WHERE requester_id = :u AND request_type = :t AND status <> 'cancelled'
            ORDER BY requested_at DESC, id
            LIMIT 1
        """),
        {"u": user_id, "t": request_type}
    ).mappings().first()


def insert_request(
    db: Session,
    user_id: str,
    request_type: str,
    grace_days: int,
    parent_ids: list[str] = ()
):
    return db.execute(
        text(f"""
            INSERT INTO deletion_requests
                (requester_id, request_type, scheduled_for, parent_ids)
            VALUES (:u, :t, now() + make_interval(days => :days), CAST(:parent_ids AS uuid[]))
            RETURNING {REQUEST_COLUMNS}
        """),
        {"u": user_id, "t": request_type, "days": grace_days, "parent_ids": list(parent_ids)}
    ).mappings().one()


def cancel_requested(db: Session, user_id: str, request_type: str, note: str) -> int:
    """접수 상태만 취소 (실행 중 approved는 그대로)"""
    return db.execute(
        text("""
            UPDATE deletion_requests
            SET status = 'cancelled', reviewed_at = now(), resolution_note = :note
            WHERE requester_id = :u AND request_type = :t AND status = 'requested'
        """),
        {"u": user_id, "t": request_type, "note": note}
    ).rowcount


# ── 삭제 실행 (워커) ──

def claim_due(db: Session, request_types: tuple[str, ...], limit: int):
    """예정일 지난 열린 요청 선점 → approved. 실패해 approved로 남은 요청도 다시 가져옴"""
    return db.execute(
        text(f"""
            UPDATE deletion_requests
            SET status = 'approved', reviewed_at = coalesce(reviewed_at, now())
            WHERE id IN (
                SELECT id FROM deletion_requests
                WHERE {OPEN} AND scheduled_for <= now()
                  AND request_type = ANY(:types)
                ORDER BY scheduled_for, id
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
            )
            RETURNING {REQUEST_COLUMNS}
        """),
        {"types": list(request_types), "limit": limit}
    ).mappings().all()


def lock_approved(db: Session, request_id: str) -> bool:
    return db.execute(
        text("""
            SELECT 1 FROM deletion_requests
            WHERE id = :id AND status = 'approved'
            FOR UPDATE
        """),
        {"id": request_id}
    ).first() is not None


def mark_completed(db: Session, request_id: str):
    db.execute(
        text("""
            UPDATE deletion_requests SET status = 'completed', completed_at = now()
            WHERE id = :id
        """),
        {"id": request_id}
    )


def audio_paths(db: Session, user_id: str, parent_ids: list[str]) -> list[str]:
    """지울 음성 파일: 내 기록 + 함께 지울 부모님 공간의 기록·업로드"""
    return list(db.execute(
        text("""
            SELECT r.audio_path FROM records r
            WHERE r.audio_path IS NOT NULL
              AND (r.author_id = :u OR r.parent_id = ANY(CAST(:p AS uuid[])))
            UNION
            SELECT a.audio_path FROM audio_uploads a
            WHERE a.storage_deleted_at IS NULL
              AND (a.record_id IN (SELECT id FROM records WHERE author_id = :u)
                   OR a.parent_id = ANY(CAST(:p AS uuid[])))
        """),
        {"u": user_id, "p": parent_ids}
    ).scalars())


def delete_records_by(db: Session, user_id: str) -> int:
    """내가 쓴 기록 (분류·수정 이력·댓글·증상 연쇄 삭제). 업로드 행 먼저 (참조 연쇄 없음)"""
    db.execute(
        text("""
            DELETE FROM audio_uploads
            WHERE record_id IN (SELECT id FROM records WHERE author_id = :u)
        """),
        {"u": user_id}
    )
    return db.execute(
        text("DELETE FROM records WHERE author_id = :u"), {"u": user_id}
    ).rowcount


def delete_sole_parents(db: Session, user_id: str, parent_ids: list[str]) -> int:
    """혼자 쓰던 부모님 공간 삭제 (연쇄). 그사이 다른 가족 생김 → 남김"""
    return db.execute(
        text("""
            DELETE FROM parents p
            WHERE p.id = ANY(CAST(:p AS uuid[]))
              AND NOT EXISTS (
                  SELECT 1 FROM family_members fm
                  WHERE fm.parent_id = p.id AND fm.user_id <> :u
              )
        """),
        {"u": user_id, "p": parent_ids}
    ).rowcount


def delete_account_data(db: Session, user_id: str):
    """기기·알림 설정·알림·멱등 키 (사용자 행은 유지)"""
    for table in ("devices", "notification_settings", "notifications", "idempotency_keys"):
        db.execute(text(f"DELETE FROM {table} WHERE user_id = :u"), {"u": user_id})
