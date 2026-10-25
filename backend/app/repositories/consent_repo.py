from sqlalchemy import text
from sqlalchemy.orm import Session


def list_active_documents(db: Session):
    """종류별로 지금 유효한 동의 문구 1개씩 (가장 최근 발행본)"""
    return db.execute(
        text("""
            SELECT DISTINCT ON (type)
                   type::text AS type, doc_version, title, content,
                   required, published_at
            FROM consent_documents
            WHERE retired_at IS NULL AND published_at <= now()
            ORDER BY type, published_at DESC
        """)
    ).mappings().all()


def list_active_documents_excluding_dev(db: Session):
    """운영 환경용: 개발용(dev-) 문구는 유효한 문구로 보지 않는다"""
    return db.execute(
        text("""
            SELECT DISTINCT ON (type)
                   type::text AS type, doc_version, title, content,
                   required, published_at
            FROM consent_documents
            WHERE retired_at IS NULL AND published_at <= now()
              AND doc_version NOT LIKE 'dev-%'
            ORDER BY type, published_at DESC
        """)
    ).mappings().all()


def lock_user(db: Session, user_id: str):
    """같은 사용자의 동의 변경이 동시에 일어나지 않도록 users 행을 잠근다"""
    db.execute(
        text("SELECT 1 FROM users WHERE id = :user_id FOR UPDATE"),
        {"user_id": user_id}
    )


def list_active_consents(db: Session, user_id: str):
    """철회하지 않은 동의 (종류별 최신 1개)"""
    return db.execute(
        text("""
            SELECT DISTINCT ON (type)
                   id, type::text AS type, doc_version, agreed_at
            FROM consents
            WHERE user_id = :user_id AND revoked_at IS NULL
            ORDER BY type, agreed_at DESC
        """),
        {"user_id": user_id}
    ).mappings().all()


def list_consent_history(db: Session, user_id: str):
    return db.execute(
        text("""
            SELECT type::text AS type, doc_version, agreed_at, revoked_at
            FROM consents
            WHERE user_id = :user_id
            ORDER BY agreed_at DESC
        """),
        {"user_id": user_id}
    ).mappings().all()


def insert_consent(db: Session, user_id: str, consent_type: str, doc_version: str):
    db.execute(
        text("""
            INSERT INTO consents (user_id, type, doc_version)
            VALUES (:user_id, CAST(:type AS consent_type_enum), :doc_version)
        """),
        {"user_id": user_id, "type": consent_type, "doc_version": doc_version}
    )


def revoke_consents(db: Session, user_id: str, consent_type: str) -> int:
    """이 종류의 유효한 동의를 모두 철회. 철회한 개수를 돌려준다"""
    return db.execute(
        text("""
            UPDATE consents
            SET revoked_at = now()
            WHERE user_id = :user_id
              AND type = CAST(:type AS consent_type_enum)
              AND revoked_at IS NULL
        """),
        {"user_id": user_id, "type": consent_type}
    ).rowcount
