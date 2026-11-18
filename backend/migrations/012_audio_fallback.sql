-- 012_audio_fallback: 받아쓰기 실패 음성 기록 → 같은 기록에서 글로 적기 / 다시 녹음
--
-- guard_record_write: app.writer = 'audio_fallback' 예외 경로 추가 (그 외 규칙 그대로)
--   조건: 이전 = 음성 + 원문 없음 + failed (받아쓰기 실패)
--   글로 적기: input_type text, 음성 경로·길이 비움, 원문 = 현재 글 (비어 있지 않음)
--   다시 녹음: input_type voice 그대로, 새 음성 경로, 원문·현재 글 없음 (받아쓰기 다시)
--   recorded_at · created_at 불변 유지, text_version 유지
-- 이전 음성 파일: 서버가 업로드 행을 expired로 → 기존 정리 작업이 삭제

create or replace function public.guard_record_write()
 returns trigger
 language plpgsql
 set search_path to ''
as $function$
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

    -- 받아쓰기 실패 기록 되살리기 (글로 적기 / 다시 녹음)
    if coalesce(current_setting('app.writer', true), '') = 'audio_fallback' then
        if not (
            old.input_type = 'voice'
            and old.original_text is null
            and old.processing_status = 'failed'
        ) then
            raise exception 'audio fallback only for failed transcription';
        end if;

        if new.input_type = 'text' then
            if new.audio_path is not null
               or new.original_text is null
               or new.original_text = ''
               or new.original_text is distinct from new.current_text then
                raise exception 'audio fallback to text: text required, audio cleared';
            end if;
        elsif new.input_type = 'voice' then
            if new.audio_path is null
               or new.audio_path = old.audio_path
               or new.original_text is not null
               or new.current_text is not null then
                raise exception 'audio fallback to new audio: new path, no text';
            end if;
        else
            raise exception 'audio fallback: text or voice only';
        end if;

        new.transcript_empty := false;
        new.text_version := old.text_version;
        new.updated_at := now();
        return new;
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
$function$;
