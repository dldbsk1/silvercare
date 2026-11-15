"""증상 기록 (A-SYM-001/002): 추천 칩 · 저장 · 최근 4주"""
from datetime import datetime, timedelta, timezone

from app.services import symptom_service
from app.services.dday import KST
from tests.integration.conftest import join_family, run_sql, sql_scalar


def save(client, parent_id, **body):
    payload = {"symptom_type": "beh_hiding", "time_band": "night", "occurrence_count": 2, **body}
    return client.post(f"/v1/parents/{parent_id}/symptoms", json=payload)


def suggestions(client, parent_id):
    return client.get(f"/v1/parents/{parent_id}/symptoms/suggestions").json()["data"]


def weekly(client, parent_id, **params):
    return client.get(f"/v1/parents/{parent_id}/symptoms/weekly", params=params)


def add_classified_text(db, parent_id, user_id, code, days_ago=1):
    """다른 입력(텍스트)으로 분류된 기록 (추천 집계용)"""
    record_id = sql_scalar(
        db,
        """
            INSERT INTO records (parent_id, author_id, input_type, source, original_text, current_text, recorded_at)
            VALUES (:p, :u, 'text', 'direct', '기록', '기록', now() - make_interval(days => :d))
            RETURNING id
        """,
        p=parent_id, u=user_id, d=days_ago
    )
    run_sql(
        db,
        "INSERT INTO record_items (record_id, item_code, set_by) VALUES (:r, :c, 'user')",
        r=record_id, c=code
    )
    run_sql(
        db,
        """
            UPDATE records SET classification_status = 'classified', classified_by = 'user',
                               processing_status = 'completed'
            WHERE id = :r
        """,
        r=record_id
    )


# ── 저장 ──

def test_save_preset_classified_at_once(client, db, user_id, parent_id):
    response = save(client, parent_id, note="새벽 3시에 현관문을 열려고 하심")
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["label"] == "물건 숨기기" and data["occurrence_count"] == 2

    record = client.get(f"/v1/records/{data['record_id']}").json()["data"]
    assert record["input_type"] == "symptom"
    assert record["current_text"] == "물건 숨기기 · 밤 · 2번\n새벽 3시에 현관문을 열려고 하심"
    assert record["classification_status"] == "classified"
    assert [i["item_code"] for i in record["items"]] == ["beh_hiding"]
    # AI 작업 없음
    assert sql_scalar(db, "SELECT count(*) FROM jobs WHERE target_id = :r", r=data["record_id"]) == 0


def test_save_custom_goes_to_ai(client, db, user_id, parent_id):
    response = save(client, parent_id, symptom_type="custom", custom_label="밥 거부")
    assert response.status_code == 201
    record_id = response.json()["data"]["record_id"]
    assert sql_scalar(
        db, "SELECT count(*) FROM jobs WHERE target_id = :r AND type = 'classify_record'", r=record_id
    ) == 1
    assert sql_scalar(db, "SELECT custom_label FROM record_symptoms WHERE record_id = :r", r=record_id) == "밥 거부"


def test_save_validation(client, parent_id):
    assert save(client, parent_id, symptom_type="custom").status_code == 422
    assert save(client, parent_id, custom_label="이름").status_code == 422
    assert save(client, parent_id, time_band="noon").status_code == 422
    assert save(client, parent_id, occurrence_count=0).status_code == 422
    assert save(client, parent_id, occurrence_count=21).status_code == 422
    # 신체 항목 → 증상 후보 X
    assert save(client, parent_id, symptom_type="phys_dressing").status_code == 400


def test_viewer_cannot_save(client, db, consent_docs, parent_id):
    join_family(db, client, consent_docs, parent_id, "viewer")
    assert save(client, parent_id).status_code == 403


