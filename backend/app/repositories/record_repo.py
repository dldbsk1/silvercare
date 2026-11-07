from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session


RECORD_COLUMNS = """
    r.id, r.parent_id, r.author_id,
    r.input_type::text AS input_type, r.source::text AS source,
    r.status::text AS status,
    r.processing_status::text AS processing_status,
    r.processing_error, r.transcript_empty,
    r.classification_status::text AS classification_status,
    r.classified_by::text AS classified_by,
    r.text_version, r.original_text, r.current_text,
    r.audio_path, r.audio_duration_seconds,
    r.recorded_at, r.occurred_at, r.created_at, r.updated_at,
    (SELECT u.display_name FROM users u WHERE u.id = r.author_id) AS author_name,
    -- 사용자 수정 이력 있음 (record_versions: PATCH로 실제 바뀐 칸만 저장)
    EXISTS (SELECT 1 FROM record_versions rv WHERE rv.record_id = r.id) AS is_edited
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
    occurred_at,
    audio_path: str | None = None,
    audio_duration_seconds: int | None = None
) -> dict:
    """original_text = current_text. text_version: 트리거가 1로 고정

    voice: 원문·현재 글 NULL, pending (트리거가 강제)
    """
    return dict(db.execute(
        text("""
            INSERT INTO records (
                parent_id, author_id, input_type, source,
                original_text, current_text, recorded_at, occurred_at,
                audio_path, audio_duration_seconds
            )
            VALUES (
                :parent_id, :author_id,
                CAST(:input_type AS input_type_enum),
                CAST(:source AS record_source_enum),
                :text, :text, COALESCE(:recorded_at, now()), :occurred_at,
                :audio_path, :audio_duration_seconds
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
            "occurred_at": occurred_at,
            "audio_path": audio_path,
            "audio_duration_seconds": audio_duration_seconds
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


@dataclass(frozen=True)
class RecordFilter:
    """목록 조건 (모두 AND). None → 조건 없음"""

    status: str | None = None
    area: str | None = None
    author_id: str | None = None
    # recorded_at 범위: from 포함, before 미포함
    recorded_from: datetime | None = None
    recorded_before: datetime | None = None
    source: str | None = None
    input_type: str | None = None
    processing_status: str | None = None
    classification_status: str | None = None
    # current_text 부분 일치 (원문 X)
    q: str | None = None


def escape_like(value: str) -> str:
    """LIKE 패턴 문자 그대로 검색 (역슬래시 → % → _ 순서)"""
    return value.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def filter_conditions(parent_id: str, f: RecordFilter) -> tuple[list[str], dict]:
    conditions = ["r.parent_id = :parent_id"]
    params = {"parent_id": parent_id}

    simple = [
        ("status", "r.status = CAST(:status AS record_status_enum)"),
        ("author_id", "r.author_id = CAST(:author_id AS uuid)"),
        ("recorded_from", "r.recorded_at >= :recorded_from"),
        ("recorded_before", "r.recorded_at < :recorded_before"),
        ("source", "r.source = CAST(:source AS record_source_enum)"),
        ("input_type", "r.input_type = CAST(:input_type AS input_type_enum)"),
        ("processing_status",
         "r.processing_status = CAST(:processing_status AS processing_status_enum)"),
        ("classification_status",
         "r.classification_status = "
         "CAST(:classification_status AS classification_status_enum)"),
    ]
    for name, condition in simple:
        value = getattr(f, name)
        if value is not None:
            conditions.append(condition)
            params[name] = value

    # 영역: 여러 항목에 걸려도 기록 1건 (EXISTS)
    if f.area is not None:
        conditions.append("""
            EXISTS (
                SELECT 1
                FROM record_items ri
                JOIN survey_items si ON si.code = ri.item_code
                WHERE ri.record_id = r.id AND si.area = CAST(:area AS area_enum)
            )
        """)
        params["area"] = f.area

    if f.q is not None:
        conditions.append(r"r.current_text ILIKE :q ESCAPE '\'")
        params["q"] = f"%{escape_like(f.q)}%"

    return conditions, params


def list_records(
    db: Session,
    parent_id: str,
    filters: RecordFilter,
    limit: int,
    after: tuple[datetime, str] | None = None
):
    """최신순 (recorded_at, id). 인덱스 (parent_id, recorded_at DESC, id DESC)

    after: 이전 페이지 마지막 항목 (recorded_at, id) → 그 다음부터 (keyset)
    """
    conditions, params = filter_conditions(parent_id, filters)
    if after is not None:
        conditions.append(
            "(r.recorded_at, r.id) < (CAST(:after_at AS timestamptz), CAST(:after_id AS uuid))"
        )
        params["after_at"], params["after_id"] = after

    return db.execute(
        text(f"""
            SELECT {RECORD_COLUMNS}, {AREAS_SUBQUERY}
            FROM records r
            WHERE {" AND ".join(conditions)}
            ORDER BY r.recorded_at DESC, r.id DESC
            LIMIT :limit
        """),
        {**params, "limit": limit}
    ).mappings().all()


def count_records(db: Session, parent_id: str, filters: RecordFilter) -> int:
    conditions, params = filter_conditions(parent_id, filters)
    return db.execute(
        text(f"SELECT count(*) FROM records r WHERE {' AND '.join(conditions)}"),
        params
    ).scalar_one()


def set_processing_status(
    db: Session,
    record_id: str,
    status: str,
    error: str | None = None
):
    """error: failed 일 때만 (DB CHECK). 그 외 상태 → 오류 코드 비움"""
    db.execute(
        text("""
            UPDATE records
            SET processing_status = CAST(:status AS processing_status_enum),
                processing_error = :error
            WHERE id = :id
        """),
        {"id": record_id, "status": status, "error": error}
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
                processing_status = CAST(:processing_status AS processing_status_enum),
                processing_error = NULL
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
    occurred_at,
    classified_by: str | None,
    changed_fields: list[str]
):
    """수정 전 상태 스냅샷 (POL-02 수정 이력)

    version: 기록당 순번. 호출 전 기록 행 잠금 필수 (UNIQUE(record_id, version)로 한 번 더 보장)
    """
    db.execute(
        text("""
            INSERT INTO record_versions (
                record_id, version, changed_fields, text, edited_by,
                source_snapshot, item_codes_snapshot, occurred_at_snapshot,
                classified_by_snapshot
            )
            VALUES (
                :record_id,
                (SELECT COALESCE(max(version), 0) + 1
                 FROM record_versions WHERE record_id = :record_id),
                CAST(:changed AS text[]), :text, :edited_by,
                CAST(:source AS record_source_enum),
                CAST(:item_codes AS text[]), :occurred_at,
                CAST(:classified_by AS set_by_enum)
            )
        """),
        {
            "record_id": record_id,
            "changed": list(changed_fields),
            "text": text_value,
            "edited_by": edited_by,
            "source": source,
            "item_codes": list(item_codes),
            "occurred_at": occurred_at,
            "classified_by": classified_by
        }
    )


def list_versions(db: Session, record_id: str):
    return db.execute(
        text("""
            SELECT rv.version, rv.changed_fields, rv.text, rv.edited_by, rv.edited_at,
                   rv.source_snapshot::text AS source_snapshot,
                   rv.item_codes_snapshot, rv.occurred_at_snapshot,
                   rv.classified_by_snapshot::text AS classified_by_snapshot,
                   u.display_name AS edited_by_name
            FROM record_versions rv
            LEFT JOIN users u ON u.id = rv.edited_by
            WHERE rv.record_id = :id
            ORDER BY rv.version DESC
        """),
        {"id": record_id}
    ).mappings().all()


def set_status(db: Session, record_id: str, status: str):
    db.execute(
        text("""
            UPDATE records SET status = CAST(:status AS record_status_enum)
            WHERE id = :id
        """),
        {"id": record_id, "status": status}
    )


def save_transcript(
    db: Session,
    record_id: str,
    transcript: str,
    duration_seconds: int,
    processing_status: str
):
    """최초 받아쓰기. 트리거 허용 조건: app.writer = transcription (이 트랜잭션 한정)

    원문 = 현재 글 동시 저장, text_version 유지. '' → transcript_empty
    """
    db.execute(text("SELECT set_config('app.writer', 'transcription', true)"))
    db.execute(
        text("""
            UPDATE records
            SET original_text = :text,
                current_text = :text,
                transcript_empty = (:text = ''),
                audio_duration_seconds = :duration,
                processing_status = CAST(:status AS processing_status_enum),
                processing_error = NULL
            WHERE id = :id
        """),
        {
            "id": record_id,
            "text": transcript,
            "duration": duration_seconds,
            "status": processing_status
        }
    )
    db.execute(text("SELECT set_config('app.writer', '', true)"))
