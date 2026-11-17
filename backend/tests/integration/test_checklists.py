"""관찰 체크리스트 (A-TASK, SCR_A_310): 고르기·추천 · 보내기 · 답 · 제출 → 기록 · 권한 · 자동 취소"""
from datetime import timedelta

import pytest

from app.services import dday
from tests.integration.conftest import join_family, patch_record, run_sql, sql_scalar


TOILET = "phys_toilet_use"    # adl
EATING = "phys_eating"        # adl
WANDER = "beh_wandering"      # yesno
DATE = "cog_date_disorient"   # yesno
REHAB = "reh_joint_knee"      # 재활 (대상 아님)


def today():
    return dday.today_kst()


def error_code(response):
    return response.json()["error"]["code"]


def send(client, parent_id, to_user, codes, due=None, key=None):
    headers = {"Idempotency-Key": key} if key else {}
    return client.post(
        f"/v1/parents/{parent_id}/checklists",
        json={"to_user_id": to_user, "item_codes": codes,
              "due_date": (due or today() + timedelta(days=7)).isoformat()},
        headers=headers,
    )


def sent(client, parent_id, to_user, codes, **kw):
    response = send(client, parent_id, to_user, codes, **kw)
    assert response.status_code == 201, response.json()
    return response.json()["data"]


def detail(client, checklist_id):
    return client.get(f"/v1/checklists/{checklist_id}")


def answer(client, checklist, code, value, note=None):
    task = next(i for i in checklist["items"] if i["item_code"] == code)
    return client.put(
        f"/v1/checklists/{checklist['id']}/items/{task['task_id']}/answer",
        json={"answer": value, "note": note},
    )


def submit(client, checklist_id):
    return client.post(f"/v1/checklists/{checklist_id}/submit")


def draft(client, parent_id):
    response = client.get(f"/v1/parents/{parent_id}/checklists/draft")
    assert response.status_code == 200, response.json()
    return response.json()["data"]


def draft_items(data):
    return {i["item_code"]: i for a in data["areas"] for i in a["items"]}


def add_record(client, db, parent_id, code, days_ago=0):
    """항목 분류된 정상 기록 1건 (days_ago 일 전). API 대신 SQL 한 번 (테스트 속도)"""
    author = sql_scalar(
        db, "SELECT user_id FROM family_members WHERE parent_id = :p AND role = 'admin' LIMIT 1",
        p=parent_id
    )
    return str(sql_scalar(
        db,
        """
            WITH r AS (
                INSERT INTO records (
                    parent_id, author_id, input_type, source, original_text, current_text,
                    recorded_at, occurred_at,
                    processing_status, classification_status, classified_by
                )
                VALUES (
                    :p, :a, 'text', 'direct', '기록', '기록',
                    now(), now() - make_interval(days => :d),
                    'completed', 'classified', 'ai'
                )
                RETURNING id
            ), i AS (
                INSERT INTO record_items (record_id, item_code, confidence, set_by)
                SELECT id, :c, 0.9, 'ai' FROM r
            )
            SELECT id FROM r
        """,
        p=parent_id, a=author, d=days_ago, c=code
    ))


def notifications(db, user, type_):
    return sql_scalar(
        db, "SELECT count(*) FROM notifications WHERE user_id = :u AND type = :t", u=user, t=type_
    )


@pytest.fixture
def family(db, client, consent_docs, user_id, parent_id):
    """나(admin) + 동생(writer) + 보기 전용. 나로 로그인한 상태"""
    sibling = join_family(db, client, consent_docs, parent_id, "writer")
    viewer = join_family(db, client, consent_docs, parent_id, "viewer")
    client.login(user_id)
    return {"me": user_id, "sibling": sibling, "viewer": viewer}


# ── 고르기 목록 · 추천 ──

def test_draft_items_and_last_recorded(client, db, user_id, parent_id):
    add_record(client, db, parent_id, TOILET, days_ago=40)
    excluded = add_record(client, db, parent_id, EATING, days_ago=1)
    run_sql(db, "UPDATE records SET status = 'excluded' WHERE id = :id", id=excluded)

    data = draft(client, parent_id)

    assert [a["area"] for a in data["areas"]] == ["physical", "cognitive", "behavior", "nursing"]
    assert [a["label"] for a in data["areas"]] == ["신체", "인지", "행동변화", "간호처치"]
    items = draft_items(data)
    assert len(items) == 42 and REHAB not in items
    assert items[TOILET]["label"] == "화장실 사용하기"
    assert items[TOILET]["hint"] == "혼자 화장실에 가시는지"
    assert items[TOILET]["last_recorded_on"] == (today() - timedelta(days=40)).isoformat()
    # 제외 기록 안 셈
    assert items[EATING]["last_recorded_on"] is None


