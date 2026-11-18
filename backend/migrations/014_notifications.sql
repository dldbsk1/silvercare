-- 014_notifications: 알림 목록 · 푸시 발송 · 정기 알림 (POP_A_NOTI, A-SET-002)
--
-- dedupe_key: 같은 알림 1번만 (정기 알림 중복 실행·재시도 대비). 일반 알림 → NULL
--   예: checklist_overdue:{checklist_id} / survey_briefing:{parent_id}:{date}:{user_id}
-- 목록 인덱스: 최신순 keyset (created_at desc, id desc) + 안 읽은 알림 개수
-- 내용 고정: 저장 뒤 바뀌는 값 = read_at · sent_at (한 번 정하면 그대로)

alter table public.notifications add column if not exists dedupe_key text;

create unique index if not exists notifications_dedupe_key
    on public.notifications (dedupe_key)
    where dedupe_key is not null;

drop index if exists public.idx_notifications_user;
create index if not exists notifications_user_list
    on public.notifications (user_id, created_at desc, id desc);
create index if not exists notifications_user_unread
    on public.notifications (user_id)
    where read_at is null;


create or replace function public.guard_notification()
 returns trigger
 language plpgsql
 set search_path to ''
as $function$
begin
    if new.user_id is distinct from old.user_id
        or new.parent_id is distinct from old.parent_id
        or new.type is distinct from old.type
        or new.title is distinct from old.title
        or new.body is distinct from old.body
        or new.payload is distinct from old.payload
        or new.created_at is distinct from old.created_at
        or new.dedupe_key is distinct from old.dedupe_key then
        raise exception 'notifications: immutable column';
    end if;

    if old.read_at is not null and new.read_at is distinct from old.read_at then
        raise exception 'notifications: read_at is final';
    end if;

    if old.sent_at is not null and new.sent_at is distinct from old.sent_at then
        raise exception 'notifications: sent_at is final';
    end if;

    return new;
end;
$function$;

drop trigger if exists trg_guard_notification on public.notifications;
create trigger trg_guard_notification
    before update on public.notifications
    for each row execute function public.guard_notification();
