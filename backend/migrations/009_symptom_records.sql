-- 009_symptom_records: 증상 기록 (A-SYM-001/002)
--
-- record_symptoms.symptom_type
--   조사표 항목 코드 (행동변화 14 · 인지 7 중 하나) → 기록 분류 = 그 항목 (사용자 분류)
--   'custom' → 기타(직접 입력). custom_label 필수, 분류는 AI 작업 (텍스트 기록과 같음)
-- custom_label   직접 입력 증상 이름 (1~20자)
--
-- 주간 집계 (최근 4주) · 추천 칩 조회용 인덱스

alter table public.record_symptoms
    add column custom_label text,
    add constraint record_symptoms_custom_label_len
        check (custom_label is null or char_length(custom_label) between 1 and 20),
    add constraint record_symptoms_custom_label_required
        check ((symptom_type = 'custom') = (custom_label is not null));

create index if not exists record_symptoms_type on public.record_symptoms (symptom_type);

create index if not exists record_items_code on public.record_items (item_code);