def test_draft_suggestion_order(client, db, consent_docs, user_id, parent_id):
    # 2일 이상 → 충분 / 1일 → 부족 / 나머지 0일
    covered = [c for c in draft_items(draft(client, parent_id)) if c != EATING]
    for code in covered:
        add_record(client, db, parent_id, code, days_ago=1)
        add_record(client, db, parent_id, code, days_ago=3)
    add_record(client, db, parent_id, EATING, days_ago=2)

    data = draft(client, parent_id)
    # 기록 0일 항목 없음 → 1일 (식사하기)만
    assert data["suggested_codes"] == [EATING]
    assert draft_items(data)[EATING]["reason"] == "few_records"
    assert draft_items(data)[TOILET]["reason"] is None

    # 열린 체크리스트에 든 항목 → 추천 X
    sent(client, parent_id, user_id, [EATING])
    assert draft(client, parent_id)["suggested_codes"] == []


def test_draft_not_seen_comes_back(client, db, user_id, parent_id):
    for code in draft_items(draft(client, parent_id)):
        add_record(client, db, parent_id, code, days_ago=1)
        add_record(client, db, parent_id, code, days_ago=3)

    checklist = sent(client, parent_id, user_id, [WANDER])
    answer(client, checklist, WANDER, "not_seen")
    assert submit(client, checklist["id"]).status_code == 200

    data = draft(client, parent_id)
    assert data["suggested_codes"] == [WANDER]
    assert draft_items(data)[WANDER]["reason"] == "not_seen_before"


def test_draft_new_space_mixes_areas(client, user_id, parent_id):
    codes = draft(client, parent_id)["suggested_codes"]
    assert codes == [
        "phys_dressing", "phys_wash_face",
        "cog_short_memory", "cog_date_disorient",
        "beh_delusion", "beh_hallucination",
    ]


# ── 보내기 ──

def test_create_and_detail(client, db, family, parent_id):
    data = sent(client, parent_id, family["sibling"], [WANDER, TOILET])

    assert data["status"] == "pending"
    assert (data["answered_items"], data["total_items"]) == (0, 2)
    assert data["from_user"]["is_me"] and not data["is_recipient"]
    # 조사표 순서 (신체 → 행동변화)
    assert [i["item_code"] for i in data["items"]] == [TOILET, WANDER]
    toilet, wander = data["items"]
    assert toilet["choices"] == ["alone", "little", "full", "not_seen"]
    assert wander["choices"] == ["yes", "no", "not_seen"]
    assert wander["hint"] == "익숙한 곳에서 길을 잃으신 적 있는지"
    assert notifications(db, family["sibling"], "checklist_received") == 1


def test_create_to_self_no_notification(client, db, user_id, parent_id):
    data = sent(client, parent_id, user_id, [TOILET])
    assert data["is_recipient"]
    assert notifications(db, user_id, "checklist_received") == 0


def test_recipient_rules(client, family, parent_id, other_user_id):
    assert error_code(send(client, parent_id, family["viewer"], [TOILET])) == "RECIPIENT_NOT_WRITER"
    # 가족 아님
    assert error_code(send(client, parent_id, other_user_id, [TOILET])) == "RECIPIENT_NOT_WRITER"

    client.login(family["viewer"])
    assert send(client, parent_id, family["me"], [TOILET]).status_code == 403


@pytest.mark.parametrize("codes, status", [
    ([REHAB], 422),
    (["nope"], 422),
    ([TOILET, TOILET], 422),
    ([], 422),
    ([TOILET] * 11, 422),
])
def test_create_item_rules(client, user_id, parent_id, codes, status):
    assert send(client, parent_id, user_id, codes).status_code == status


def test_due_date_range(client, user_id, parent_id):
    assert error_code(send(client, parent_id, user_id, [TOILET], due=today() - timedelta(days=1))) == "INVALID_DUE_DATE"
    assert error_code(send(client, parent_id, user_id, [TOILET], due=today() + timedelta(days=31))) == "INVALID_DUE_DATE"
    assert send(client, parent_id, user_id, [TOILET], due=today()).status_code == 201
    assert send(client, parent_id, user_id, [EATING], due=today() + timedelta(days=30)).status_code == 201


def test_create_idempotent(client, db, user_id, parent_id):
    first = sent(client, parent_id, user_id, [TOILET], key="k1")
    second = sent(client, parent_id, user_id, [TOILET], key="k1")
    assert first["id"] == second["id"]
    assert sql_scalar(db, "SELECT count(*) FROM checklists WHERE parent_id = :p", p=parent_id) == 1


# ── 조회 권한 ──

