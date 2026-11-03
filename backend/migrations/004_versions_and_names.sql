-- 004_versions_and_names: 수정 이력 버전 + 사용자 표시 이름 (A-1)
--
-- record_versions
--   version                 사용자 수정 순번 1, 2, 3… (text_version과 별개: 모든 사용자 수정)
--   changed_fields          저장 시점에 실제로 바뀐 칸 (text / source / occurred_at / item_codes)
--   classified_by_snapshot  수정 전 분류 주체 (ai / user / NULL = 분류 전)
-- users
--   display_name            본인이 정한 표시 이름 (초대·작성자 표시)
--
-- 적용 전 점검: record_versions 0건 (2026-11-03) → 기존 행 채우기 불필요

do $$
begin
    if exists (select 1 from public.record_versions) then
        raise exception '004: record_versions에 기존 행 존재, version 채우기 필요';
    end if;
end;
$$;

alter table public.record_versions
    add column version integer not null check (version >= 1),
    add column changed_fields text[] not null
        check (
            cardinality(changed_fields) >= 1
            and changed_fields <@ array['text', 'source', 'occurred_at', 'item_codes']
        ),
    add column classified_by_snapshot public.set_by_enum,
    add constraint record_versions_record_version_key unique (record_id, version);

alter table public.users
    add column display_name text
        check (display_name is null or char_length(btrim(display_name)) between 1 and 20);
