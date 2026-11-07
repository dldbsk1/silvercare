from sqlalchemy import text
from sqlalchemy.orm import Session


PARENT_COLUMNS = """
    p.id, p.nickname, p.age_band, p.apply_stage::text AS apply_stage,
    p.cohabiting, p.survey_date, p.judged_date, p.survey_scheduled_at
"""


def create_parent(
    db: Session,
    nickname: str,
    age_band: str | None,
    apply_stage: str,
    cohabiting: bool
) -> str:
    return str(db.execute(
        text("""
            INSERT INTO parents (nickname, age_band, apply_stage, cohabiting)
            VALUES (:nickname, :age_band,
                    CAST(:apply_stage AS apply_stage_enum), :cohabiting)
            RETURNING id
        """),
        {
            "nickname": nickname,
            "age_band": age_band,
            "apply_stage": apply_stage,
            "cohabiting": cohabiting
        }
    ).scalar_one())


def add_member(db: Session, parent_id: str, user_id: str, role: str):
    db.execute(
        text("""
            INSERT INTO family_members (parent_id, user_id, role)
            VALUES (:parent_id, :user_id, CAST(:role AS family_role_enum))
        """),
        {"parent_id": parent_id, "user_id": user_id, "role": role}
    )


def get_for_user(db: Session, parent_id: str, user_id: str):
    """가족인 부모님만 조회 (my_role 포함). 가족이 아니면 None"""
    return db.execute(
        text(f"""
            SELECT {PARENT_COLUMNS}, fm.role::text AS my_role
            FROM parents p
            JOIN family_members fm ON fm.parent_id = p.id
            WHERE p.id = :parent_id AND fm.user_id = :user_id
        """),
        {"parent_id": parent_id, "user_id": user_id}
    ).mappings().first()


def list_for_user(db: Session, user_id: str):
    return db.execute(
        text(f"""
            SELECT {PARENT_COLUMNS}, fm.role::text AS my_role
            FROM parents p
            JOIN family_members fm ON fm.parent_id = p.id
            WHERE fm.user_id = :user_id
            ORDER BY fm.joined_at, p.id
        """),
        {"user_id": user_id}
    ).mappings().all()



def get_nickname(db: Session, parent_id: str) -> str | None:
    return db.execute(
        text("SELECT nickname FROM parents WHERE id = :id"), {"id": parent_id}
    ).scalar_one_or_none()


def get_for_update(db: Session, parent_id: str):
    return db.execute(
        text(f"SELECT {PARENT_COLUMNS} FROM parents p WHERE p.id = :id FOR UPDATE"),
        {"id": parent_id}
    ).mappings().one()


# 칸 → SET 식 (enum 형 변환)
UPDATE_EXPRESSIONS = {
    "nickname": "nickname = :nickname",
    "age_band": "age_band = :age_band",
    "apply_stage": "apply_stage = CAST(:apply_stage AS apply_stage_enum)",
    "cohabiting": "cohabiting = :cohabiting",
    "survey_date": "survey_date = :survey_date",
    "judged_date": "judged_date = :judged_date",
}


def update_fields(db: Session, parent_id: str, fields: dict):
    assignments = ", ".join(UPDATE_EXPRESSIONS[f] for f in fields)
    db.execute(
        text(f"UPDATE parents SET {assignments} WHERE id = :id"),
        {"id": parent_id, **fields}
    )
