"""기록 상세 수정: 수정 순번 (edit_version) · 동시 수정 · 증상 고치기 · 조사표 항목"""
from tests.integration.conftest import join_family, sql_scalar


def create_text(client, parent_id, text="점심에 죽 드셨어요"):
    return client.post(f"/v1/parents/{parent_id}/records/text", json={"text": text}).json()["data"]["id"]


def detail(client, record_id):
    return client.get(f"/v1/records/{record_id}").json()["data"]


def patch(client, record_id, base, **body):
    return client.patch(f"/v1/records/{record_id}", json={"base_version": base, **body})


def history(client, record_id):
    return client.get(f"/v1/records/{record_id}/versions").json()["data"]


def save_symptom(client, parent_id, **body):
    payload = {"symptom_type": "beh_hiding", "time_band": "night", "occurrence_count": 2, **body}
    return client.post(f"/v1/parents/{parent_id}/symptoms", json=payload).json()["data"]["record_id"]


def patch_symptom(client, record_id, base, **body):
    return client.patch(f"/v1/records/{record_id}/symptom", json={"base_version": base, **body})


# ── 수정 순번 ──

def test_edit_version_counts_only_real_changes(client, parent_id):
    record_id = create_text(client, parent_id)
    assert detail(client, record_id)["edit_version"] == 0

    assert patch(client, record_id, 0, source="call").json()["data"]["edit_version"] == 1
    # 같은 값 → 이력·순번 그대로
    assert patch(client, record_id, 1, source="call").json()["data"]["edit_version"] == 1
    assert patch(client, record_id, 1, current_text="점심에 죽 드셨어요").json()["data"]["edit_version"] == 1

    assert patch(client, record_id, 1, item_codes=["phys_eating"]).json()["data"]["edit_version"] == 2
    # 같은 분류 (순서만 다름 포함) → 그대로
    assert patch(client, record_id, 2, item_codes=["phys_eating"]).json()["data"]["edit_version"] == 2

    data = history(client, record_id)
    assert data["edit_version"] == 2
    assert [v["changed"] for v in data["history"]] == [["item_codes"], ["source"]]
    assert data["history"][1]["before"]["source"] == "direct"


def test_stale_base_version_conflict(client, parent_id):
    record_id = create_text(client, parent_id)
    patch(client, record_id, 0, current_text="다른 기기에서 고침")

    response = patch(client, record_id, 0, current_text="이 기기에서 고침")
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "EDIT_CONFLICT"
    assert error["details"]["edit_version"] == 1
    assert detail(client, record_id)["current_text"] == "다른 기기에서 고침"

    # 오래된 순번이라도 실제 변경 없음 → 그대로 200
    assert patch(client, record_id, 0, current_text="다른 기기에서 고침").status_code == 200
    # 최신 순번 → 저장
    assert patch(client, record_id, 1, current_text="이 기기에서 고침").json()["data"]["edit_version"] == 2


def test_base_version_required(client, parent_id):
    record_id = create_text(client, parent_id)
    assert client.patch(f"/v1/records/{record_id}", json={"source": "call"}).status_code == 422
    response = client.patch(f"/v1/records/{record_id}", json={"base_version": 0})
    assert response.status_code == 400


def test_exclude_does_not_bump_edit_version(client, parent_id):
    record_id = create_text(client, parent_id)
    client.post(f"/v1/records/{record_id}/exclude")
    assert detail(client, record_id)["edit_version"] == 0


# ── 증상 고치기 ──

