-- 010_deletion_options: 탈퇴·동의 철회 때 "내 기록도 모두 지우기" 선택 + 탈퇴 뒤 음성만 삭제
--
-- deletion_requests.delete_records
--   true  → 내가 쓴 기록 삭제 (기존 동작, 기존 행 기본값)
--   false → 기록(글) 가족 공간에 유지, 작성자 '탈퇴한 사용자' (탈퇴만)
--   ⚖️ 보관 근거·범위 법률 확인 전 임시
-- records.audio_deleted_at
--   탈퇴 뒤 기록은 남기고 음성 파일만 삭제한 시각 (목소리 = 작성자 개인정보)
--   음성 기록 audio_path NOT NULL·불변 규칙 유지 → 경로는 두고 이 칸으로 재생 막음

alter table public.deletion_requests
    add column delete_records boolean not null default true;

alter table public.records
    add column audio_deleted_at timestamptz;
