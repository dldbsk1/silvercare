# 실버케어 백엔드 TODO

> 기준 문서: 기능명세서 · API 명세서 · Backend Architecture · ERD
> 범례: `[x]` 완료 · `[ ]` 할 일 · 👤 담당이 백엔드가 아님(앱·웹·AI·설정) · ⚖️ 법률/정책 결정 필요

---

## 지금 바로 할 일

- [ ] 0~1단계 작업 커밋·푸시 (`dldbsk` 브랜치) — GitHub에는 첫 업로드만 올라가 있음
- [ ] `python -m scripts.smoke_test` 실제 계정으로 실행해서 전부 PASS 확인
- [ ] 앱·웹 팀에 공유: 모든 경로가 `/v1` 아래로 이동 (`/auth/me` → `/v1/auth/me`)
- [ ] API 명세서 4.2 수정: 음성 기록은 multipart 대신 "업로드 URL 발급 → Storage 직접 업로드 → `audio_path` JSON 전달"
- [ ] AI 팀원에게 `backend/app/ai/interfaces.py` 공유하고 함수 모양 합의

## 결정이 필요한 것

- [ ] ⚖️ 필수 동의 철회 시 데이터 삭제 시점·범위 (A-SET-001 "예: 7일 뒤") — API 명세서 14.3: 개발자 임의 결정 금지
- [ ] ⚖️ 실제 동의 문구 4종 (서비스·개인정보·건강정보·알림) 확정
- [ ] ⚖️ 부모님 본인 동의·대리 동의 방식 (POL-05, `care_subject_authorizations`)
- [ ] P0에서 부모님 1명만 등록하도록 서버에서 막을지 (현재는 여러 명 허용, P2 기능)
- [ ] STT·LLM 제공업체 선택 (Whisper / Clova / Google) — AI 팀원과
- [ ] 백엔드 배포처 (Railway / Render / Fly.io)
- [ ] 단톡방 원문을 외부 AI에 보낼 범위 (다른 가족 개인정보 포함, API 명세서 10장)

---

## 0단계 · 기반

### 구조
- [x] 폴더 구조 정리 (`api/v1`, `core`, `db`, `models`, `schemas`, `services`, `repositories`, `ai`, `workers`)
- [x] 버전 경로는 `api/v1` 아래만, `/health`는 버전 밖
- [x] `.env`를 실행 위치와 상관없이 `backend/.env`에서 읽기
- [x] `requirements.txt`, `.env.example`, `pytest.ini`
- [x] GitHub 연결 (`main` 빈 브랜치, `dldbsk` 작업 브랜치)

### 공통 응답·오류
- [x] 공통 응답 형식 `{"data", "meta"}`
- [x] 공통 오류 형식 `{"error": {"code", "message", "details"}}`
- [x] 401 / 403 / 404 / 422 / 409 코드 변환
- [x] 예상 못 한 오류 → 500 `INTERNAL_ERROR` (내부 정보 숨김, 로그 기록)
- [x] DB·Storage·Auth 장애 → 503 `SERVICE_UNAVAILABLE`
- [ ] 429 `RATE_LIMITED` 요청 제한 (베타 후반)

### 인증·권한
- [x] Supabase 토큰 확인 (Auth 서버 장애는 401이 아니라 503)
- [x] 첫 요청 때 `public.users` 프로필 자동 생성
- [x] 가족 권한 의존성 `ReadAccess` / `WriteAccess` / `AdminAccess` (가족 아님 404)
- [x] 필수 동의 확인 의존성 `ConsentedUser`
- [ ] URL에 `parent_id`가 없는 API(`/records/{id}` 등)용 "리소스 → 부모님 → 권한" 헬퍼 (2단계에서)
- [ ] 작성자 본인만 수정 규칙 (타인 기록은 admin도 수정 불가, 댓글만)
- [ ] (나중) JWT 서버 직접 검증으로 바꿔 Auth 서버 호출 줄이기

