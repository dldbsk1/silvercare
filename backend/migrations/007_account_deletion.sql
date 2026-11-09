-- 007_account_deletion: 탈퇴·동의 철회 삭제 예약 (A-5, A-SET-001/003)
--
-- users.withdrawn_at          탈퇴 접수 시각. 이후 /auth/me 외 API 403 ACCOUNT_WITHDRAWN
--                             삭제 실행 뒤에도 행 유지 (다른 가족 기록의 수정 이력·초대 기록 참조)
-- deletion_requests
--   scheduled_for             삭제 예정 시각 (접수 + 유예기간). ⚖️ 유예기간 법률 확인 전 임시
--   parent_ids                탈퇴 시 혼자 쓰던 부모님 → 삭제 실행 때 공간 전체 삭제
-- deletion_status_enum
--   cancelled                 예정일 전 필수 동의 다시 함 (철회 예약 취소)
--                             같은 트랜잭션에서 새 값 사용 불가 → 아래 인덱스는 다른 값만 사용
-- 열린 요청 (requested·approved) 사람·종류당 1개
--
-- 적용 전 점검: deletion_requests 0건 (2026-11-09) → scheduled_for NOT NULL 바로 추가

do $$
begin
    if exists (select 1 from public.deletion_requests) then
        raise exception '007: deletion_requests에 기존 행 존재, scheduled_for 채우기 필요';
    end if;
end;
$$;

alter type public.deletion_status_enum add value if not exists 'cancelled';

alter table public.users
    add column withdrawn_at timestamptz;

alter table public.deletion_requests
    add column scheduled_for timestamptz not null,
    add column parent_ids uuid[] not null default '{}';

create unique index deletion_requests_open
    on public.deletion_requests (requester_id, request_type)
    where status in ('requested', 'approved');

create index deletion_requests_due
    on public.deletion_requests (scheduled_for)
    where status in ('requested', 'approved');
