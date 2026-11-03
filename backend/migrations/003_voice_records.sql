-- 003_voice_records: 음성 기록 (A-HOME-001)
--
-- audio_uploads   업로드 발급·사용·만료 관리 (소유권 검증, 고아 파일 정리)
-- records
--   transcript_empty   STT 성공 + 말소리 없음 (원문 '')
--   processing_error   실패 코드. processing_status = failed 일 때만
--   audio_path         UNIQUE (파일 1개 = 기록 1개)
-- jobs
--   lease_token        작업 소유권. 회수 시 재발급 → 이전 워커 무효
--   받아쓰기 작업       기록당 활성 1개
-- 트리거
--   protect + text_version → guard_record_write 하나로 통합
--
-- 적용 전 점검: 음성 기록 0건, audio_path 중복 0건, 원문 없는 텍스트 기록 0건 (2026-11-03)

-- ── 안전장치: 중복 audio_path → 전체 취소 ──
do $$
begin
    if exists (
        select 1 from public.records
        where audio_path is not null
        group by audio_path having count(*) > 1
    ) then
        raise exception '003: records.audio_path 중복 존재';
    end if;
end;
$$;

-- ── records ──
alter table public.records
    add column transcript_empty boolean not null default false,
    add column processing_error text
        check (processing_error is null or char_length(processing_error) between 1 and 100),
    add constraint records_transcript_empty_voice
        check (not transcript_empty or (input_type = 'voice' and original_text = '')),
    add constraint records_processing_error_failed
        check ((processing_status = 'failed') = (processing_error is not null)),
    add constraint records_voice_audio
        check (input_type <> 'voice' or (audio_path is not null and audio_duration_seconds is not null)),
    add constraint records_voice_text_pair
        check (input_type <> 'voice' or ((original_text is null) = (current_text is null)));

create unique index records_audio_path_key on public.records (audio_path)
    where audio_path is not null;

-- ── records 트리거 통합 ──
-- INSERT
--   text_version 1
--   voice → 원문·현재 글 NULL, pending, 오류·분류 없음, transcript_empty false
-- UPDATE
--   recorded_at·created_at·input_type·audio_path 불변
--   original_text 변경 → 최초 받아쓰기만 허용 (아래 조건 전부), 버전 유지
--     app.writer = 'transcription' (set_config 트랜잭션 한정)
--     voice + 기존 원문·현재 글 NULL + 새 원문 NOT NULL + 새 원문 = 새 현재 글
--   current_text 변경 → 원문 있을 때만, 버전 +1
--   transcript_empty → 최초 받아쓰기에서만 변경
create or replace function public.guard_record_write()
returns trigger
language plpgsql
set search_path to ''
as $$
begin
    if tg_op = 'INSERT' then
        new.text_version := 1;
        new.transcript_empty := false;
        if new.input_type = 'voice' then
            new.original_text := null;
            new.current_text := null;
            new.processing_status := 'pending';
            new.processing_error := null;
            new.classification_status := null;
            new.classified_by := null;
        end if;
        return new;
    end if;

    if new.recorded_at is distinct from old.recorded_at then
        raise exception 'recorded_at is immutable';
    end if;
    if new.created_at is distinct from old.created_at then
        raise exception 'created_at is immutable';
    end if;
    if new.input_type is distinct from old.input_type then
        raise exception 'input_type is immutable';
    end if;
    if new.audio_path is distinct from old.audio_path then
        raise exception 'audio_path is immutable';
    end if;

    if new.original_text is distinct from old.original_text then
        if not (
            coalesce(current_setting('app.writer', true), '') = 'transcription'
            and old.input_type = 'voice'
            and old.original_text is null
            and old.current_text is null
            and new.original_text is not null
            and new.original_text is not distinct from new.current_text
        ) then
            raise exception 'original_text cannot be changed after first assignment';
        end if;
        new.text_version := old.text_version;

    else
        if new.transcript_empty is distinct from old.transcript_empty then
            raise exception 'transcript_empty is set only by transcription';
        end if;

        if new.current_text is distinct from old.current_text then
            if old.original_text is null then
                raise exception 'current_text cannot be changed before transcription';
            end if;
            new.text_version := old.text_version + 1;
        else
            new.text_version := old.text_version;
        end if;
    end if;

    new.updated_at := now();
    return new;
end;
$$;

drop trigger trg_record_protection on public.records;
drop trigger trg_record_text_version on public.records;
drop function public.enforce_record_text_version();
drop function public.protect_record_original_fields();

create trigger trg_record_guard
    before insert or update on public.records
    for each row execute function public.guard_record_write();

-- ── audio_uploads ──
-- issued → consumed (기록 생성) / issued → expired (정리 대상)
-- consumed: 만료와 무관하게 정리 대상 아님
create table public.audio_uploads (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.users(id),
    parent_id uuid not null references public.parents(id) on delete cascade,
    audio_path text not null unique check (length(btrim(audio_path)) > 0),
    content_type text not null,
    status text not null default 'issued'
        check (status in ('issued', 'consumed', 'expired')),
    expires_at timestamptz not null,
    record_id uuid unique references public.records(id),
    consumed_at timestamptz,
    storage_deleted_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint audio_uploads_state check (
        (status = 'issued'
            and consumed_at is null and record_id is null and storage_deleted_at is null)
        or (status = 'consumed'
            and consumed_at is not null and record_id is not null and storage_deleted_at is null)
        or (status = 'expired'
            and consumed_at is null and record_id is null)
    )
);

-- 정리 대상 조회
create index audio_uploads_cleanup_idx on public.audio_uploads (expires_at)
    where status = 'issued' or (status = 'expired' and storage_deleted_at is null);

create or replace function public.guard_audio_upload()
returns trigger
language plpgsql
set search_path to ''
as $$
begin
    if new.user_id is distinct from old.user_id
        or new.parent_id is distinct from old.parent_id
        or new.audio_path is distinct from old.audio_path
        or new.content_type is distinct from old.content_type
        or new.created_at is distinct from old.created_at then
        raise exception 'audio_uploads: immutable column';
    end if;

    if new.status is distinct from old.status
        and not (old.status = 'issued' and new.status in ('consumed', 'expired')) then
        raise exception 'audio_uploads: % → % not allowed', old.status, new.status;
    end if;

    if old.status = 'consumed' and (
        new.record_id is distinct from old.record_id
        or new.consumed_at is distinct from old.consumed_at
    ) then
        raise exception 'audio_uploads: consumed is final';
    end if;

    if old.storage_deleted_at is not null
        and new.storage_deleted_at is distinct from old.storage_deleted_at then
        raise exception 'audio_uploads: storage_deleted_at is final';
    end if;

    new.updated_at := now();
    return new;
end;
$$;

create trigger trg_audio_upload_guard
    before update on public.audio_uploads
    for each row execute function public.guard_audio_upload();

alter table public.audio_uploads enable row level security;
revoke all on public.audio_uploads from anon, authenticated;

-- ── jobs ──
alter table public.jobs add column lease_token uuid;

create unique index jobs_one_active_transcription on public.jobs (target_id)
    where type = 'transcribe_record' and status in ('queued', 'running');