### 비동기 작업
- [x] Postgres 작업 큐 `jobs` 테이블 (`migrations/001_jobs.sql`, DB 적용됨)
- [x] `enqueue()` — 저장과 작업 등록을 한 트랜잭션으로
- [x] 워커 `python -m app.workers.worker` (재시도 30초→2분→8분, 멈춘 작업 회수)
- [x] 작업 상태 조회 `get_latest_job()`
- [ ] 정기 작업 기능 (단톡방 후보 24시간 삭제, 알림 예약 발송, 만료 키 정리)

### Storage
- [x] 비공개 버킷 `audio`(10MB, 음성) · `kakao-imports`(20MB, txt) — `scripts/setup_storage.py`
- [x] 음성 서명 업로드 URL `POST /v1/parents/{id}/records/audio/upload-url`
- [x] 업로드 파일 경로·존재 확인 `verify_uploaded_audio()`
- [ ] 음성 재생용 서명 다운로드 URL (A-DET-001, P1)

### 기타 기반
- [x] `Idempotency-Key` 처리 (같은 요청 재전송 시 첫 응답 반환, 7일 보관)
- [x] AI 연동 계약 `ai/interfaces.py` + 임시 구현 `ai/stub.py` + 교체 지점 `ai/provider.py`
- [x] 개발용 동의 문구 `dev-0.1` (`scripts/seed_dev_consents.py`, 운영에서 실행·사용 차단)
- [x] 단위 테스트 + 실제 DB 통합 테스트(롤백) + `scripts/smoke_test.py`
- [ ] 웹(React)용 CORS 설정 (3단계 웹 연동 전)

---

## 1단계 · 가입 흐름 (P0)

- [x] `GET /v1/auth/me` — 동의 완료 여부, 빠진 필수 동의, 부모님 등록 여부, `parent_ids`
- [x] A-ON-002 `GET /v1/consents/required` — 유효 문구·버전·필수 여부
- [x] A-ON-002 `POST /v1/consents` — 동의 저장
  - [x] 공개된 문구 버전만 허용 (임의 버전 거부)
  - [x] 필수 비동의 거부 (403 `CONSENT_REQUIRED`)
  - [x] 같은 동의 재전송 시 중복 저장 안 함
  - [x] 문구가 새 버전이 되면 다시 동의 필요
- [x] A-SET-001 `GET /v1/consents/me` — 현재 동의 + 이력
- [x] A-SET-001 `POST /v1/consents/{type}/revoke` — 철회 (이력은 남김)
  - [x] 필수 동의 철회 → 기록 기능 중지
  - [ ] ⚖️ 철회 시 데이터 삭제 예약 + 삭제 예정일 안내
- [x] A-ON-003 `POST /v1/parents` — 부모님 등록, 만든 사람 = 관리자 (한 트랜잭션, `Idempotency-Key`)
  - [x] 호칭 1~20자, 나이대·신청 단계 값 검증
  - [x] 이름·주민번호 저장 안 함 (POL-07)
- [x] `GET /v1/parents`, `GET /v1/parents/{id}`
- [ ] 👤 Supabase에서 카카오 로그인·휴대폰 OTP 공급자 설정 (A-ON-001)
- [ ] 👤 Flutter: 인증번호 3분 제한·재발송, 이미 가입한 번호 → 로그인 전환

---

## 2단계 · 기록 + AI 분류 (P0 핵심)

### 텍스트 기록 — A-HOME-002/003
- [ ] `POST /v1/parents/{id}/records/text` (`WriteAccess`, `Idempotency-Key`)
  - [ ] 1~1000자, 공백만 입력 거부
  - [ ] 출처 미선택 시 `direct`, 일반 입력에서 `kakao` 금지
  - [ ] `recorded_at`(기기 시각) / `occurred_at`(사건 시각) 구분, 비정상적인 미래 시각 처리
  - [ ] 원문 먼저 저장 → 분류 작업 등록 (한 트랜잭션), 분류가 실패해도 기록은 남음

