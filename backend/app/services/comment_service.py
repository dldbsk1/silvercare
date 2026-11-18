"""기록 댓글 (A-DET-002). 트랜잭션은 라우터가 연다.

- 보기: 그 공간 가족 모두 (viewer 포함)
- 쓰기: 관리자·쓰기 가족 (내 기록·다른 가족 기록 모두). 공간 삭제 예정 → 409 (ensure_write)
- 지우기: 내 댓글만 (관리자도 남의 댓글 X)
- 알림: 기록 작성자 (내가 쓴 기록에 내 댓글 → X)
"""
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.repositories import comment_repo
from app.services import notification_service
from app.services.access import ensure_write
from app.services.record_service import record_access


PREVIEW_LENGTH = 40


def to_out(row, user_id: str) -> dict:
    return {
        "comment_id": str(row["id"]),
        "record_id": str(row["record_id"]),
        "author_id": str(row["author_id"]),
        "author_name": row["author_name"],
        "is_mine": str(row["author_id"]) == user_id,
        "body": row["body"],
        "created_at": row["created_at"],
    }


def list_comments(db: Session, user_id: str, record_id: str) -> dict:
    """meta.can_comment: 입력칸 보이기 (보기 가족·삭제 예정 공간 → false)"""
    access, _ = record_access(db, user_id, record_id)
    return {
        "data": [to_out(r, user_id) for r in comment_repo.list_comments(db, record_id)],
        "meta": {"can_comment": access.can_write and not access.deletion_locked},
    }


def preview(body: str) -> str:
    one_line = " ".join(body.split())
    return one_line if len(one_line) <= PREVIEW_LENGTH else one_line[:PREVIEW_LENGTH] + "…"


def create_comment(db: Session, user_id: str, record_id: str, body: str) -> dict:
    access, record = record_access(db, user_id, record_id)
    ensure_write(access)
    row = comment_repo.insert_comment(db, record_id, user_id, body)

    author_id = str(record["author_id"])
    if author_id != user_id:
        notification_service.notify(
            db, author_id, access.parent_id, "record_comment",
            f"{row['author_name'] or '가족'}님이 내 기록에 댓글을 남겼어요",
            preview(body),
            {"record_id": record_id, "comment_id": str(row["id"])},
            setting=None,
        )
    return to_out(row, user_id)


def delete_comment(db: Session, user_id: str, record_id: str, comment_id: str):
    """내 댓글 아님 → 403. 없음 → 404"""
    access, _ = record_access(db, user_id, record_id)
    row = comment_repo.get_comment(db, record_id, comment_id)
    if row is None:
        raise AppError(404, "NOT_FOUND", "댓글을 찾을 수 없어요.")
    if str(row["author_id"]) != user_id:
        raise AppError(403, "PERMISSION_DENIED", "내가 쓴 댓글만 지울 수 있어요.")
    ensure_write(access)
    comment_repo.delete_comment(db, comment_id)
