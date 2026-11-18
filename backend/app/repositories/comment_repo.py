"""record_comments: 기록 댓글 (A-DET-002). 글 1~1000자 (DB CHECK)"""
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.repositories.record_repo import USER_NAME


COMMENT_COLUMNS = f"""
    c.id, c.record_id, c.author_id, c.body, c.created_at,
    (SELECT {USER_NAME} FROM users u WHERE u.id = c.author_id) AS author_name
"""


def list_comments(db: Session, record_id: str):
    """오래된 순 (대화 순서)"""
    return db.execute(
        text(f"""
            SELECT {COMMENT_COLUMNS} FROM record_comments c
            WHERE c.record_id = :id
            ORDER BY c.created_at, c.id
        """),
        {"id": record_id}
    ).mappings().all()


def insert_comment(db: Session, record_id: str, author_id: str, body: str):
    comment_id = db.execute(
        text("""
            INSERT INTO record_comments (record_id, author_id, body)
            VALUES (:r, :a, :body)
            RETURNING id
        """),
        {"r": record_id, "a": author_id, "body": body}
    ).scalar_one()
    return get_comment(db, record_id, str(comment_id))


def get_comment(db: Session, record_id: str, comment_id: str):
    return db.execute(
        text(f"SELECT {COMMENT_COLUMNS} FROM record_comments c WHERE c.id = :id AND c.record_id = :r"),
        {"id": comment_id, "r": record_id}
    ).mappings().first()


def delete_comment(db: Session, comment_id: str):
    db.execute(text("DELETE FROM record_comments WHERE id = :id"), {"id": comment_id})