### 음성 기록 — A-HOME-001/003
- [ ] `POST /v1/parents/{id}/records/audio` — `audio_path` JSON (`Idempotency-Key`)
  - [ ] 경로·파일 존재 확인, 길이 2~180초, 출처 `direct|call`
  - [ ] 기록 저장(처리 중) → 받아쓰기 작업 등록
- [ ] 👤 Flutter: 1회 탭 녹음, 3분 자동 종료, 2초 미만 취소, 전화 수신 일시정지, 마이크 권한
- [ ] 👤 Flutter: 오프라인 저장 → 연결 후 같은 `Idempotency-Key`로 전송

### 처리 작업 (워커)
- [ ] `transcribe_record`: Storage에서 음성 → STT → 원문 저장 → 분류 작업 등록
- [ ] `classify_record`: 분류 → `record_items` 저장 (52항목 코드만, 확신 낮으면 미분류)
- [ ] 실패 시 `processing_status=failed`, 원문·음성은 유지
- [ ] 작업을 멱등하게 (두 번 실행돼도 결과 같게)

### 상태·재시도 — A-HOME-004/005
- [ ] `GET /v1/records/{id}/processing` — 진행 상태 + 분류 결과 (저장 확인 카드용)
- [ ] `POST /v1/records/{id}/reclassify` — 분류 재시도
- [ ] 홈 최근 기록 3건 (A-HOME-009 일부, P0)

### AI 연결
- [ ] 👤 AI 팀원: STT·분류 구현 → `ai/provider.py` 교체
- [ ] 👤 AI 팀원: 테스트 문장 20개 중 16개 이상 정확 분류 (완료 기준)
- [ ] 외부 AI로 보내는 정보 최소화, 학습 미사용 옵션 확인

### 완료 기준 (기능명세서)
- [ ] 1분 녹음 종료 후 10초 안에 저장 확인 카드
- [ ] 인터넷 끄고 기록해도 연결 후 사라지지 않음
- [ ] 글을 고쳐도 원문을 다시 볼 수 있음 (6단계 수정 API와 함께)

---

## 3단계 · 웹 근거 현황판·타임라인 (P0)

### 근거 현황판 — W-DASH-001/002
- [ ] `GET /v1/parents/{id}/coverage` — 52항목별 기록 수·최근일·충분/부족/없음
  - [ ] 충분 = 최근 30일 서로 다른 날 2건 이상 (팀 기준 확정)
  - [ ] 제외(`excluded`)·처리 미완료 기록 빼기, 요약 총 기록 수는 중복 제거
  - [ ] 점수·등급 절대 반환 안 함 (POL-03)
- [ ] `GET /v1/parents/{id}/coverage/{item_code}/records` — 그 칸을 만든 기록만
- [ ] 기록 0건 항목 → "이런 장면을 보세요" 예시 문장 (항목별 관찰 문구 데이터 필요)

### 타임라인 — W-TL-001/002
- [ ] `GET /v1/parents/{id}/timeline` — 영역별 날짜별 기록 수 + 컨디션 띠 (기간 1m/3m/6m/all)
  - [ ] 기록 7일 미만이면 `insufficient=true`
  - [ ] 좋은 날도 함께 표시 (편향 방지)
- [ ] `POST /v1/parents/{id}/events` — 낙상·입원·퇴원·약 변경·기타
- [ ] `GET /v1/events/{id}/compare` — 사건 전후 30일 기록 건수 (해석 문구 없음)

### 완료 기준
- [ ] 앱에서 기록 → 웹 새로고침 시 숫자 반영, 3초 안에 로딩
- [ ] 칸을 누르면 그 칸을 만든 기록만 나옴
- [ ] 화면 어디에도 점수·등급 없음

---

