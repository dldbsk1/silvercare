"""알림 (POP_A_NOTI): 목록·읽음 · 저장 규칙 · 푸시 작업 · 정기 알림 · 가족 합류 · 댓글 · 기록 실패

정기 알림: 개발 DB 공용 → 반환 개수 대신 테스트 사용자별 개수로 확인
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.db import fcm
from app.services import dday, notification_service
from app.services import scheduled_notification_service as scheduled
from app.workers import worker
from app.workers.tasks import load_tasks
from tests.integration.conftest import (
    agree_all,
    claim_job,
    create_auth_user,
    fail_final,
    join_family,
    run_sql,
    sql_scalar,
)
from tests.integration.test_family import accept, new_token, share_doc  # noqa: F401


KST = timezone(timedelta(hours=9))


def count(db, user, type_):
    return sql_scalar(
        db, "SELECT count(*) FROM notifications WHERE user_id = :u AND type = :t", u=user, t=type_
    )


def add_notification(db, user, parent_id=None, title="알림", minutes_ago=0, type_="checklist_received"):
    return str(sql_scalar(
        db,
        """
            INSERT INTO notifications (user_id, parent_id, type, title, created_at)
            VALUES (:u, :p, :t, :title, now() - make_interval(mins => :m))
            RETURNING id
        """,
        u=user, p=parent_id, t=type_, title=title, m=minutes_ago
    ))


def set_setting(db, user, **values):
    base = {"condition_enabled": True, "tasks_enabled": True, "briefing_enabled": True, **values}
    run_sql(
        db,
        """
            INSERT INTO notification_settings (user_id, condition_enabled, tasks_enabled, briefing_enabled)
            VALUES (:u, :c, :t, :b)
            ON CONFLICT (user_id) DO UPDATE SET condition_enabled = :c, tasks_enabled = :t, briefing_enabled = :b
        """,
        u=user, c=base["condition_enabled"], t=base["tasks_enabled"], b=base["briefing_enabled"]
    )


def add_device(db, user, token="token-1"):
    return str(sql_scalar(
        db,
        "INSERT INTO devices (user_id, platform, push_token) VALUES (:u, 'android', :t) RETURNING id",
        u=user, t=token
    ))


def push_jobs(db, notification_id):
    return sql_scalar(
        db, "SELECT count(*) FROM jobs WHERE type = 'send_push' AND target_id = :id", id=notification_id
    )


def notify(db, user, parent_id, setting=notification_service.TASKS, dedupe_key=None):
    with db.begin():
        return notification_service.notify(
            db, user, parent_id, "checklist_received", "제목", "본문", {"checklist_id": "c1"},
            setting=setting, dedupe_key=dedupe_key,
        )


@pytest.fixture
def family(db, client, consent_docs, user_id, parent_id):
    """나(admin) + 동생(writer) + 보기 전용. 나로 로그인한 상태"""
    sibling = join_family(db, client, consent_docs, parent_id, "writer")
    viewer = join_family(db, client, consent_docs, parent_id, "viewer")
    client.login(user_id)
    return {"me": user_id, "sibling": sibling, "viewer": viewer}


# ── 목록 · 읽음 ──

def test_list_newest_first_with_cursor(client, db, user_id, parent_id):
    ids = [add_notification(db, user_id, parent_id, f"알림{i}", minutes_ago=10 - i) for i in range(3)]

    first = client.get("/v1/notifications", params={"limit": 2}).json()
    assert [n["notification_id"] for n in first["data"]] == [ids[2], ids[1]]
    assert first["meta"]["has_more"] is True
    assert first["meta"]["unread_count"] == 3

    second = client.get("/v1/notifications", params={"limit": 2, "cursor": first["meta"]["next_cursor"]}).json()
    assert [n["notification_id"] for n in second["data"]] == [ids[0]]
    assert second["meta"]["has_more"] is False


def test_cursor_of_other_user_rejected(client, db, consent_docs, user_id, parent_id):
    for i in range(3):
        add_notification(db, user_id, parent_id, minutes_ago=i)
    cursor = client.get("/v1/notifications", params={"limit": 1}).json()["meta"]["next_cursor"]

    other = join_family(db, client, consent_docs, parent_id, "writer")
    assert other
    response = client.get("/v1/notifications", params={"cursor": cursor})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CURSOR"


def test_read_one_and_all(client, db, user_id, parent_id):
    first = add_notification(db, user_id, parent_id)
    add_notification(db, user_id, parent_id)

    response = client.patch(f"/v1/notifications/{first}/read")
    assert response.status_code == 200
    read_at = response.json()["data"]["read_at"]
    assert read_at is not None
    # 다시 → 그대로
    assert client.patch(f"/v1/notifications/{first}/read").json()["data"]["read_at"] == read_at
    assert client.get("/v1/notifications").json()["meta"]["unread_count"] == 1

    assert client.post("/v1/notifications/read-all").status_code == 204
    assert client.get("/v1/notifications").json()["meta"]["unread_count"] == 0


def test_other_users_notification_404(client, db, user_id, parent_id, other_user_id):
    # 앱 프로필 (users) = 첫 요청 때 생성
    client.login(other_user_id)
    client.get("/v1/auth/me")
    client.login(user_id)
    theirs = add_notification(db, other_user_id)
    assert client.patch(f"/v1/notifications/{theirs}/read").status_code == 404
    assert client.get("/v1/notifications").json()["data"] == []


def test_left_space_notifications_hidden(client, db, family, parent_id):
    add_notification(db, family["sibling"], parent_id)
    add_notification(db, family["sibling"], None)
    run_sql(db, "DELETE FROM family_members WHERE parent_id = :p AND user_id = :u", p=parent_id, u=family["sibling"])

    client.login(family["sibling"])
    data = client.get("/v1/notifications").json()
    assert len(data["data"]) == 1
    assert data["data"][0]["parent_id"] is None
    assert data["meta"]["unread_count"] == 1


def test_home_unread_count(client, db, user_id, parent_id):
    add_notification(db, user_id, parent_id)
    home = client.get(f"/v1/parents/{parent_id}/home").json()["data"]
    assert home["unread_notifications"] == 1


def test_content_immutable(db, user_id, parent_id):
    notification_id = add_notification(db, user_id, parent_id)
    with pytest.raises(Exception, match="immutable"):
        run_sql(db, "UPDATE notifications SET title = '바꿈' WHERE id = :id", id=notification_id)


# ── 저장 규칙 · 푸시 작업 등록 ──

def test_setting_off_not_stored(db, user_id, parent_id):
    set_setting(db, user_id, tasks_enabled=False)
    assert notify(db, user_id, parent_id) is None
    # 스위치 없는 알림 → 저장
    assert notify(db, user_id, parent_id, setting=None) is not None


def test_dedupe_key_once(db, user_id, parent_id):
    assert notify(db, user_id, parent_id, dedupe_key="test:1") is not None
    assert notify(db, user_id, parent_id, dedupe_key="test:1") is None
    assert count(db, user_id, "checklist_received") == 1


def test_push_job_only_with_target(db, monkeypatch, user_id, parent_id):
    # 발송 꺼짐 (기본 none) → 작업 X
    first = notify(db, user_id, parent_id)
    assert push_jobs(db, first) == 0

    monkeypatch.setattr(settings, "PUSH_PROVIDER", "fcm")
    # 기기 없음 → 작업 X
    second = notify(db, user_id, parent_id)
    assert push_jobs(db, second) == 0

    add_device(db, user_id)
    third = notify(db, user_id, parent_id)
    assert push_jobs(db, third) == 1


def test_push_job_needs_noti_consent(db, client, monkeypatch, consent_docs, user_id, parent_id):
    monkeypatch.setattr(settings, "PUSH_PROVIDER", "fcm")
    add_device(db, user_id)
    assert client.post("/v1/consents/noti/revoke", json={}).status_code == 200
    notification_id = notify(db, user_id, parent_id)
    assert notification_id is not None
    assert push_jobs(db, notification_id) == 0


# ── 푸시 발송 (send_push) ──

def run_push(db, notification_id):
    load_tasks()
    job = claim_job(db, notification_id, notification_service.SEND_PUSH_JOB)
    worker.run_job(db, job)
    return job


def push_ready(db, monkeypatch, user_id, parent_id, tokens=("token-1",)):
    monkeypatch.setattr(settings, "PUSH_PROVIDER", "fcm")
    devices = [add_device(db, user_id, t) for t in tokens]
    return notify(db, user_id, parent_id), devices


def job_status(db, job):
    return sql_scalar(db, "SELECT status FROM jobs WHERE id = :id", id=job.id)


def test_send_push_marks_sent(db, monkeypatch, user_id, parent_id):
    notification_id, _ = push_ready(db, monkeypatch, user_id, parent_id)
    sent = []
    monkeypatch.setattr(fcm, "send", lambda token, title, body, data: sent.append((token, data)) or fcm.Result.SENT)

    job = run_push(db, notification_id)

    assert job_status(db, job) == "completed"
    assert sent[0][0] == "token-1"
    assert sent[0][1]["type"] == "checklist_received"
    assert sent[0][1]["checklist_id"] == "c1"
    assert sql_scalar(db, "SELECT sent_at IS NOT NULL FROM notifications WHERE id = :id", id=notification_id)


def test_send_push_invalid_token_revokes_device(db, monkeypatch, user_id, parent_id):
    notification_id, devices = push_ready(db, monkeypatch, user_id, parent_id, ("bad", "good"))
    monkeypatch.setattr(
        fcm, "send", lambda token, *a: fcm.Result.INVALID if token == "bad" else fcm.Result.SENT
    )

    run_push(db, notification_id)

    assert sql_scalar(db, "SELECT revoked_at IS NOT NULL FROM devices WHERE id = :id", id=devices[0])
    assert sql_scalar(db, "SELECT revoked_at IS NULL FROM devices WHERE id = :id", id=devices[1])
    assert sql_scalar(db, "SELECT sent_at IS NOT NULL FROM notifications WHERE id = :id", id=notification_id)


def test_send_push_retry_when_all_fail(db, monkeypatch, user_id, parent_id):
    notification_id, _ = push_ready(db, monkeypatch, user_id, parent_id)
    monkeypatch.setattr(fcm, "send", lambda *a: fcm.Result.RETRY)

    job = run_push(db, notification_id)

    assert job_status(db, job) == "queued"
    assert sql_scalar(db, "SELECT sent_at IS NULL FROM notifications WHERE id = :id", id=notification_id)


def test_send_push_skips_read(db, monkeypatch, client, user_id, parent_id):
    notification_id, _ = push_ready(db, monkeypatch, user_id, parent_id)
    client.patch(f"/v1/notifications/{notification_id}/read")
    calls = []
    monkeypatch.setattr(fcm, "send", lambda *a: calls.append(a) or fcm.Result.SENT)

    job = run_push(db, notification_id)

    assert job_status(db, job) == "completed"
    assert calls == []


# ── 정기 알림 (시각 = 지금 시각으로 바꿔서) ──

@pytest.fixture
def now_hour(monkeypatch):
    hour = datetime.now(KST).hour
    monkeypatch.setattr(scheduled, "OVERDUE_HOUR", hour)
    monkeypatch.setattr(scheduled, "BRIEFING_HOUR", hour)
    monkeypatch.setattr(scheduled, "CONDITION_HOUR", hour)
    return hour


def run_scheduled(db, job):
    with db.begin():
        return job(db)


def add_checklist(db, parent_id, from_user, to_user, due):
    return str(sql_scalar(
        db,
        """
            INSERT INTO checklists (parent_id, from_user_id, to_user_id, due_date)
            VALUES (:p, :f, :t, :d) RETURNING id
        """,
        p=parent_id, f=from_user, t=to_user, d=due
    ))


def test_checklist_overdue_once(db, family, parent_id, now_hour):
    yesterday = dday.today_kst() - timedelta(days=1)
    add_checklist(db, parent_id, family["me"], family["sibling"], yesterday)
    # 오늘까지 → 아직 X
    add_checklist(db, parent_id, family["me"], family["sibling"], dday.today_kst())

    run_scheduled(db, scheduled.checklist_overdue)
    run_scheduled(db, scheduled.checklist_overdue)
    assert count(db, family["sibling"], "checklist_overdue") == 1


def test_checklist_overdue_skips_submitted_and_late(db, family, parent_id, now_hour):
    yesterday = dday.today_kst() - timedelta(days=1)
    checklist = add_checklist(db, parent_id, family["me"], family["sibling"], yesterday)
    run_sql(db, "UPDATE checklists SET submitted_at = now() WHERE id = :id", id=checklist)
    # 3시간 넘게 지난 것 X
    add_checklist(db, parent_id, family["me"], family["sibling"], yesterday - timedelta(days=1))

    run_scheduled(db, scheduled.checklist_overdue)
    assert count(db, family["sibling"], "checklist_overdue") == 0


def test_survey_briefing_all_family(client, db, family, parent_id, now_hour):
    tomorrow = dday.today_kst() + timedelta(days=1)
    response = client.patch(f"/v1/parents/{parent_id}", json={"survey_date": tomorrow.isoformat()})
    assert response.status_code == 200, response.json()
    set_setting(db, family["viewer"], briefing_enabled=False)

    run_scheduled(db, scheduled.survey_briefing)
    run_scheduled(db, scheduled.survey_briefing)
    assert count(db, family["me"], "survey_briefing") == 1
    assert count(db, family["sibling"], "survey_briefing") == 1
    assert count(db, family["viewer"], "survey_briefing") == 0


def test_condition_reminder(db, monkeypatch, family, parent_id, now_hour):
    assert run_scheduled(db, scheduled.condition_reminder) == 0  # 기본 꺼짐

    monkeypatch.setattr(settings, "CONDITION_REMINDER_ENABLED", True)
    run_scheduled(db, scheduled.condition_reminder)
    # 관리자·쓰기만
    assert count(db, family["me"], "condition_reminder") == 1
    assert count(db, family["sibling"], "condition_reminder") == 1
    assert count(db, family["viewer"], "condition_reminder") == 0


def test_condition_reminder_skips_recorded_day(db, monkeypatch, family, parent_id, now_hour):
    monkeypatch.setattr(settings, "CONDITION_REMINDER_ENABLED", True)
    enum_type = sql_scalar(
        db, "SELECT udt_name FROM information_schema.columns WHERE table_name = 'conditions' AND column_name = 'value'"
    )
    run_sql(
        db,
        f"""
            INSERT INTO conditions (parent_id, author_id, date, value)
            VALUES (:p, :a, (now() AT TIME ZONE 'Asia/Seoul')::date,
                    (enum_range(NULL::public.{enum_type}))[1])
        """,
        p=parent_id, a=family["me"]
    )
    run_scheduled(db, scheduled.condition_reminder)
    assert count(db, family["me"], "condition_reminder") == 0


# ── 가족 합류 ──

def test_family_joined_notifies_admins(client, db, consent_docs, share_doc, user_id, parent_id):  # noqa: F811
    token = new_token(client, parent_id)
    joiner = create_auth_user(db)
    client.login(joiner)
    agree_all(client, consent_docs)
    client.patch("/v1/auth/me", json={"display_name": "동생"})

    assert accept(client, token).status_code == 200
    assert count(db, user_id, "family_joined") == 1
    assert count(db, joiner, "family_joined") == 0
    title = sql_scalar(db, "SELECT title FROM notifications WHERE user_id = :u AND type = 'family_joined'", u=user_id)
    assert title == "동생님이 가족으로 들어왔어요"


# ── 댓글 ──

def add_text_record(client, parent_id, text="엄마가 아침을 드셨어요"):
    response = client.post(f"/v1/parents/{parent_id}/records/text", json={"text": text})
    assert response.status_code == 201, response.json()
    return response.json()["data"]["id"]


def test_comment_notifies_author(client, db, family, parent_id):
    record_id = add_text_record(client, parent_id)

    client.login(family["sibling"])
    response = client.post(f"/v1/records/{record_id}/comments", json={"body": "  저도 봤어요  "})
    assert response.status_code == 201, response.json()
    comment = response.json()["data"]
    assert comment["body"] == "저도 봤어요"
    assert comment["is_mine"] is True

    assert count(db, family["me"], "record_comment") == 1

    # 내 기록에 내 댓글 → 알림 X
    client.login(family["me"])
    client.post(f"/v1/records/{record_id}/comments", json={"body": "고마워요"})
    assert count(db, family["me"], "record_comment") == 1

    response = client.get(f"/v1/records/{record_id}/comments").json()
    assert response["meta"]["can_comment"] is True
    listed = response["data"]
    assert [c["body"] for c in listed] == ["저도 봤어요", "고마워요"]
    assert [c["is_mine"] for c in listed] == [False, True]


def test_comment_permissions(client, db, family, parent_id, other_user_id):
    record_id = add_text_record(client, parent_id)
    mine = client.post(f"/v1/records/{record_id}/comments", json={"body": "메모"}).json()["data"]

    client.login(family["viewer"])
    viewer_list = client.get(f"/v1/records/{record_id}/comments")
    assert viewer_list.status_code == 200
    assert viewer_list.json()["meta"]["can_comment"] is False
    assert client.post(f"/v1/records/{record_id}/comments", json={"body": "보기"}).status_code == 403

    client.login(family["sibling"])
    assert client.delete(f"/v1/records/{record_id}/comments/{mine['comment_id']}").status_code == 403

    client.login(family["me"])
    assert client.post(f"/v1/records/{record_id}/comments", json={"body": "   "}).status_code == 422
    assert client.delete(f"/v1/records/{record_id}/comments/{mine['comment_id']}").status_code == 204
    assert client.get(f"/v1/records/{record_id}/comments").json()["data"] == []


# ── 기록 실패 ──

def test_record_failed_notifies_author(client, db, user_id, parent_id):
    record_id = add_text_record(client, parent_id)
    job = claim_job(db, record_id, "classify_record", 1)
    fail_final(db, job, "CLASSIFY_FAILED")

    assert count(db, user_id, "record_failed") == 1
    payload = sql_scalar(
        db, "SELECT payload->>'record_id' FROM notifications WHERE user_id = :u AND type = 'record_failed'", u=user_id
    )
    assert payload == record_id
