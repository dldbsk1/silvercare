-- 002_records_classification: 기록 분류 상태 + 글 버전
--
-- records 상태 칸
--   status                기록 사용 여부 (normal / excluded)
--   processing_status     AI 분석 진행 (pending / processing / completed / failed)
--   classification_status 분류 결과 (classified / unclassified / NULL = 분석 전)
--   classified_by         분류 결정 주체 (ai / user / NULL). user → AI 재분류 금지
--   text_version          current_text 버전. 트리거 전용, 앱에서 변경 불가
--
-- jobs.status: superseded 추가 (글이 바뀌어 결과를 버린 작업)

create type public.classification_status_enum as enum ('classified', 'unclassified');

alter table public.records
    add column classification_status public.classification_status_enum,
    add column classified_by public.set_by_enum,
    add column text_version integer not null default 1 check (text_version >= 1),
    add constraint records_classification_pair
        check ((classification_status is null) = (classified_by is null));

-- text_version 강제
--   INSERT → 항상 1
--   UPDATE → current_text 실제 변경 시에만 +1, 그 외 기존 값 유지 (앱이 보낸 값 무시)
create or replace function public.enforce_record_text_version()
returns trigger
language plpgsql
as $$
begin
    if tg_op = 'INSERT' then
        new.text_version := 1;
    elsif new.current_text is distinct from old.current_text then
        new.text_version := old.text_version + 1;
    else
        new.text_version := old.text_version;
    end if;
    return new;
end;
$$;

create trigger trg_record_text_version
    before insert or update on public.records
    for each row execute function public.enforce_record_text_version();

alter table public.jobs drop constraint jobs_status_check;
alter table public.jobs add constraint jobs_status_check
    check (status in ('queued', 'running', 'completed', 'failed', 'superseded'));