## 4단계 · 카카오 단톡방 불러오기 (P0) — W-UP

- [ ] `POST /v1/parents/{id}/imports` — React → FastAPI 업로드 (multipart, 202)
  - [ ] `.txt`만, 20MB 이하 (초과 시 기간 줄이라고 안내), 동의 체크 필수, 기간 1~60개월(기본 6)
  - [ ] 원본을 `kakao-imports` 버킷에 저장 → 작업 등록
- [ ] 워커 `import_kakao`
  - [ ] 안드로이드·아이폰·PC 내보내기 날짜 형식 모두 해석
  - [ ] 날짜·보낸 사람·문장 분리, 사진·이모티콘 줄 건너뛰기
  - [ ] AI로 부모님 관련 문장만 후보로 + 추천 항목
  - [ ] 진행률 (`processed_messages / total_messages`)
  - [ ] **성공·실패 상관없이 원본 즉시 삭제**, 삭제 시각 기록 (삭제 실패 시 완료 처리 안 함)
- [ ] `GET /v1/imports/{job_id}` — 상태·진행률·원본 삭제 여부
- [ ] `GET /v1/imports/{job_id}/candidates` — 후보 목록 (후보 0건 안내)
- [ ] `POST /v1/imports/{job_id}/save` — 체크한 후보만 기록으로
  - [ ] 출처 `kakao`, 날짜 = 원래 대화 시각, 작성자 = 올린 사람
- [ ] 저장 안 한 후보 24시간 뒤 삭제 (정기 작업)
- [ ] 👤 React: 내보내기 안내 이미지, 동의 문구, 처리 중 화면

### 완료 기준
- [ ] 안드로이드·아이폰 파일 둘 다 읽힘
- [ ] 처리 후 서버에 원본 파일이 남지 않음
- [ ] 체크하지 않은 문장은 어디에도 저장되지 않음

---

## 5단계 · 조사원 전달 기록지 (P0) — W-REP

- [ ] `POST /v1/parents/{id}/reports` — 초안 생성 작업 등록 (202, 기간 기본 3개월)
- [ ] 기록지 생성 상태 조회 API (`jobs` 테이블 사용, 지난 결정)
- [ ] 워커 `generate_report`: 항목별 기록 모아 AI 요약 + 근거 기록 연결 (`report_item_sources`)
  - [ ] 기록 없는 항목은 비워 둠, 기록에 없는 내용 생성 금지, 점수·등급 문구 금지
- [ ] `GET /v1/parents/{id}/reports` — 초안·확정본 목록
- [ ] `GET /v1/reports/{id}` — 항목 문장 + 문장별 근거 기록
- [ ] `PATCH /v1/reports/{id}/items/{item_id}` — 문장 수정, 빼기, 세부사항(200자)
  - [ ] 근거 없이 가족이 쓴 문장은 `is_family_added=true`
- [ ] `POST /v1/reports/{id}/confirm` — "내용을 확인했고 제가 작성했습니다" 체크 + admin만 확정
- [ ] `GET /v1/reports/{id}/pdf` — 확정본만 (확정 전 403 `NOT_CONFIRMED`)
  - [ ] A4 1~2장, 12pt 이상, 흑백 구분, 2장 초과 시 축약 안내
  - [ ] 제목 "가족이 작성한 평소 관찰 기록", 하단 "이 기록은 가족의 관찰이며 판정은 공단이 합니다"
  - [ ] 좋은 날·나쁜 날 차이, 복용약 목록 포함
- [ ] `POST /v1/reports/{id}/revisions` — 확정본 기반 새 버전 초안
- [ ] W-REP-003 세부사항 AI 후보 문장 (P1)
- [ ] W-REP-006 `PUT /v1/reports/{id}/top5` — 꼭 전할 5가지 (P1, 5개 초과 불가)

