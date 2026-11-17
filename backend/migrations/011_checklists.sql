-- 011_checklists: 관찰 체크리스트 (A-TASK, SCR_A_310)
--
-- task_answer_enum: yes / no 추가 (인지·행동변화·간호처치 30항목: 있었어요 / 없었어요)
--   신체 12항목: alone / little / full (기존) · 공통: not_seen
--   ⚠️ ADD VALUE → 같은 트랜잭션에서 새 값 사용 불가 → 이 파일에서 'yes'·'no' 쓰는 CHECK·데이터 X
-- survey_items.observation_hint: 짧은 설명 (고르기 화면, 보낼 때 tasks.question 으로 복사)
--   가족 체크리스트 대상 42개 필수 / 재활 10개 제외 (family_checklist = false)
-- checklists.cancelled_at: 자동 취소 (보낸·받은 사람 가족 나가기·탈퇴). 사용자 취소 기능 없음
-- tasks.note: "한 줄 덧붙이기" 200자 (항목 중복 방지는 기존 uq_tasks_checklist_item)

alter type public.task_answer_enum add value if not exists 'yes';
alter type public.task_answer_enum add value if not exists 'no';


-- ── 설명 문구 (초안, 팀 검토. DB 값이라 배포 없이 수정 가능) ──

alter table public.survey_items
    add column if not exists observation_hint text;

update public.survey_items si
set observation_hint = v.hint
from (values
    ('phys_dressing',         '옷을 혼자 벗고 입으시는지'),
    ('phys_wash_face',        '혼자 세수하시는지'),
    ('phys_brush_teeth',      '혼자 양치하시는지'),
    ('phys_bathing',          '혼자 목욕하시는지'),
    ('phys_eating',           '혼자 식사하시는지'),
    ('phys_reposition',       '누워서 혼자 돌아누우시는지'),
    ('phys_sit_up',           '누웠다가 혼자 일어나 앉으시는지'),
    ('phys_transfer',         '침대에서 의자로 혼자 옮겨 앉으시는지'),
    ('phys_go_outside_room',  '방 밖으로 혼자 나오시는지'),
    ('phys_toilet_use',       '혼자 화장실에 가시는지'),
    ('phys_bowel_control',    '대변을 실수 없이 보시는지'),
    ('phys_bladder_control',  '소변을 실수 없이 보시는지'),
    ('cog_short_memory',      '방금 한 일을 금방 잊으신 적 있는지'),
    ('cog_date_disorient',    '날짜나 요일을 헷갈려 하신 적 있는지'),
    ('cog_place_disorient',   '계신 곳을 헷갈려 하신 적 있는지'),
    ('cog_age_dob_disorient', '나이나 생일을 잘못 말씀하신 적 있는지'),
    ('cog_instruction',       '간단한 부탁을 못 알아들으신 적 있는지'),
    ('cog_judgment',          '위험한 상황을 알아차리지 못하신 적 있는지'),
    ('cog_communication',     '하고 싶은 말을 전하지 못하신 적 있는지'),
    ('beh_delusion',          '도둑맞았다는 등 사실이 아닌 일을 믿으신 적 있는지'),
    ('beh_hallucination',     '없는 것이 보이거나 들린다고 하신 적 있는지'),
    ('beh_sad_crying',        '이유 없이 슬퍼하거나 우신 적 있는지'),
    ('beh_irregular_sleep',   '밤낮이 바뀌어 주무신 적 있는지'),
    ('beh_resist_help',       '도와드릴 때 거부하신 적 있는지'),
    ('beh_restless',          '안절부절못하고 서성이신 적 있는지'),
    ('beh_wandering',         '익숙한 곳에서 길을 잃으신 적 있는지'),
    ('beh_verbal_abuse',      '큰소리치거나 위협하신 적 있는지'),
    ('beh_going_out',         '이유 없이 밖으로 나가려 하신 적 있는지'),
    ('beh_breaking',          '물건을 던지거나 망가뜨리신 적 있는지'),
    ('beh_meaningless',       '상황에 맞지 않는 행동을 반복하신 적 있는지'),
    ('beh_hiding',            '돈이나 물건을 숨기고 못 찾으신 적 있는지'),
    ('beh_improper_dress',    '옷을 겹쳐 입거나 거꾸로 입으신 적 있는지'),
    ('beh_incontinence_act',  '대소변을 만지거나 아무 데나 보신 적 있는지'),
    ('nur_tracheostomy',      '목의 숨 쉬는 관을 관리해 드린 적 있는지'),
    ('nur_suction',           '가래를 기계로 빼 드린 적 있는지'),
    ('nur_oxygen',            '산소 기계를 쓰신 적 있는지'),
    ('nur_wound',             '욕창 소독이나 드레싱을 해 드린 적 있는지'),
    ('nur_tube_feeding',      '코나 배의 관으로 영양을 드신 적 있는지'),
    ('nur_cancer_pain',       '암 통증 때문에 통증 관리를 받으신 적 있는지'),
    ('nur_catheter',          '소변줄을 쓰신 적 있는지'),
    ('nur_ostomy',            '장루 주머니를 관리해 드린 적 있는지'),
    ('nur_dialysis',          '투석을 받으신 적 있는지')
) as v(code, hint)
where si.code = v.code;

alter table public.survey_items
    add constraint ck_survey_items_hint
    check (not family_checklist or observation_hint is not null);


-- ── 체크리스트 묶음 ──

alter table public.checklists
    add column if not exists cancelled_at timestamptz;

alter table public.checklists
    add constraint ck_checklists_closed_once
    check (submitted_at is null or cancelled_at is null);

create index if not exists ix_checklists_to
    on public.checklists (parent_id, to_user_id, created_at desc);
create index if not exists ix_checklists_from
    on public.checklists (parent_id, from_user_id, created_at desc);


-- ── 항목 ──

alter table public.tasks
    add column if not exists note text;

alter table public.tasks
    add constraint ck_tasks_note_length check (char_length(note) <= 200);

-- 체크리스트 안 항목 중복 방지: 기존 uq_tasks_checklist_item (unique index, checklist_id 있는 행) 그대로

create index if not exists ix_tasks_checklist on public.tasks (checklist_id);

-- "못 봤어요" 재추천 ('not_seen'은 기존 값 → 이 파일에서 사용 가능)
create index if not exists ix_tasks_not_seen
    on public.tasks (parent_id, item_code, done_at)
    where answer = 'not_seen';
