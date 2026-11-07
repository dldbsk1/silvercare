-- 006_family_invites: 가족 초대·공유 동의·마지막 관리자 보호·요청 제한 (A-3)
--
-- family_invites
--   share_confirmed_at   초대한 관리자의 확인 시각 (부모님·대리인에게 가족 공유 동의 받음)
--   intended_role        writer / viewer만 (관리자는 가족이 된 뒤 역할 변경으로)
-- family_members
--   share_doc_version / share_agreed_at   초대받은 사람의 가족 공유 동의 (부모님별)
--                                         부모님을 직접 등록한 관리자 → NULL
-- consent_type_enum
--   family_share         가족 공유 동의 문서 (가입 동의 목록 X, 초대 수락 때만)
--                        같은 트랜잭션에서 새 값 사용 불가 → 문서는 seed_dev_consents로
-- rate_limits            고정 구간 요청 횟수 (서버 여러 대 공유). 워커가 하루 지난 구간 삭제
--
-- 마지막 관리자 보호 (트랜잭션 끝 검사, DEFERRABLE INITIALLY DEFERRED)
--   대상: 역할 변경 · 구성원 삭제 (내보내기·나가기·계정 삭제 연쇄) · 부모님 생성
--   부모님 행 삭제됨 (공간 삭제 연쇄) → 검사 X
--
-- 적용 전 점검: family_invites 0건 (2026-11-07) → share_confirmed_at NOT NULL 바로 추가

do $$
begin
    if exists (select 1 from public.family_invites) then
        raise exception '006: family_invites에 기존 행 존재, share_confirmed_at 채우기 필요';
    end if;
    if exists (
        select 1 from public.parents p
        where not exists (
            select 1 from public.family_members fm
            where fm.parent_id = p.id and fm.role = 'admin'
        )
    ) then
        raise exception '006: 관리자 없는 부모님 존재, 정리 필요';
    end if;
end;
$$;

alter type public.consent_type_enum add value if not exists 'family_share';

alter table public.family_invites
    add column share_confirmed_at timestamptz not null,
    add constraint family_invites_role_not_admin check (intended_role <> 'admin');

create index family_invites_active_by_parent
    on public.family_invites (parent_id)
    where accepted_at is null and revoked_at is null;

alter table public.family_members
    add column share_doc_version text,
    add column share_agreed_at timestamptz,
    add constraint family_members_share_pair
        check ((share_doc_version is null) = (share_agreed_at is null));

create table public.rate_limits (
    key text not null,
    window_start timestamptz not null,
    count integer not null default 1 check (count >= 1),
    primary key (key, window_start)
);

alter table public.rate_limits enable row level security;

create or replace function public.check_parent_has_admin()
returns trigger
language plpgsql
as $$
declare
    target_id uuid;
begin
    if tg_table_name = 'parents' then
        target_id := new.id;
    elsif tg_op = 'DELETE' then
        target_id := old.parent_id;
    else
        target_id := new.parent_id;
    end if;

    -- 부모님 공간 삭제 (연쇄 삭제) → 검사 대상 없음
    if not exists (select 1 from public.parents where id = target_id) then
        return null;
    end if;

    if not exists (
        select 1 from public.family_members
        where parent_id = target_id and role = 'admin'
    ) then
        raise exception 'parent % 관리자 없음 (마지막 관리자 보호)', target_id
            using errcode = 'check_violation';
    end if;

    return null;
end;
$$;

create constraint trigger parents_has_admin
    after insert
    on public.parents
    deferrable initially deferred
    for each row
    execute function public.check_parent_has_admin();

create constraint trigger family_members_last_admin
    after update of role or delete
    on public.family_members
    deferrable initially deferred
    for each row
    execute function public.check_parent_has_admin();