### 완료 기준
- [ ] 모든 문장을 눌러 근거 기록을 볼 수 있음
- [ ] 기록 없는 항목에 AI가 내용을 지어내지 않음
- [ ] 확정 전에는 인쇄·PDF 막힘
- [ ] 흑백 인쇄해도 영역 구분이 보임

---

## 6단계 · P1 (MVP)

### 기록함 — A-LIST / A-DET
- [ ] `GET /v1/parents/{id}/records` — 최신순 20개씩, 커서, 필터(영역·작성자·기간·출처·입력 방식)
- [ ] `GET /v1/records/{id}` — 상세 (음성 없으면 재생 숨김용 정보)
- [ ] `GET /v1/records/{id}/audio` — 재생용 서명 URL
- [ ] `PATCH /v1/records/{id}` — 작성자만, 수정 전 상태를 `record_versions`에 (한 트랜잭션)
  - [ ] 원문·음성·`recorded_at` 등 수정 시도 → 400 `IMMUTABLE_FIELD` (POL-02)
- [ ] `GET /v1/records/{id}/versions` — 수정 이력
- [ ] `POST /v1/records/{id}/exclude` — 기록지에서 제외 (삭제 아님)
- [ ] `POST /v1/records/{id}/comments` — 다른 가족 기록에 댓글

### 홈 — A-HOME-006~009
- [ ] `PUT /v1/parents/{id}/conditions/{date}` — 오늘 컨디션 (하루 1건, 이력은 DB 트리거)
- [ ] `GET /v1/parents/{id}/home` — 최근 기록 3건, 받은 체크리스트, D-day, 컨디션

### 가족 — A-FAM
- [ ] `POST /v1/parents/{id}/invites` — admin, 7일 유효 링크 (DB에는 해시만)
- [ ] `POST /v1/invites/{token}/accept` — 초대받은 사람도 동의 필수, 만료 링크 안내
- [ ] `PATCH /v1/family/{member_id}/role` — admin만, 마지막 관리자 보호 (409 `LAST_ADMIN`)
- [ ] 👤 Flutter: 초대 링크로 가입 시 부모님 등록 단계 건너뛰기

### 관찰 체크리스트 — A-TASK
- [ ] `GET /v1/parents/{id}/checklists/suggestions` — 없음·부족 항목 최대 6개
- [ ] `POST /v1/parents/{id}/checklists` — 항목 1개 이상, 받을 사람(나 포함), 확인 날짜
- [ ] `GET /v1/parents/{id}/checklists` — 보낸/받은 목록, 진행 n/m
- [ ] `GET /v1/checklists/{id}` — 항목별 정해진 관찰 질문 (자유 질문 없음)
- [ ] `PUT /v1/checklists/{id}/items/{task_id}/answer` — 답 = 기록 1건, "못 봤어요"는 기록 안 만들고 다음 추천에 포함
- [ ] `POST /v1/checklists/{id}/submit` — 모든 항목 답해야 제출, 보낸 사람에게 알림
- [ ] 52항목별 관찰 질문 문구 데이터 (팀이 작성)

### 조사 일정·브리핑 — A-SCH / A-BRF
- [ ] 후보 날짜 등록(지난 날짜 불가)·목록·가능 인원
- [ ] `PUT /v1/survey/candidates/{id}/vote`
- [ ] `POST /v1/parents/{id}/survey/confirm` — 조사일 저장, D-day, 전날 알림 재예약
- [ ] `GET /v1/parents/{id}/briefing` — 확정 기록지의 꼭 전할 5가지 (미확정이면 안내만)

### 알림 — POP_A_NOTI / A-SET-002
- [ ] `GET /v1/notifications`, `PATCH /v1/notifications/{id}/read`
- [ ] `GET`·`PUT /v1/settings/notifications` — 컨디션·할 일·브리핑 켜기/끄기
- [ ] `POST /v1/devices`, `DELETE /v1/devices/{id}` — FCM 토큰
- [ ] FCM 발송 연동
- [ ] 정기 알림: 조사 전날 20:00 브리핑, 컨디션 저녁 8시, 체크리스트 기한 다음 날 10:00 (꺼 두면 발송 안 함)