def test_idempotent(client, db, parent_id):
    headers = {"Idempotency-Key": "sym-1"}
    body = {"symptom_type": "beh_hiding", "time_band": "night"}
    first = client.post(f"/v1/parents/{parent_id}/symptoms", json=body, headers=headers).json()
    second = client.post(f"/v1/parents/{parent_id}/symptoms", json=body, headers=headers).json()
    assert first == second
    assert sql_scalar(db, "SELECT count(*) FROM records WHERE parent_id = :p", p=parent_id) == 1


# ── 추천 칩 ──

def test_suggestions_default_when_few_records(client, db, user_id, parent_id):
    data = suggestions(client, parent_id)
    assert data["source"] == "default"
    assert [i["label"] for i in data["items"]] == [
        "밤에 헤매", "환청·환각", "길 잃음", "같은 말 반복", "화내기·폭언", "물건 숨기기",
    ]


def test_suggestions_personal_from_all_records(client, db, user_id, parent_id):
    # 텍스트·음성 분류 기록도 집계 (증상 기록만 X)
    for _ in range(3):
        add_classified_text(db, parent_id, user_id, "beh_going_out")
    for _ in range(2):
        add_classified_text(db, parent_id, user_id, "cog_date_disorient")
    # 신체 항목 → 후보 X
    add_classified_text(db, parent_id, user_id, "phys_dressing")
    # 오래된 기록 → 제외
    add_classified_text(db, parent_id, user_id, "beh_breaking", days_ago=120)

    data = suggestions(client, parent_id)
    assert data["source"] == "personal"
    codes = [i["symptom_type"] for i in data["items"]]
    assert codes[:2] == ["beh_going_out", "cog_date_disorient"]
    # 나머지 → 기본 키워드로 채움
    assert codes[2:] == ["beh_irregular_sleep", "beh_hallucination", "beh_wandering", "cog_short_memory"]
    assert data["items"][0]["record_count"] == 3


def test_suggestions_ignore_excluded(client, db, user_id, parent_id):
    for _ in range(5):
        add_classified_text(db, parent_id, user_id, "beh_going_out")
    run_sql(db, "UPDATE records SET status = 'excluded' WHERE parent_id = :p", p=parent_id)
    assert suggestions(client, parent_id)["source"] == "default"


# ── 최근 4주 ──

def test_weekly_sums_counts_by_week(client, db, user_id, parent_id):
    now = datetime.now(timezone.utc)
    this_monday = symptom_service.week_start(now.astimezone(KST).date())
    # 이번 주: 지금 직전 (월요일 0시 직후 실행돼도 이번 주)
    save(client, parent_id, occurrence_count=3, occurred_at=(now - timedelta(seconds=2)).isoformat())
    save(client, parent_id, occurrence_count=1, occurred_at=(now - timedelta(seconds=1)).isoformat())
    save(client, parent_id, occurrence_count=2, occurred_at=(this_monday - timedelta(days=13)).isoformat())
    # 4주 전 → 제외 / 다른 증상 → 제외
    save(client, parent_id, occurrence_count=5, occurred_at=(this_monday - timedelta(days=22)).isoformat())
    save(client, parent_id, symptom_type="beh_wandering", occurrence_count=4)

    response = weekly(client, parent_id, symptom_type="beh_hiding")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["label"] == "물건 숨기기"
    assert [w["count"] for w in data["weeks"]] == [0, 2, 0, 4]
    assert data["weeks"][-1]["week_start"] == this_monday.date().isoformat()


def test_weekly_custom_by_label(client, db, user_id, parent_id):
    save(client, parent_id, symptom_type="custom", custom_label="밥 거부", occurrence_count=2)
    save(client, parent_id, symptom_type="custom", custom_label="잠꼬대", occurrence_count=7)
    data = weekly(client, parent_id, symptom_type="custom", custom_label="밥 거부").json()["data"]
    assert data["weeks"][-1]["count"] == 2
    assert weekly(client, parent_id, symptom_type="custom").status_code == 400