def test_only_sender_and_recipient_can_view(client, db, consent_docs, family, parent_id):
    checklist = sent(client, parent_id, family["sibling"], [TOILET])

    client.login(family["viewer"])
    assert error_code(detail(client, checklist["id"])) == "CHECKLIST_NOT_FOUND"

    client.login(family["sibling"])
    assert detail(client, checklist["id"]).json()["data"]["is_recipient"]


def test_sender_sees_answers_before_submit(client, family, parent_id):
    checklist = sent(client, parent_id, family["sibling"], [TOILET, EATING])

    client.login(family["sibling"])
    assert answer(client, checklist, TOILET, "little", "밤에는 부축이 필요해요").status_code == 200

    client.login(family["me"])
    data = detail(client, checklist["id"]).json()["data"]
    assert data["status"] == "in_progress" and data["answered_items"] == 1
    items = {item["item_code"]: item for item in data["items"]}
    assert (items[TOILET]["answer"], items[TOILET]["note"]) == ("little", "밤에는 부축이 필요해요")
    assert items[EATING]["answer"] is None


# ── 답 ──

def test_answer_rules(client, db, family, parent_id):
    checklist = sent(client, parent_id, family["sibling"], [TOILET, WANDER])

    # 보낸 사람은 답 X
    assert error_code(answer(client, checklist, TOILET, "alone")) == "NOT_RECIPIENT"

    client.login(family["sibling"])
    # 척도에 안 맞는 답
    assert error_code(answer(client, checklist, TOILET, "yes")) == "INVALID_ANSWER"
    assert error_code(answer(client, checklist, WANDER, "little")) == "INVALID_ANSWER"

    first = answer(client, checklist, TOILET, "alone").json()["data"]
    assert first["answered_items"] == 1
    # 같은 답 → 답한 시각 그대로
    again = answer(client, checklist, TOILET, "alone").json()["data"]
    assert again["item"]["answered_at"] == first["item"]["answered_at"]
    # 덮어쓰기 + 빈 메모 → null
    changed = answer(client, checklist, TOILET, "full", "").json()["data"]["item"]
    assert (changed["answer"], changed["note"]) == ("full", None)

    # 다른 체크리스트의 항목
    other = sent(client, parent_id, family["sibling"], [EATING])
    task_id = other["items"][0]["task_id"]
    response = client.put(
        f"/v1/checklists/{checklist['id']}/items/{task_id}/answer", json={"answer": "alone"}
    )
    assert response.status_code == 404


# ── 제출 → 기록 ──

def test_submit_creates_records(client, db, family, parent_id):
    checklist = sent(client, parent_id, family["sibling"], [TOILET, WANDER, DATE])

    client.login(family["sibling"])
    answer(client, checklist, TOILET, "little", "밤에는 부축이 필요해요")
    answer(client, checklist, WANDER, "no")
    answer(client, checklist, DATE, "not_seen")

    response = submit(client, checklist["id"])
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "submitted"
    by_code = {i["item_code"]: i for i in data["items"]}
    assert by_code[DATE]["record_id"] is None

    toilet = client.get(f"/v1/records/{by_code[TOILET]['record_id']}").json()["data"]
    assert toilet["input_type"] == "checklist" and toilet["source"] == "direct"
    assert toilet["current_text"] == "화장실 사용하기 — 조금 도와드림. 밤에는 부축이 필요해요"
    assert toilet["classified_by"] == "user"
    assert [i["item_code"] for i in toilet["items"]] == [TOILET]
    assert toilet["is_mine"]

    wander = client.get(f"/v1/records/{by_code[WANDER]['record_id']}").json()["data"]
    assert wander["current_text"] == "길을 잃음 — 없었어요"

    assert sql_scalar(
        db, "SELECT count(*) FROM records WHERE parent_id = :p AND input_type = 'checklist'", p=parent_id
    ) == 2
    assert notifications(db, family["me"], "checklist_submitted") == 1

    # 다시 제출 → 같은 응답, 기록 그대로
    assert submit(client, checklist["id"]).status_code == 200
    assert sql_scalar(
        db, "SELECT count(*) FROM records WHERE parent_id = :p AND input_type = 'checklist'", p=parent_id
    ) == 2
    # 제출 뒤 답 X
    assert error_code(answer(client, checklist, TOILET, "alone")) == "CHECKLIST_SUBMITTED"

    client.login(family["me"])
    assert detail(client, checklist["id"]).json()["data"]["status"] == "submitted"