### 웹 추가 — W-DASH-003/004, W-TL-003
- [ ] `GET /v1/parents/{id}/next-actions` — 부족 항목 3개 + 관찰 예시
- [ ] `PATCH /v1/parents/{id}` — admin만 부모님 정보·신청 단계 변경 (A-SET, W-DASH-004)
- [ ] `GET /v1/parents/{id}/timeline/{date}/records` — 그날 기록 펼치기

---

## 7단계 · P1 나머지 / P2

### 기록함 부가 (P1)
- [ ] A-SYM-001 `POST /v1/parents/{id}/symptoms` — 증상·시간대(필수)·횟수·메모 → 행동변화 항목 연결
- [ ] A-SYM-002 `GET /v1/parents/{id}/symptoms/weekly` — 최근 4주 증상별 횟수
- [ ] A-MED-001 `POST /v1/parents/{id}/medications/scan` — 약 봉투 OCR, 사용자 확인 전 저장 안 함, 효능·복용법 설명 안 함, 사진 삭제
- [ ] A-MED-002 복용약 목록·추가·수정·중단 (삭제 대신 중단)

### 웹 P1
- [ ] W-DOC-001 의사 전달 요약 1장 (`type=doctor`, 진단명 추측 금지, 같은 확정·PDF 규칙)
- [ ] W-SIM-001/002 AI 모의 인터뷰 + 피드백 (점수·등급·과장 유도 금지)
- [ ] W-APL-001 이의신청 기한 계산 — ⚖️ 검증된 규칙만 (`rule_version`, `source_url`, 미검증 수치 하드코딩 금지)
- [ ] W-APL-002 선택지 비교, W-APL-003 소명자료 초안 (`type=appeal`)
- [ ] W-ALT-001 지역 도움 기관 목록 (정보 갱신일, 없으면 보건소 안내) — 기관 데이터 필요
- [ ] W-NHI-001 공단 서류 사진 쉬운 설명 (OCR, 즉시 삭제, 개별 판단은 공단 안내)
- [ ] W-RNW-001/002 갱신 준비: 판정일 전후 건수, 새 기록지
- [ ] W-LOG-002 QR 웹 로그인 — QR 세션 테이블·안전한 세션 전달 설계 먼저
- [ ] A-SET-003 로그아웃·탈퇴 (관리자 탈퇴 시 관리자 넘기기), 삭제 요청 API

### P2
- [ ] A-FAM-003 가족별 최근 30일 기록 수
- [ ] A-LIST-003 원문·수정본 검색
- [ ] 부모님 여러 명 등록 UI 지원

---

## 배포·운영 (베타 전)

- [ ] 운영용 Supabase 프로젝트 따로 만들기 (DB 마이그레이션·버킷·트리거 다시 적용)
- [ ] 운영 `.env`: `ENV=production` 필수 (없으면 `/v1/dev` 열림), secret key는 서버에만
- [ ] 실제 동의 문구 발행 (`consent_documents`, 더미 금지)
- [ ] `survey_items` 52항목을 최신 공식 조사표와 1회 대조 (현재 legacy 버전)
- [ ] Dockerfile — API 서버·워커 같은 이미지, 실행 명령만 다르게
- [ ] HTTPS, CORS(웹 도메인만), 로그·오류 모니터링
- [ ] 성능 확인: 음성 1분 → 10초, 현황판 3초
- [ ] 권한 테스트 보강 (TS-7: 역할별·타 가족 접근·마지막 관리자)
- [ ] 개인정보: 단톡방 원본·서류 사진 처리 후 즉시 삭제 확인, 탈퇴·철회 시 삭제 흐름
- [ ] 👤 접근성(대비 4.5:1, 글자 16px, 버튼 44px) — 앱·웹
