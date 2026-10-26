-- 001_jobs: 비동기 작업 큐 (Postgres 기반)
-- 대상: STT·분류·단톡방 처리·기록지 생성
-- 기록지 생성 상태 조회: 이 테이블 사용 (reports.generation_status 대신)
-- 적용: 개발 DB 적용 완료. 운영 프로젝트 생성 시 재적용

create table public.jobs (
    id uuid primary key default gen_random_uuid(),
    type text not null check (char_length(type) between 1 and 100),
    payload jsonb not null default '{}'::jsonb,
    status text not null default 'queued'
        check (status in ('queued', 'running', 'completed', 'failed')),
    attempts integer not null default 0 check (attempts >= 0),
    max_attempts integer not null default 3 check (max_attempts >= 1),
    run_at timestamptz not null default now(),
    locked_at timestamptz,
    last_error text,
    -- 상태 조회 대상: record / report / import_job
    target_type text,
    target_id uuid,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    completed_at timestamptz,
    check ((target_type is null) = (target_id is null))
);

-- 워커: 실행할 작업 찾기
create index jobs_ready_idx on public.jobs (run_at)
    where status in ('queued', 'running');

-- 리소스별 최근 작업 조회
create index jobs_target_idx on public.jobs (target_type, target_id, created_at desc);

-- 다른 테이블과 동일: FastAPI(서버)만 접근
alter table public.jobs enable row level security;
revoke all on public.jobs from anon, authenticated;