def test_symptom_detail_and_edit(client, parent_id):
    record_id = save_symptom(client, parent_id, note="새벽에 서랍 뒤지심")
    data = detail(client, record_id)
    assert data["symptom"] == {
        "symptom_type": "beh_hiding", "label": "물건 감추기",
        "time_band": "night", "occurrence_count": 2, "note": "새벽에 서랍 뒤지심",
    }

    response = patch_symptom(client, record_id, 0, time_band="dawn", occurrence_count=3)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["current_text"] == "물건 감추기 · 새벽 · 3번\n새벽에 서랍 뒤지심"
    assert data["symptom"]["occurrence_count"] == 3
    assert data["edit_version"] == 1
    # 조사표 항목 → 사용자 분류 유지
    assert data["classified_by"] == "user"
    assert [i["item_code"] for i in data["items"]] == ["beh_hiding"]

    # 메모 비움
    data = patch_symptom(client, record_id, 1, note="").json()["data"]
    assert data["current_text"] == "물건 감추기 · 새벽 · 3번"
    assert data["symptom"]["note"] is None

    # 같은 값 → 순번 그대로
    assert patch_symptom(client, record_id, 2, occurrence_count=3).json()["data"]["edit_version"] == 2

    versions = history(client, record_id)["history"]
    assert [v["changed"] for v in versions] == [["text"], ["text"]]
    assert versions[1]["before"]["text"] == "물건 감추기 · 밤 · 2번\n새벽에 서랍 뒤지심"


def test_symptom_edit_updates_weekly(client, parent_id):
    record_id = save_symptom(client, parent_id)
    patch_symptom(client, record_id, 0, occurrence_count=5)
    weeks = client.get(
        f"/v1/parents/{parent_id}/symptoms/weekly", params={"symptom_type": "beh_hiding"}
    ).json()["data"]["weeks"]
    assert weeks[-1]["count"] == 5


def test_symptom_edit_conflict_and_rules(client, db, consent_docs, parent_id):
    record_id = save_symptom(client, parent_id)
    patch_symptom(client, record_id, 0, occurrence_count=4)

    response = patch_symptom(client, record_id, 0, occurrence_count=6)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EDIT_CONFLICT"
    # 증상 행도 그대로 (트랜잭션 취소)
    assert sql_scalar(db, "SELECT occurrence_count FROM record_symptoms WHERE record_id = :r", r=record_id) == 4

    # 증상 기록 글 → 일반 수정 X / 출처는 일반 수정 O
    response = patch(client, record_id, 1, current_text="직접 고친 글")
    assert response.json()["error"]["code"] == "USE_SYMPTOM_EDIT"
    assert patch(client, record_id, 1, source="call").status_code == 200

    # 증상 기록 아님 → 400
    text_id = create_text(client, parent_id)
    assert patch_symptom(client, text_id, 0, occurrence_count=2).status_code == 400
    # 빈 요청 / null → 400 / 422
    assert patch_symptom(client, record_id, 2).status_code == 400
    assert patch_symptom(client, record_id, 2, time_band=None).status_code == 422

    # 작성자만
    join_family(db, client, consent_docs, parent_id, "writer")
    assert patch_symptom(client, record_id, 2, occurrence_count=1).status_code == 403


def test_symptom_custom_edit_reclassifies(client, db, parent_id):
    record_id = save_symptom(client, parent_id, symptom_type="custom", custom_label="밥 거부")
    response = patch_symptom(client, record_id, 0, occurrence_count=3)
    data = response.json()["data"]
    assert data["current_text"] == "밥 거부 · 밤 · 3번"
    assert data["processing_status"] == "pending"
    jobs = sql_scalar(
        db,
        "SELECT count(*) FROM jobs WHERE type = 'classify_record' AND target_type = 'record' AND target_id = :r",
        r=record_id,
    )
    assert jobs == 2


# ── 조사표 항목 ──

def test_survey_items(client, parent_id):
    items = client.get("/v1/survey/items").json()["data"]
    assert len(items) == 52
    assert [i["sort_order"] for i in items] == sorted(i["sort_order"] for i in items)
    assert {i["area"] for i in items} == {"physical", "cognitive", "behavior", "nursing", "rehab"}
    assert {"code": "phys_eating", "area": "physical"}.items() <= next(
        i for i in items if i["code"] == "phys_eating"
    ).items()