def test_submit_incomplete(client, user_id, parent_id):
    checklist = sent(client, parent_id, user_id, [TOILET, EATING])
    answer(client, checklist, TOILET, "alone")

    response = submit(client, checklist["id"])
    assert error_code(response) == "INCOMPLETE_ANSWERS"
    eating = next(i for i in checklist["items"] if i["item_code"] == EATING)
    assert response.json()["error"]["details"]["task_ids"] == [eating["task_id"]]


def test_checklist_record_item_fixed(client, user_id, parent_id):
    checklist = sent(client, parent_id, user_id, [TOILET])
    answer(client, checklist, TOILET, "alone")
    record_id = submit(client, checklist["id"]).json()["data"]["items"][0]["record_id"]
    url = f"/v1/records/{record_id}"

    assert error_code(patch_record(client, url, {"item_codes": [EATING]})) == "CHECKLIST_ITEM_FIXED"
    assert patch_record(client, url, {"item_codes": [TOILET]}).status_code == 200
    assert patch_record(client, url, {"current_text": "화장실 혼자 다녀오심"}).status_code == 200


def test_status_overdue(client, db, user_id, parent_id):
    checklist = sent(client, parent_id, user_id, [TOILET])
    run_sql(db, "UPDATE checklists SET due_date = due_date - 30 WHERE id = :id", id=checklist["id"])

    assert detail(client, checklist["id"]).json()["data"]["status"] == "overdue"
    answer(client, checklist, TOILET, "alone")
    assert submit(client, checklist["id"]).status_code == 200


def test_recipient_downgraded_to_viewer(client, db, family, parent_id):
    checklist = sent(client, parent_id, family["sibling"], [TOILET])
    client.login(family["sibling"])
    answer(client, checklist, TOILET, "alone")
    run_sql(
        db, "UPDATE family_members SET role = 'viewer' WHERE parent_id = :p AND user_id = :u",
        p=parent_id, u=family["sibling"]
    )
    assert submit(client, checklist["id"]).status_code == 403


# ── 목록 ──

def test_list_boxes(client, family, parent_id):
    later = sent(client, parent_id, family["sibling"], [TOILET], due=today() + timedelta(days=9))
    sooner = sent(client, parent_id, family["sibling"], [EATING], due=today() + timedelta(days=2))
    mine = sent(client, parent_id, family["me"], [WANDER])
    answer(client, mine, WANDER, "yes")
    submit(client, mine["id"])

    def ids(**params):
        body = client.get(f"/v1/parents/{parent_id}/checklists", params=params).json()
        return [c["id"] for c in body["data"]], body["meta"]["total"]

    # 보낸 전체: 열린 것 확인 날짜 순 → 완료
    assert ids(box="sent", state="all") == ([sooner["id"], later["id"], mine["id"]], 3)
    assert ids(box="sent", state="done") == ([mine["id"]], 1)
    assert ids(box="received", state="open") == ([], 0)

    client.login(family["sibling"])
    assert ids(box="received", state="open") == ([sooner["id"], later["id"]], 2)


# ── 공간 삭제 예정 · 자동 취소 ──

def test_parent_deletion_locks_writes(client, user_id, parent_id):
    checklist = sent(client, parent_id, user_id, [TOILET])
    assert client.post(f"/v1/parents/{parent_id}/deletion").status_code == 201

    assert error_code(send(client, parent_id, user_id, [EATING])) == "PARENT_DELETION_SCHEDULED"
    assert client.get(f"/v1/parents/{parent_id}/checklists/draft").status_code == 409
    assert error_code(answer(client, checklist, TOILET, "alone")) == "PARENT_DELETION_SCHEDULED"
    assert detail(client, checklist["id"]).status_code == 200


def test_leaving_family_cancels_open(client, db, family, parent_id):
    to_sibling = sent(client, parent_id, family["sibling"], [TOILET])
    to_me = sent(client, parent_id, family["me"], [EATING])

    client.login(family["sibling"])
    member_id = next(
        m["member_id"] for m in client.get(f"/v1/parents/{parent_id}/family").json()["data"]
        if m["user_id"] == family["sibling"]
    )
    assert client.delete(f"/v1/family/{member_id}").status_code == 204

    client.login(family["me"])
    assert detail(client, to_sibling["id"]).json()["data"]["status"] == "cancelled"
    assert detail(client, to_me["id"]).json()["data"]["status"] == "pending"
    assert notifications(db, family["me"], "checklist_cancelled") == 1


def test_home_received_count(client, family, parent_id):
    sent(client, parent_id, family["sibling"], [TOILET])
    done = sent(client, parent_id, family["sibling"], [EATING])

    client.login(family["sibling"])
    answer(client, done, EATING, "alone")
    submit(client, done["id"])
    home = client.get(f"/v1/parents/{parent_id}/home").json()["data"]
    assert home["received_checklists_open"] == 1
