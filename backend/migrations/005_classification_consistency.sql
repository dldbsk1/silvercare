-- 005_classification_consistency: 분류 상태 ↔ 분류 항목 일치 (A-2 미분류 필터 전제)
--
-- 규칙 (트랜잭션 끝에 검사, DEFERRABLE INITIALLY DEFERRED)
--   completed + 항목 1개 이상 → classified
--   completed + 항목 없음     → unclassified
--   그 외 (pending / processing / failed) → classification_status NULL + 항목 없음
-- 대상: 워커 (분류·받아쓰기), 사용자 PATCH, 재분류 → 모두 같은 트랜잭션에서 항목 + 상태 변경
--
-- 적용 전 점검: records 0건 (2026-11-07) → 기존 행 정리 불필요

do $$
begin
    if exists (
        select 1
        from public.records r
        where case
            when r.processing_status = 'completed' then
                r.classification_status is null
                or (r.classification_status = 'classified')
                   <> exists (select 1 from public.record_items ri where ri.record_id = r.id)
            else
                r.classification_status is not null
                or exists (select 1 from public.record_items ri where ri.record_id = r.id)
        end
    ) then
        raise exception '005: 분류 상태와 항목이 맞지 않는 기록 존재, 정리 필요';
    end if;
end;
$$;

create or replace function public.check_record_classification()
returns trigger
language plpgsql
as $$
declare
    target_id uuid;
    rec record;
    has_items boolean;
begin
    if tg_table_name = 'records' then
        target_id := new.id;
    elsif tg_op = 'DELETE' then
        target_id := old.record_id;
    else
        target_id := new.record_id;
    end if;

    select r.processing_status, r.classification_status
    into rec
    from public.records r
    where r.id = target_id;

    -- 기록 삭제됨 → 검사 대상 없음
    if not found then
        return null;
    end if;

    has_items := exists (
        select 1 from public.record_items ri where ri.record_id = target_id
    );

    if rec.processing_status = 'completed' then
        if rec.classification_status is null
           or (rec.classification_status = 'classified') <> has_items then
            raise exception 'record % 분류 상태 불일치: completed, %, 항목 %',
                target_id, rec.classification_status, has_items
                using errcode = 'check_violation';
        end if;
    elsif rec.classification_status is not null or has_items then
        raise exception 'record % 분류 상태 불일치: %, %, 항목 %',
            target_id, rec.processing_status, rec.classification_status, has_items
            using errcode = 'check_violation';
    end if;

    return null;
end;
$$;

create constraint trigger records_classification_consistent
    after insert or update of processing_status, classification_status
    on public.records
    deferrable initially deferred
    for each row
    execute function public.check_record_classification();

create constraint trigger record_items_classification_consistent
    after insert or update or delete
    on public.record_items
    deferrable initially deferred
    for each row
    execute function public.check_record_classification();
