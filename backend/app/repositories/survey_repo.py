from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


def existing_codes(db: Session, codes: list[str]) -> set[str]:
    """codes 중 survey_items(52항목)에 있는 것만"""
    if not codes:
        return set()

    rows = db.execute(
        text("SELECT code FROM survey_items WHERE code IN :codes")
        .bindparams(bindparam("codes", expanding=True)),
        {"codes": list(codes)}
    ).scalars()
    return set(rows)


def all_codes(db: Session) -> set[str]:
    return set(db.execute(text("SELECT code FROM survey_items")).scalars())
