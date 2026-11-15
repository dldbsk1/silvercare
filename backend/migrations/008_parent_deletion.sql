-- 008_parent_deletion: 부모님 기록 공간 삭제 (가족 자발적 삭제)
--
-- 흐름
--   pending    관리자 요청. 관리자 전원 동의 대기 (approval_deadline 지나면 expired)
--   scheduled  전원 동의 → scheduled_for (= 동의 완료 + 유예기간) 까지 읽기 전용. 관리자 누구나 취소
--   executing  예정일 지남 → 워커 선점. 실행 중 AI 작업 끝날 때까지 대기 → Storage → DB 삭제
--   completed  삭제 끝. 행은 감사 기록으로 유지 (부모님 정보 X, id·시각·건수만)
--   cancelled / expired
-- 열린 요청 (pending·scheduled·executing) 공간당 1개
--
-- target_parent_id   삭제 대상 id (FK X → 부모님 행 삭제 뒤에도 남음)
-- parent_id          FK, 삭제되면 null (열람·잠금 조회용)
-- deleted_counts     실행 결과 건수 (기록·파일). 내용 X
--
-- ⚖️ 유예기간 7일: 법률 자문 후 확정 (즉시 삭제 가능성 포함)
-- 동의 철회·부모님 본인 삭제 요구 → 유예 없는 별도 경로 (이 표 X)
--
-- deletion_requests.parent_id: 공간 삭제를 막지 않게 on delete set null 로 변경

create table public.parent_deletions (
    id uuid primary key default gen_random_uuid(),
    target_parent_id uuid not null,
    parent_id uuid references public.parents(id) on delete set null,
    requested_by uuid not null references public.users(id),
    status text not null default 'pending'
        check (status in ('pending', 'scheduled', 'executing', 'completed', 'cancelled', 'expired')),
    requested_at timestamptz not null default now(),
    approval_deadline timestamptz not null,
    scheduled_at timestamptz,
    scheduled_for timestamptz,
    cancelled_by uuid references public.users(id),
    cancelled_at timestamptz,
    completed_at timestamptz,
    deleted_counts jsonb,
    check (status <> 'scheduled' or scheduled_for is not null)
);

create unique index parent_deletions_open
    on public.parent_deletions (target_parent_id)
    where status in ('pending', 'scheduled', 'executing');

create index parent_deletions_due
    on public.parent_deletions (scheduled_for)
    where status in ('scheduled', 'executing');

create table public.parent_deletion_approvals (
    deletion_id uuid not null references public.parent_deletions(id) on delete cascade,
    user_id uuid not null references public.users(id),
    approved_at timestamptz not null default now(),
    primary key (deletion_id, user_id)
);

alter table public.parent_deletions enable row level security;
revoke all on public.parent_deletions from anon, authenticated;
alter table public.parent_deletion_approvals enable row level security;
revoke all on public.parent_deletion_approvals from anon, authenticated;

alter table public.deletion_requests
    drop constraint if exists deletion_requests_parent_id_fkey,
    add constraint deletion_requests_parent_id_fkey
        foreign key (parent_id) references public.parents(id) on delete set null;
