from sqlalchemy import text
from sqlalchemy.orm import Session


RECORD_COLUMNS = """
    r.id, r.parent_id, r.author_id,
    r.input_type::text AS input_type, r.source::text AS source,
    r.status::text AS status,
    r.processing_status::text AS processing_status,
    r.classification_status::text AS classification_status,
    r.classified_by::text AS classified_by,
    r.text_version, r.original_text, r.current_text,
    r.audio_path, r.audio_duration_seconds,
    r.recorded_at, r.occurred_at, r.created_at, r.updated_at
"""

# 영역 태그: 조사표 영역 순서 (신체 → 인지 → 행동변화 → 간호처치 → 재활)
AREAS_SUBQUERY = """
    COALESCE((
        SELECT array_agg(a.area ORDER BY a.first_sort)
        FROM (
            SELECT si.area::text AS area, min(si.sort_order) AS first_sort
            FROM record_items ri
            JOIN survey_items si ON si.code = ri.item_code
            WHERE ri.record_id = r.id
            GROUP BY si.area
        ) a
    ), ARRAY[]::text[]) AS areas
"""


def insert_record(
    db: Session,
    parent_id: str,
    author_id: str,
    input_type: str,
    source: str,
    text_value: str | None,
    recorded_at,
    occurred_at
) -> dict:
    """original_text = current_text. text_version: 트리거가 1로 고정"""
    return dict(db.execute(
        text("""
            INSERT INTO records (
                parent_id, author_id, input_type, source,
                original_text, current_text, recorded_at, occurred_at
            )
            VALUES (
                :parent_id, :author_id,
                CAST(:input_type AS input_type_enum),
                CAST(:source AS record_source_enum),
                :text, :text, COALESCE(:recorded_at, now()), :occurred_at
            )
            RETURNING id, text_version
        """),
        {
            "parent_id": parent_id,
            "author_id": author_id,
            "input_type": input_type,
            "source": source,
            "text": text_value,
            "recorded_at": recorded_at,
            "occurred_at": occurred_at
        }
    ).mappings().one())


def get_record(db: Session, record_id: str, for_update: bool = False):
    lock = "FOR UPDATE OF r" if for_update else ""
    return db.execute(
        text(f"""
            SELECT {RECORD_COLUMNS}, {AREAS_SUBQUERY}
            FROM records r
            WHERE r.id = :id
            {lock}
        """),
        {"id": record_id}
    ).mappings().first()


def get_items(db: Session, record_id: str):
    return db.execute(
        text("""
            SELECT si.area::text AS area, ri.item_code, si.label,
                   ri.confidence, ri.set_by::text AS set_by
            FROM record_items ri
            JOIN survey_items si ON si.code = ri.item_code
            WHERE ri.record_id = :id
            ORDER BY si.sort_order
        """),
        {"id": record_id}
    ).mappings().all()


def list_records(db: Session, parent_id: str, status: str | None, limit: int):
    """최신순 (recorded_at, id). 인덱스 (parent_id, recorded_at DESC, id DESC)"""
    return db.execute(
        text(f"""
            SELECT {RECORD_COLUMNS}, {AREAS_SUBQUERY}
            FROM records r
            WHERE r.parent_id = :parent_id
              AND (CAST(:status AS record_status_enum) IS NULL
                   OR r.status = CAST(:status AS record_status_enum))
            ORDER BY r.recorded_at DESC, r.id DESC
            LIMIT :limit
        """),
        {"parent_id": parent_id, "status": status, "limit": limit}
    ).mappings().all()


def set_processing_status(db: Session, record_id: str, status: str):
    db.execute(
        text("""
            UPDATE records
            SET processing_status = CAST(:status AS processing_status_enum)
            WHERE id = :id
        """),
        {"id": record_id, "status": status}
    )


def replace_items(
    db: Session,
    record_id: str,
    items: list[tuple[str, float | None]],
    set_by: str
):
    """분류 전체 교체. 중복 실행·중복 코드 → 1건 (unique + ON CONFLICT)"""
    db.execute(
        text("DELETE FROM record_items WHERE record_id = :id"),
        {"id": record_id}
    )
    for item_code, confidence in items:
        db.execute(
            text("""
                INSERT INTO record_items (record_id, item_code, confidence, set_by)
                VALUES (:id, :code, :confidence, CAST(:set_by AS set_by_enum))
                ON CONFLICT (record_id, item_code) DO NOTHING
            """),
            {
                "id": record_id,
                "code": item_code,
                "confidence": confidence,
                "set_by": set_by
            }
        )


def set_classification(
    db: Session,
    record_id: str,
    classification_status: str | None,
    classified_by: str | None,
    processing_status: str
):
    db.execute(
        text("""
            UPDATE records
            SET classification_status =
                    CAST(:classification_status AS classification_status_enum),
                classified_by = CAST(:classified_by AS set_by_enum),
                processing_status = CAST(:processing_status AS processing_status_enum)
            WHERE id = :id
        """),
        {
            "id": record_id,
            "classification_status": classification_status,
            "classified_by": classified_by,
            "processing_status": processing_status
        }
    )


def update_fields(db: Session, record_id: str, fields: dict) -> int:
    """current_text / source / occurred_at 중 보낸 것만. 새 text_version 반환 (트리거 계산)"""
    assignments = []
    if "current_text" in fields:
        assignments.append("current_text = :current_text")
    if "source" in fields:
        assignments.append("source = CAST(:source AS record_source_enum)")
    if "occurred_at" in fields:
        assignments.append("occurred_at = :occurred_at")

    return db.execute(
        text(f"""
            UPDATE records
            SET {", ".join(assignments)}
            WHERE id = :id
            RETURNING text_version
        """),
        {"id": record_id, **fields}
    ).scalar_one()


def insert_version(
    db: Session,
    record_id: str,
    text_value: str,
    edited_by: str,
    source: str,
    item_codes: list[str],
    occurred_at
):
    """수정 전 상태 스냅샷 (POL-02 수정 이력)"""
    db.execute(
        text("""
            INSERT INTO record_versions (
                record_id, text, edited_by,
                source_snapshot, item_codes_snapshot, occurred_at_snapshot
            )
            VALUES (
                :record_id, :text, :edited_by,
                CAST(:source AS record_source_enum),
                CAST(:item_codes AS text[]), :occurred_at
            )
        """),
        {
            "record_id": record_id,
            "text": text_value,
            "edited_by": edited_by,
            "source": source,
            "item_codes": list(item_codes),
            "occurred_at": occurred_at
        }
    )
