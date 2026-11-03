"""audio_uploads: issued → consumed / issued → expired (DB 트리거·CHECK로 강제)"""
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


UPLOAD_COLUMNS = """
    id, user_id, parent_id, audio_path, content_type, status,
    expires_at, record_id, consumed_at, storage_deleted_at, created_at
"""


def insert_upload(
    db: Session,
    user_id: str,
    parent_id: str,
    audio_path: str,
    content_type: str,
    expires_in_seconds: int
) -> str:
    return str(db.execute(
        text("""
            INSERT INTO audio_uploads (
                user_id, parent_id, audio_path, content_type, expires_at
            )
            VALUES (
                :user_id, :parent_id, :audio_path, :content_type,
                now() + make_interval(secs => CAST(:expires AS double precision))
            )
            RETURNING id
        """),
        {
            "user_id": user_id,
            "parent_id": parent_id,
            "audio_path": audio_path,
            "content_type": content_type,
            "expires": expires_in_seconds
        }
    ).scalar_one())


def get_upload(db: Session, upload_id: str, for_update: bool = False):
    lock = "FOR UPDATE" if for_update else ""
    return db.execute(
        text(f"SELECT {UPLOAD_COLUMNS} FROM audio_uploads WHERE id = :id {lock}"),
        {"id": upload_id}
    ).mappings().first()


def get_by_record(db: Session, record_id: str):
    return db.execute(
        text(f"SELECT {UPLOAD_COLUMNS} FROM audio_uploads WHERE record_id = :id"),
        {"id": record_id}
    ).mappings().first()


def consume(db: Session, upload_id: str, record_id: str):
    db.execute(
        text("""
            UPDATE audio_uploads
            SET status = 'consumed', consumed_at = now(), record_id = :record_id
            WHERE id = :id AND status = 'issued'
        """),
        {"id": upload_id, "record_id": record_id}
    )


# ── 정리 작업 ──

def claim_cleanup(db: Session, grace_days: int, limit: int):
    """정리 대상 선점. consumed 제외 (만료와 무관)

    - issued + 서명 URL 만료 후 grace_days 경과
    - expired + Storage 삭제 미완료 (이전 실행 실패분)
    """
    return db.execute(
        text(f"""
            SELECT {UPLOAD_COLUMNS}
            FROM audio_uploads
            WHERE (status = 'issued'
                   AND expires_at < now() - make_interval(days => :grace))
               OR (status = 'expired' AND storage_deleted_at IS NULL)
            ORDER BY expires_at
            LIMIT :limit
            FOR UPDATE SKIP LOCKED
        """),
        {"grace": grace_days, "limit": limit}
    ).mappings().all()


def record_id_for_path(db: Session, audio_path: str) -> str | None:
    record_id = db.execute(
        text("SELECT id FROM records WHERE audio_path = :path"),
        {"path": audio_path}
    ).scalar()
    return str(record_id) if record_id else None


def mark_expired(db: Session, upload_id: str):
    db.execute(
        text("UPDATE audio_uploads SET status = 'expired' WHERE id = :id AND status = 'issued'"),
        {"id": upload_id}
    )


def repair_consumed(db: Session, upload_id: str, record_id: str):
    """기록이 참조 중인 issued 업로드 → consumed로 바로잡기"""
    db.execute(
        text("""
            UPDATE audio_uploads
            SET status = 'consumed', consumed_at = now(), record_id = :record_id
            WHERE id = :id AND status = 'issued'
        """),
        {"id": upload_id, "record_id": record_id}
    )


def mark_storage_deleted(db: Session, upload_ids: list[str]):
    if not upload_ids:
        return
    db.execute(
        text("""
            UPDATE audio_uploads
            SET storage_deleted_at = now()
            WHERE id IN :ids AND status = 'expired' AND storage_deleted_at IS NULL
        """).bindparams(bindparam("ids", expanding=True)),
        {"ids": upload_ids}
    )
