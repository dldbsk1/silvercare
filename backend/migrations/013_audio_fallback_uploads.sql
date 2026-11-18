-- 013_audio_fallback_uploads: 글로 적기·다시 녹음 → 이전 업로드 consumed → expired (012 이어서)
--
-- guard_audio_upload: app.writer = 'audio_fallback' 일 때만 consumed → expired 허용
--   조건: 기록 연결·사용 시각 비움 (audio_uploads_state CHECK), Storage 삭제 전
--   이후 기존 정리 작업이 Storage 파일 삭제 → storage_deleted_at
-- 그 외 규칙 그대로

create or replace function public.guard_audio_upload()
 returns trigger
 language plpgsql
 set search_path to ''
as $function$
declare
    fallback boolean := coalesce(current_setting('app.writer', true), '') = 'audio_fallback';
begin
    if new.user_id is distinct from old.user_id
        or new.parent_id is distinct from old.parent_id
        or new.audio_path is distinct from old.audio_path
        or new.content_type is distinct from old.content_type
        or new.created_at is distinct from old.created_at then
        raise exception 'audio_uploads: immutable column';
    end if;

    -- 기록이 음성을 버림 (글로 적기·다시 녹음)
    if fallback and old.status = 'consumed' and new.status = 'expired' then
        if new.record_id is not null
            or new.consumed_at is not null
            or new.storage_deleted_at is not null then
            raise exception 'audio_uploads: fallback release clears record only';
        end if;
        new.updated_at := now();
        return new;
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
$function$;
