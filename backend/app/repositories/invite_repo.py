from sqlalchemy import text
from sqlalchemy.orm import Session


INVITE_COLUMNS = """
    i.id, i.parent_id, i.invited_by, i.intended_role::text AS role,
    i.expires_at, i.accepted_by, i.accepted_at, i.revoked_at, i.created_at,
    i.expires_at <= now() AS expired,
    u.display_name AS inviter_name
"""

# 쓸 수 있는 초대: 수락 X, 취소 X, 만료 전
ACTIVE = "i.accepted_at IS NULL AND i.revoked_at IS NULL AND i.expires_at > now()"


def insert_invite(
    db: Session,
    parent_id: str,
    invited_by: str,
    role: str,
    token_hash: str,
    valid_days: int
) -> dict:
    return dict(db.execute(
        text("""
            INSERT INTO family_invites
                (parent_id, invited_by, intended_role, token_hash,
                 expires_at, share_confirmed_at)
            VALUES (:parent_id, :invited_by, CAST(:role AS family_role_enum),
                    :token_hash, now() + make_interval(days => :days), now())
            RETURNING id, intended_role::text AS role, expires_at
        """),
        {
            "parent_id": parent_id,
            "invited_by": invited_by,
            "role": role,
            "token_hash": token_hash,
            "days": valid_days
        }
    ).mappings().one())


def count_active(db: Session, parent_id: str) -> int:
    return db.execute(
        text(f"SELECT count(*) FROM family_invites i WHERE i.parent_id = :p AND {ACTIVE}"),
        {"p": parent_id}
    ).scalar_one()


def list_active(db: Session, parent_id: str):
    return db.execute(
        text(f"""
            SELECT {INVITE_COLUMNS}
            FROM family_invites i
            JOIN users u ON u.id = i.invited_by
            WHERE i.parent_id = :p AND {ACTIVE}
            ORDER BY i.created_at DESC, i.id
        """),
        {"p": parent_id}
    ).mappings().all()


def get_by_hash(db: Session, token_hash: str, for_update: bool = False):
    lock = "FOR UPDATE OF i" if for_update else ""
    return db.execute(
        text(f"""
            SELECT {INVITE_COLUMNS}
            FROM family_invites i
            JOIN users u ON u.id = i.invited_by
            WHERE i.token_hash = :h
            {lock}
        """),
        {"h": token_hash}
    ).mappings().first()


def get_by_id(db: Session, invite_id: str, for_update: bool = False):
    lock = "FOR UPDATE OF i" if for_update else ""
    return db.execute(
        text(f"""
            SELECT {INVITE_COLUMNS}
            FROM family_invites i
            JOIN users u ON u.id = i.invited_by
            WHERE i.id = :id
            {lock}
        """),
        {"id": invite_id}
    ).mappings().first()


def mark_accepted(db: Session, invite_id: str, user_id: str):
    db.execute(
        text("""
            UPDATE family_invites SET accepted_by = :u, accepted_at = now()
            WHERE id = :id
        """),
        {"id": invite_id, "u": user_id}
    )


def revoke(db: Session, invite_id: str):
    db.execute(
        text("UPDATE family_invites SET revoked_at = now() WHERE id = :id"),
        {"id": invite_id}
    )


def revoke_created_by(db: Session, parent_id: str, user_id: str) -> int:
    """관리자 권한 잃음 (강등·내보내기·나가기) → 그 사람이 만든 미사용 초대 전부 취소"""
    return db.execute(
        text("""
            UPDATE family_invites SET revoked_at = now()
            WHERE parent_id = :p AND invited_by = :u
              AND accepted_at IS NULL AND revoked_at IS NULL
        """),
        {"p": parent_id, "u": user_id}
    ).rowcount
