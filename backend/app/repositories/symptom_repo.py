from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session


def insert(
    db: Session,
    record_id: str,
    symptom_type: str,
    custom_label: str | None,
    time_band: str,
    occurrence_count: int,
    note: str | None,
):
    db.execute(
        text("""
            INSERT INTO record_symptoms
                (record_id, symptom_type, custom_label, time_band, occurrence_count, note)
            VALUES (:r, :t, :label, :band, :n, :note)
        """),
        {"r": record_id, "t": symptom_type, "label": custom_label, "band": time_band,
         "n": occurrence_count, "note": note}
    )


def item_record_counts(db: Session, parent_id: str, codes: list[str], since: datetime) -> dict[str, int]:
    """항목별 기록 수 (모든 입력 방식 · 제외 안 된 기록 · 기간 안). 증상 칩 추천용"""
    rows = db.execute(
        text("""
            SELECT ri.item_code, count(DISTINCT r.id)
            FROM record_items ri
            JOIN records r ON r.id = ri.record_id
            WHERE r.parent_id = :p AND r.status = 'normal'
              AND COALESCE(r.occurred_at, r.recorded_at) >= :since
              AND ri.item_code = ANY(:codes)
            GROUP BY ri.item_code
        """),
        {"p": parent_id, "codes": codes, "since": since}
    ).all()
    return {code: count for code, count in rows}


def weekly_counts(
    db: Session,
    parent_id: str,
    symptom_type: str,
    custom_label: str | None,
    start: datetime,
) -> list[tuple[datetime, int]]:
    """주(월요일 시작, 한국 시간)별 횟수 합. 빈 주 → 없음 (서비스에서 0 채움)
    조사표 항목 → 증상 기록 중 그 항목 / custom → 같은 이름"""
    return db.execute(
        text("""
            SELECT date_trunc('week', COALESCE(r.occurred_at, r.recorded_at) AT TIME ZONE 'Asia/Seoul') AS week,
                   sum(s.occurrence_count)
            FROM record_symptoms s
            JOIN records r ON r.id = s.record_id
            WHERE r.parent_id = :p AND r.status = 'normal'
              AND s.symptom_type = :t
              AND (CAST(:label AS text) IS NULL OR s.custom_label = :label)
              AND COALESCE(r.occurred_at, r.recorded_at) >= :start
            GROUP BY 1
        """),
        {"p": parent_id, "t": symptom_type, "label": custom_label, "start": start}
    ).all()


def get(db: Session, record_id: str):
    return db.execute(
        text("""
            SELECT symptom_type, custom_label, time_band::text AS time_band, occurrence_count, note
            FROM record_symptoms WHERE record_id = :r
        """),
        {"r": record_id}
    ).mappings().first()


def update(db: Session, record_id: str, time_band: str, occurrence_count: int, note: str | None):
    db.execute(
        text("""
            UPDATE record_symptoms
            SET time_band = :band, occurrence_count = :n, note = :note
            WHERE record_id = :r
        """),
        {"r": record_id, "band": time_band, "n": occurrence_count, "note": note}
    )
