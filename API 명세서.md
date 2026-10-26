# API 명세서

> **기준:** 「실버케어 기능명세서 v0.4」(최상위 요구사항) · Supabase PostgreSQL v0.5 + v0.7 증분 마이그레이션(구현 스키마)
> 
> 
> **기술:** Flutter · React → **FastAPI(서비스 CRUD·권한·AI)** → Supabase PostgreSQL / Storage, 로그인은 Supabase Auth
> 
> **문서 상태:** 개발 계약 초안. `설계 결정` 표시는 기능명세서의 동작을 구현하기 위해 정한 API 세부 규칙. 개인정보 처리, 공식 조사표 및 행정 절차는 정식 출시 전 별도 검증 필요.
> 

## 0. 읽는 법 및 개발 원칙

- **우선순위:** 기능명세서 P0(베타 필수), P1(MVP), P2(추후). API의 `기능 ID`는 명세서 ID를 그대로 사용한다.
- **Base URL:** 로컬 `http://127.0.0.1:8001/v1`, 운영 예시 `https://api.silvercare.app/v1`(도메인 확정 전).
- **인증:** Supabase Auth에서 로그인·토큰 발급/갱신/로그아웃; FastAPI는 Bearer access token의 유효성을 검증한다. **FastAPI가 자체 비밀번호 DB나 별도 로그인 토큰을 발급하지 않는다.**
- **데이터 경로:** Flutter·React는 서비스 데이터 CRUD를 FastAPI로만 수행한다. Supabase Data API에 직접 쓰기 권한을 부여하지 않는다. 비공개 Storage 접근은 FastAPI 경유 또는 한시적 서명 업로드/다운로드 방식이다.
- **형식:** UTF-8 JSON, `snake_case`, UUID 문자열, `date=YYYY-MM-DD`, `datetime=ISO 8601(오프셋 포함)`. DB는 `timestamptz`로 저장하며 클라이언트는 KST로 표시한다.
- **기록 보호(POL-02):** 일반 수정 API는 음성 원본·STT 원문·`recorded_at`을 수정하지 못한다. 개인정보 삭제·철회는 별도 승인된 삭제 절차로 구분한다.
- **분류(POL-03/06):** 5개 영역 `physical/cognitive/behavior/nursing/rehab` 및 미분류. **점수·예상 등급을 생성하거나 반환하지 않는다.** 기록 분류 항목 코드에는 DB `survey_items.code` 값을 사용한다. 기존 API v0.4 예시의 `mobility`, `short_memory`는 실제 코드가 아닐 수 있다.
- **설계 변경:** v0.4에서 임의 정의한 `u_…`, `r_…` 등의 ID는 사용하지 않고 UUID로 통일한다. `audio_url` 대신 비공개 버킷의 `audio_path`를 사용한다. 응답에서 접근 가능한 오디오 URL이 필요할 때는 별도 서명 링크를 발급한다.

### 0.1 응답 규칙

**성공(단일 객체)**

```
{"data":{"id":"550e8400-e29b-41d4-a716-446655440000"},"meta":{}}
```

**목록(커서 기반)**

```
{"data":[],"meta":{"next_cursor":null,"has_more":false}}
```

**비동기 작업 접수**

```
{"data":{"job_id":"550e8400-e29b-41d4-a716-446655440001","status":"queued"}}
```

**오류**

```
{"error":{"code":"CONSENT_REQUIRED","message":"필수 동의를 완료해 주세요.","details":null}}
```

- 입력값 검증은 기본적으로 **422**, 비즈니스 규칙 위반은 400/409. FastAPI 기본 오류를 공통 에러 포맷으로 변환한다.
- 페이지네이션 기본 `limit=20`, 최대 `100`; 동일 시각 중복 방지를 위해 `(recorded_at, id)` 기반 커서를 사용한다(설계 결정).
- `202 Accepted`는 백그라운드 작업 시작, `204 No Content`는 빈 본문 처리에 사용한다.

### 0.2 HTTP 상태·오류 코드

| HTTP | 대표 코드 | 의미 |
| --- | --- | --- |
| 400 | `INVALID_REQUEST`, `IMMUTABLE_FIELD`, `INVALID_FILE_TYPE` | 잘못된 입력·불허 수정 |
| 401 | `UNAUTHORIZED`, `TOKEN_EXPIRED` | 인증 누락·만료 |
| 403 | `PERMISSION_DENIED`, `CONSENT_REQUIRED`, `NOT_CONFIRMED` | 가족 권한·동의·출력 권한 부족 |
| 404 | `NOT_FOUND` | 없거나 접근 불가능한 리소스(타 가족 정보 노출 방지) |
| 409 | `ALREADY_MEMBER`, `IDEMPOTENCY_CONFLICT`, `LAST_ADMIN`, `VERSION_CONFLICT` | 중복·경합·상태 충돌 |
| 413 | `FILE_TOO_LARGE` | 파일 크기 제한 위반 |
| 422 | `VALIDATION_ERROR` | 타입·형식 검증 실패 |
| 429 | `RATE_LIMITED` | 요청 과다 |
| 500/502/503 | `INTERNAL_ERROR`, `AI_PROVIDER_ERROR`, `SERVICE_UNAVAILABLE` | 서버·외부 AI 장애 |

> `CONSENT_REQUIRED`는 기본적으로 403으로 통일한다(설계 결정). 초기 v0.4의 422 표기와 다름. `404`는 다른 가족의 정보를 추측하지 못하도록 사용한다. 마이크 권한 거부는 **Flutter 클라이언트의 오류**로, 서버가 403 `MIC_PERMISSION`을 반환하는 형태로 정의하지 않는다.
> 

### 0.3 공통 헤더

| 헤더 | 필수 | 내용 |
| --- | --- | --- |
| `Authorization: Bearer <access_token>` | 인증 API 모두 | Supabase Auth 액세스 토큰 |
| `Content-Type: application/json` | JSON 요청 | 파일은 `multipart/form-data` |
| `Idempotency-Key` | 기록 생성/오프라인 재전송/중요 중복 방지 | 사용자·경로·키 조합으로 한 요청 결과 재사용 |
| `If-Match` | 선택(권장) | 동시 수정 방지용 버전/ETag(구현 단계에서 확정) |

현재 부모님은 P0 기준 1명 등록이 기본이나 DB는 여러 부모님을 지원한다. 각 리소스는 URL 경로의 `parent_id`가 기준이며, 임의 `X-Parent-Id`만 믿고 접근을 허가하지 않는다.

### 0.4 가족 접근 권한

| 동작 | `admin` | `writer` | `viewer` |
| --- | --- | --- | --- |
| 부모님·기록·현황판·보고서 조회 | ✓ | ✓ | ✓ |
| 새 기록·컨디션·증상 작성 | ✓ | ✓ | — |
| 본인이 작성한 기록 수정·제외 | ✓ | ✓ | — |
| **다른 사람 기록 본문/분류 수정** | — | — | — |
| 다른 사람 기록에 댓글 | ✓ | ✓ | — |
| 체크리스트 발송·응답, 일정 투표 | ✓ | ✓ | — |
| 보고서 초안 생성·편집 | ✓ | ✓ | — |
| 보고서 **최종 확정** | ✓ | — | — |
| 부모님 정보·가족 역할 변경·초대 | ✓ | — | — |

> **설계 결정:** 보고서 최종 확정은 admin만 허용. 원본 기능명세서는 가족의 명시적 확정을 요구하며 확정자의 역할은 지정하지 않음. API에 `user_id`를 받더라도 인증 토큰의 실제 사용자와 대조한다. 사용자는 최소한 해당 `parent_id`의 `family_members` 멤버여야 한다.
> 

### 0.5 P0 요청·비동기 공통 흐름

1. 요청 인증 → `public.users` 프로필 유무 및 필수 동의 확인 → 부모님 멤버십·역할 검사.
2. 서버 검증 후 DB 트랜잭션으로 기록/작업 생성; `Idempotency-Key`가 같고 요청 내용이 같으면 기존 응답 반환, 다르면 409.
3. STT/LLM 등 오래 걸리는 작업은 즉시 응답할 수 없으면 `202 + processing_status/job_id`로 접수하고 별도 상태 조회. **완료 시간 보장 불가**이며, 기능명세서의 음성 1분→10초 목표는 측정/최적화 목표로 남긴다.
4. AI 실패 시 원문·음성 원본을 잃지 않고 `failed` 상태와 재시도 경로를 제공한다. 외부 AI에 보낼 정보는 최소화한다.

---

## 1. 인증 및 계정 — Supabase Auth + FastAPI

**출처:** A-ON-001, W-LOG-001/002, A-SET-003. **개발용 이메일 로그인**은 기능명세서에 없는 임시 구현이다. 제품 요구 로그인은 카카오/휴대폰 OTP이며 QR 웹 로그인은 P1.

| 주체 | 동작 | 경로/메서드 | 우선 | 설명 |
| --- | --- | --- | --- | --- |
| Supabase Auth SDK | 이메일 가입·로그인(개발) | SDK `sign_up` / `sign_in_with_password` | 개발 | 제품 API가 아님 |
| Supabase Auth SDK | 휴대폰 OTP | SDK `sign_in_with_otp` / `verify_otp` | P0 | 인증번호 3분 제한은 제품 요구; 실제 제공자 구성 검증 필요 |
| Supabase Auth SDK | 카카오 OAuth | SDK OAuth 흐름 | P0 | 공급자 설정 후 구현, 자체 `/auth/kakao` 토큰 발급 API 없음 |
| Supabase Auth SDK | 세션 갱신·로그아웃 | SDK refresh/sign_out | P0/P1 | 인증 세션 제공자가 담당 |
| FastAPI | 내 온보딩 상태 | `GET /v1/auth/me` | P0 | 서비스 프로필, 동의·부모님 연결 확인 |
| FastAPI | 계정 탈퇴 요청 | `POST /v1/users/me/deletion-requests` | P1 | 실제 삭제는 별도 처리, 관리자 위임 필요 |
| FastAPI | QR 로그인 요청 발급 | `POST /v1/auth/qr/sessions` | P1 | 일회용 세션, 3분 만료 |
| FastAPI | 앱 QR 승인 | `POST /v1/auth/qr/sessions/{id}/approve` | P1 | 앱에서 사용자 인증 후 승인 |
| FastAPI | QR 처리 상태 조회 | `GET /v1/auth/qr/sessions/{id}` | P1 | 소비·만료 확인 |

> **구현 주의:** QR 로그인은 기존 DB v0.7에 전용 `qr_login_sessions` 테이블이 없다. P1 작업 전 DB 추가와 Supabase 세션의 안전한 웹 전달 방식 설계가 필요하다. 브라우저에 기존 앱 access/refresh token을 단순 전달하는 방식은 사용하지 않는다.
> 

**GET `/v1/auth/me`** — `users`, `consents`, `family_members`

```
{"data":{"user":{"id":"550e8400-e29b-41d4-a716-446655440000","login_type":"email"},"onboarding":{"consents_completed":false,"parent_registered":false},"parent_ids":[]}}
```

로그인 공급자 정보의 단일 진실 원천은 `auth.users`; `public.users.login_type`은 선택적인 프로필 메타데이터로 사용한다.

---

## 2. 동의 및 정보주체 권한 — POL-05

**기능:** A-ON-002, A-SET-001. **테이블:** `consent_documents`, `consents`, `care_subject_authorizations`, `deletion_requests`.

| Method | Endpoint | 우선 | 설명 |
| --- | --- | --- | --- |
| GET | `/v1/consents/required` | P0 | 유효 동의 문구·버전·필수 여부 조회 |
| POST | `/v1/consents` | P0 | 사용자별 동의/비동의 저장 |
| GET | `/v1/consents/me` | P0 | 최신 상태·과거 이력 조회 |
| POST | `/v1/consents/{type}/revoke` | P0 | 철회, 필수 동의 철회 시 후속 처리 제한 |
| POST | `/v1/parents/{parent_id}/authorizations` | P0 준비 | 돌봄 대상자 정보 처리 권한/동의 근거 제출 |
| GET | `/v1/parents/{parent_id}/authorizations` | P0 준비 | 확인 상태 조회 |
| POST | `/v1/deletion-requests` | P1 | 계정/동의철회/정보삭제 접수 |
| GET | `/v1/deletion-requests/{id}` | P1 | 요청 상태 조회 |

**GET `/v1/consents/required`**

```
{"data":[{"type":"service","required":true,"doc_version":"<published-version>","title":"서비스 이용 동의","content":"<published-text>"},{"type":"privacy","required":true,"doc_version":"<published-version>","title":"개인정보 수집·이용","content":"<published-text>"},{"type":"health","required":true,"doc_version":"<published-version>","title":"건강정보 처리","content":"<published-text>"},{"type":"noti","required":false,"doc_version":"<published-version>","title":"알림","content":"<published-text>"}]}
```

**POST `/v1/consents`**

```
{"items":[{"type":"service","doc_version":"<published-version>","agreed":true},{"type":"privacy","doc_version":"<published-version>","agreed":true},{"type":"health","doc_version":"<published-version>","agreed":true},{"type":"noti","doc_version":"<published-version>","agreed":false}]}
```

- 필수 3종에 `agreed=true`가 없으면 다음 온보딩 단계로 진행할 수 없다.
- FastAPI는 제출된 `doc_version`이 **실제로 공개된 문구 버전**인지 검증한다. 클라이언트가 임의의 버전을 만들어 등록할 수 없다.
- 동의 이력은 삭제하지 않고 `revoked_at`으로 철회를 표시한다. 부모님 본인 또는 적법한 대리 권한에 관한 상세 법적 요건은 **정식 출시 전 법률 검토 후 확정**한다. 개발 테스트에는 가상 건강정보만 사용한다.

---

## 3. 부모님·가족 — A-ON-003 / A-FAM

**테이블:** `parents`, `family_members`, `family_invites`. 등록한 사용자를 `admin`으로 생성하는 작업은 **한 트랜잭션**으로 처리한다.

| Method | Endpoint | 기능 ID | 우선 | 권한·설명 |
| --- | --- | --- | --- | --- |
| POST | `/v1/parents` | A-ON-003 | P0 | 동의 완료한 사용자, 등록 후 admin |
| GET | `/v1/parents` | 홈/공통 | P0 | 본인이 접근 가능한 부모님 목록(설계 추가) |
| GET | `/v1/parents/{parent_id}` | A-ON-003 | P0 | 멤버 조회 |
| PATCH | `/v1/parents/{parent_id}` | A-SET | P1 | admin 정보 변경 |
| GET | `/v1/parents/{parent_id}/family` | A-FAM-003 | P2 | 멤버·최근 30일 작성 수 |
| POST | `/v1/parents/{parent_id}/invites` | A-FAM-001 | P1 | admin, 7일 유효 링크 발급 |
| POST | `/v1/invites/{token}/accept` | A-FAM-001 | P1 | 동의한 신규 가족 수락 |
| PATCH | `/v1/family/{member_id}/role` | A-FAM-002 | P1 | admin만, 마지막 admin 보호 |

**POST `/v1/parents`**

```
{"nickname":"엄마","age_band":"80s","apply_stage":"waiting","cohabiting":false}
```

**201**

```
{"data":{"id":"550e8400-e29b-41d4-a716-446655440010","nickname":"엄마","age_band":"80s","apply_stage":"waiting","cohabiting":false,"survey_date":null,"judged_date":null,"my_role":"admin"}}
```

- `apply_stage`: `before | waiting | result | renewal` (DB enum과 일치). 화면에는 각각 신청 전 / 조사 대기 / 결과 나옴 / 갱신 준비로 표시. 기존 API v0.4의 `survey_waiting`은 사용하지 않는다.
- 이름·주민등록번호 입력 필드 없음(POL-07). 부모님 추가 등록은 P2지만 내부 ID/권한 구조는 다중 대상을 지원.

**POST `/v1/parents/{parent_id}/invites`**

```
{"role":"writer"}
```

**201**

```
{"data":{"invite_url":"https://example.invalid/i/<one-time-secret>","expires_at":"2026-11-01T12:00:00+09:00"}}
```

`invite_url`은 **형식 예시**이며 실제 도메인·경로는 구현 시 확정한다. DB에는 링크 원문이 아니라 `token_hash`만 저장한다. 가족 초대 수락 시 역할을 무조건 신뢰하지 말고 서버가 초대 데이터로 결정한다.

---

## 4. 기록 및 AI 분류 — 앱 P0 핵심

**기능:** A-HOME-001~005, A-LIST-001~003, A-DET-001~003. **테이블:** `records`, `record_items`, `survey_items`, `record_versions`, `record_comments`, `idempotency_keys`. `audio_path`, `recorded_at`, `occurred_at`, `created_at`을 구분한다.

| Method | Endpoint | 기능 ID | 우선 | 역할 |
| --- | --- | --- | --- | --- |
| POST | `/v1/parents/{parent_id}/records/text` | A-HOME-002/003 | **P0** | 텍스트 기록 생성, 분류 접수 |
| POST | `/v1/parents/{parent_id}/records/audio` | A-HOME-001/003 | **P0** | 음성 파일 업로드, 녹음 원본 보존, STT/분류 접수 |
| GET | `/v1/parents/{parent_id}/records` | A-LIST-001/002/003 | P1(최근 3개 P0) | 최신 목록·필터·검색(P2) |
| GET | `/v1/records/{record_id}` | A-DET-001 | P1 | 본문·원본·AI 항목·작성자 |
| GET | `/v1/records/{record_id}/audio` | A-DET-001 | P1 | 권한 확인 후 제한적 재생 링크 |
| PATCH | `/v1/records/{record_id}` | A-DET-002 | P1 | 작성자만 본문·출처·분류 변경, 이력 생성 |
| POST | `/v1/records/{record_id}/exclude` | A-DET-003 | P1 | 작성자, `status=excluded`로 변경 |
| GET | `/v1/records/{record_id}/versions` | A-DET-002 | P1 | 원문·수정본·작성자·시각 |
| POST | `/v1/records/{record_id}/comments` | A-DET-002 | P1 | 가족 타인 기록 댓글 |
| POST | `/v1/records/{record_id}/reclassify` | A-HOME-004 | P0 오류복구 | AI 분류 재시도 |
| GET | `/v1/records/{record_id}/processing` | A-HOME-001/004 | P0 | STT/분류 진행·실패 상태 조회(설계 추가) |

### 4.1 텍스트 기록

**POST `/v1/parents/{parent_id}/records/text`** — `Authorization`, `Idempotency-Key` 권장

```
{"text":"식사: 반찬을 작게 잘라 드려야 드셨어요.","source":"direct","recorded_at":"2026-10-25T10:20:00+09:00","occurred_at":"2026-10-25T09:30:00+09:00"}
```

**201 또는 202**

```
{"data":{"id":"550e8400-e29b-41d4-a716-446655440020","parent_id":"550e8400-e29b-41d4-a716-446655440010","input_type":"text","source":"direct","original_text":"식사: 반찬을 작게 잘라 드려야 드셨어요.","current_text":"식사: 반찬을 작게 잘라 드려야 드셨어요.","processing_status":"pending","items":[]}}
```

- 텍스트는 **1~1000자**; 공백만 입력 거부. 출처 미선택 시 `direct`.
- DB 트랜잭션에서 **먼저 원문 보존**, 이후 AI 분류 작업을 시작. 분류 실패해도 기록은 남는다.
- `recorded_at`은 실제 기기 기록 생성 시각(오프라인 포함); 서버 저장 `created_at`은 DB가 부여. 시간이 비정상적으로 미래인 경우 정책에 따라 거부/보정하며 로그를 남긴다.
- `source`: `direct`(직접 봄), `call`(통화), `kakao`(단톡방). 일반 텍스트 입력에서 `kakao` 직접 지정은 서버 정책으로 제한할 수 있다.

### 4.2 음성 기록

**POST `/v1/parents/{parent_id}/records/audio`** — `multipart/form-data`

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `audio` | File | ✓ | Flutter가 녹음한 파일 |
| `source` | enum | ✓ | `direct` 또는 `call` |
| `recorded_at` | ISO8601 | ✓ | 기기에서 녹음한 시각 |
| `occurred_at` | ISO8601 | — | 실제 사건 시간 |
| `duration_seconds` | int | ✓ | 2~180초 |

**202**

```
{"data":{"id":"550e8400-e29b-41d4-a716-446655440021","input_type":"voice","processing_status":"pending","recorded_at":"2026-10-25T10:20:00+09:00","audio_duration_seconds":60}}
```

- Flutter 녹음: **1회 탭 시작, 전화 수신 시 일시정지, 3분 자동 종료, 2초 미만 취소**. 파일 검증·저장은 서버도 확인. 마이크 권한 오류는 앱에서 처리.
- 인터넷이 없으면 Flutter 로컬 저장소에 보관, 재연결 후 동일 `Idempotency-Key`로 전송.
- FastAPI가 비공개 Supabase Storage에 음성 원본 저장 → STT → 분류. 원본 업로드가 먼저 완료되어야 하고 임시 상태도 DB에 남긴다. 사용자에게 공개 Storage URL을 전달하지 않는다.
- **저장 확인 10초 목표**는 기능명세 완료 기준이며 AI 처리 시간이 길면 원본 저장을 먼저 확인하고 처리 중임을 분리해서 표시해야 한다(표시 방식 검증 필요).

### 4.3 분류·수정·상태

**GET `/v1/records/{record_id}/processing`**

```
{"data":{"record_id":"550e8400-e29b-41d4-a716-446655440021","processing_status":"completed","original_text":"어머니가 밤에 두 번 현관문을 열려고 하셨어요.","items":[{"area":"behavior","item_code":"beh_going_out","confidence":0.92,"set_by":"ai"}]}}
```

- `processing_status`: `pending | processing | completed | failed`.
- 확신도가 낮거나 부모님과 무관한 문장은 **미분류** 처리. `survey_items` 코드가 아닌 임의 코드를 `record_items`에 저장하지 않는다.
- 분류된 항목은 여러 개가 될 수 있다. `confidence`는 0~1, `set_by`는 `ai|user`.

**PATCH `/v1/records/{record_id}`** — 작성자만 가능

```
{"current_text":"밤에 현관문을 두 차례 열려고 하셨어요.","source":"call","item_codes":["beh_going_out"],"occurred_at":"2026-10-24T23:00:00+09:00"}
```

- `original_text`, `audio_path`, `recorded_at`, `created_at`, `author_id`, `parent_id`는 수정 불가(`400 IMMUTABLE_FIELD`).
- `record_versions`에 수정 전 문장·출처·분류·사건시각 스냅샷을 남기고 갱신한다. 한 트랜잭션에서 처리.
- 타 가족의 문장/분류 변경은 admin이라도 금지하고, 댓글 작성만 허용.
- `POST /exclude` 처리 후 현황판과 보고서 **새 초안** 집계에서 제외한다. 기존 확정 보고서의 근거·출력본은 별도 정책에 따름.

**GET `/v1/parents/{parent_id}/records`**

`?area=cognitive&author_id=<uuid>&from=2026-09-01&to=2026-10-25&source=call&input_type=voice&cursor=...&limit=20`

선택적 `q=...` 전문 검색은 P2. 결과에 작성자·기록시각·출처·수정됨 표시. 인덱스/커서 필드는 실제 DB 정렬과 일치시키기.

---

## 5. 홈·증상·컨디션·복용약

**기능:** A-HOME-006~009, A-SYM-001/002, A-MED-001/002. **테이블:** `conditions`, `condition_versions`, `record_symptoms`, `records`, `medications`.

| Method | Endpoint | 우선 | 기능 ID | 설명 |
| --- | --- | --- | --- | --- |
| GET | `/v1/parents/{parent_id}/home` | P0/P1 | A-HOME-007~009 | 최근 기록 3건, 할 일, D-day, 컨디션 조합(설계 추가) |
| PUT | `/v1/parents/{parent_id}/conditions/{date}` | P1 | A-HOME-006 | 하루 한 건 생성/수정 및 이력 |
| POST | `/v1/parents/{parent_id}/symptoms` | P1 | A-SYM-001 | 증상·시간대·횟수·메모, 행동변화 분류 연결 |
| GET | `/v1/parents/{parent_id}/symptoms/weekly` | P1 | A-SYM-002 | 최근 4주 증상별 횟수 |
| POST | `/v1/parents/{parent_id}/medications/scan` | P1 | A-MED-001 | 약 봉투·처방전 OCR, 사용자 수정 전까지 확정 금지 |
| GET | `/v1/parents/{parent_id}/medications` | P1 | A-MED-002 | 복용 중/중단 목록 |
| POST | `/v1/parents/{parent_id}/medications` | P1 | A-MED-002 | 사용자가 확인한 약 추가 |
| PATCH | `/v1/medications/{medication_id}` | P1 | A-MED-002 | 수정 및 `stopped` 전환 |

**PUT `/v1/parents/{parent_id}/conditions/2026-10-25`**

```
{"value":"bad"}
```

**200** `{"data":{"date":"2026-10-25","value":"bad","updated_at":"2026-10-25T11:00:00+09:00"}}`

- `good|normal|bad`. 변경 시 `condition_versions`에 이전 값과 수정자·시각 기록. `author_id`는 수정한 사용자로 저장하는 정책(구현 결정).

**POST `/v1/parents/{parent_id}/symptoms`**

```
{"symptom_type":"night_wandering","time_band":"dawn","occurrence_count":2,"note":"새벽에 현관문을 열려고 하심","occurred_at":"2026-10-24T03:00:00+09:00"}
```

**201** `{"data":{"record_id":"550e8400-e29b-41d4-a716-446655440030","symptom_type":"night_wandering","occurrence_count":2}}`

- 시간대 필수: `dawn|morning|afternoon|evening|night`. 증상은 `records`의 한 건 + `record_symptoms` 1:1로 저장하며 적절한 행동변화 코드에 연결.
- 약 OCR은 이름·1회 양·하루 횟수·처방일만 추출, **효능이나 용법을 임의 설명하지 않음**. OCR 결과는 저장 전 사용자 확인 필수.

---

## 6. 가족 관찰 체크리스트 — A-TASK-001~005

**테이블:** `checklists`(묶음), `tasks`(항목), `record_items`, `records`. 체크리스트 수신·제출 권한은 해당 가족의 `writer/admin`.

| Method | Endpoint | 우선 | 기능 |
| --- | --- | --- | --- |
| GET | `/v1/parents/{parent_id}/checklists/suggestions` | P1 | W-DASH의 부족 항목 최대 6개 추천 |
| POST | `/v1/parents/{parent_id}/checklists` | P1 | 항목 선택·담당자·기한·발송 |
| GET | `/v1/parents/{parent_id}/checklists` | P1 | 보낸/받은 목록·진행 n/m |
| GET | `/v1/checklists/{checklist_id}` | P1 | 항목·관찰 질문·답변 조회 |
| PUT | `/v1/checklists/{checklist_id}/items/{task_id}/answer` | P1 | 개별 항목 답 및 기록 생성 |
| POST | `/v1/checklists/{checklist_id}/submit` | P1 | 전체 항목 응답 완료 확인·발신자 알림 |

**POST `/v1/parents/{parent_id}/checklists`**

```
{"item_codes":["phys_toilet_use","phys_eating"],"to_user_id":"550e8400-e29b-41d4-a716-446655440000","due_date":"2026-10-28"}
```

**201** `{"data":{"id":"550e8400-e29b-41d4-a716-446655440040","total_items":2,"answered_items":0,"status":"pending"}}`

**PUT `/v1/checklists/{checklist_id}/items/{task_id}/answer`**

```
{"answer":"little","note":"뒤처리는 도와드려야 함"}
```

- DB `task_answer_enum`: `alone | little | full | not_seen`에 맞춘다. 기존 API v0.4의 `self/a_little/a_lot`는 변경.
- `not_seen`은 **체크리스트 응답으로만 저장**, `records`는 생성하지 않고 다음 추천에 재포함.
- 나머지는 항목당 `records` 1건(`input_type=checklist`, `source=direct`, 작성자는 응답자) 생성. 같은 항목 재전송으로 중복 기록이 생기지 않게 멱등성 및 최종 답변 정책 적용.
- 질문은 `survey_items`별 서버 지정 관찰 문구로 내려주며 자유 질문 생성은 허용하지 않는다(기능명세).

---

## 7. 방문조사 일정·전날 브리핑 — A-SCH / A-BRF

**테이블:** `survey_candidates`, `schedule_votes`, `parents.survey_scheduled_at`, `reports`, `report_items`.

| Method | Endpoint | 우선 | 기능 |
| --- | --- | --- | --- |
| POST | `/v1/parents/{parent_id}/survey/candidates` | P1 | 날짜·오전오후 후보 추가 |
| GET | `/v1/parents/{parent_id}/survey/candidates` | P1 | 후보 목록·가능 인원 |
| PUT | `/v1/survey/candidates/{candidate_id}/vote` | P1 | 현재 사용자 가능/불가 선택 |
| POST | `/v1/parents/{parent_id}/survey/confirm` | P1 | 공단과 통화로 정한 조사일시 저장 |
| GET | `/v1/parents/{parent_id}/briefing` | P1 | 확정 기록지의 꼭 전할 5가지 |

**POST `/v1/parents/{parent_id}/survey/candidates`**

```
{"candidate_date":"2026-10-28","ampm":"pm"}
```

**PUT `/v1/survey/candidates/{candidate_id}/vote`**

```
{"available":true}
```

**POST `/v1/parents/{parent_id}/survey/confirm`**

```
{"survey_scheduled_at":"2026-10-28T14:00:00+09:00"}
```

- 공단 방문조사 일시는 **가족이 통화로 확인한 값**을 입력; 시스템이 공단 예약을 확정해 주는 기능이 아님.
- 확정/변경 시 D-day와 전날 오후 8시 알림 예약 갱신. 미확정 보고서만 있으면 브리핑은 안내 문구 반환, AI가 5개를 새로 지어내지 않음.

---

## 8. 웹 근거 현황판 — W-DASH-001~004 (P0)

**테이블:** `survey_items`, `record_items`, `records`, `family_members`, `conditions`.

| Method | Endpoint | 우선 | 기능 |
| --- | --- | --- | --- |
| GET | `/v1/parents/{parent_id}/coverage` | **P0** | 52항목 기준 기록수·최근일·충분도 |
| GET | `/v1/parents/{parent_id}/coverage/{item_code}/records` | **P0** | 해당 항목을 만든 원문 기록 |
| GET | `/v1/parents/{parent_id}/next-actions` | P1 | 부족 항목 3개·관찰 예시 |

**GET `/v1/parents/{parent_id}/coverage`**

```
{"data":{"summary":{"total_records":86,"recorded_days":41,"family_members":3,"sufficient_items":29},"areas":[{"area":"physical","total_items":12,"sufficient_items":7,"items":[{"item_code":"phys_eating","label":"식사하기","count":5,"last_at":"2026-10-13","status":"sufficient"},{"item_code":"phys_bathing","label":"목욕하기","count":0,"last_at":null,"status":"none"}]}]}}
```

- 실제 응답에는 5개 영역 전부 포함. 예시는 일부만 표시.
- **제안 기준:** 최근 30일 서로 다른 날에 2건 이상이면 `sufficient`; 1일/1건은 `insufficient`, 0건은 `none`. **이것은 기록 충분도이지 장기요양 점수·등급 판정이 아님.**
- `excluded` 기록 제외; 같은 기록이 여러 코드로 분류되면 코드별로 각각 반영하되 요약의 `total_records`는 중복 제거.
- `GET /coverage/{item_code}/records`는 해당 부모님의 **정상 상태 기록만** 반환. 타 가족 데이터 혼입 방지를 위해 `records.parent_id`에서 먼저 필터링.

---

## 9. 웹 타임라인 — W-TL-001~003 (P0)

**테이블:** `records`, `record_items`, `conditions`, `events`.

| Method | Endpoint | 우선 | 기능 |
| --- | --- | --- | --- |
| GET | `/v1/parents/{parent_id}/timeline` | **P0** | 영역별 날짜별 기록 건수 + 컨디션 띠 |
| POST | `/v1/parents/{parent_id}/events` | **P0** | 낙상·입원·퇴원·약 변경·기타 |
| GET | `/v1/events/{event_id}/compare` | **P0** | 사건 전/후 각 30일 기록 건수 |
| GET | `/v1/parents/{parent_id}/timeline/{date}/records` | P1 | 해당 날짜/영역 근거 기록 펼치기 |

**GET `/v1/parents/{parent_id}/timeline?areas=physical,behavior&period=3m`**

```
{"data":{"period":"3m","insufficient":false,"conditions":[{"date":"2026-10-24","value":"normal"}],"series":[{"area":"behavior","points":[{"date":"2026-10-24","count":2}]}],"events":[{"id":"550e8400-e29b-41d4-a716-446655440050","date":"2026-10-02","type":"fall","note":"낙상"}]}}
```

- 기간: `1m|3m|6m|all`. 7일 미만의 기록은 `insufficient=true`로 안내하되 존재하는 기록 자체를 숨기지는 않는 방향(설계 결정).
- 전후 비교는 **기록 건수만** 보여주고 의학적 원인·상태 악화의 인과 해석은 하지 않는다. 컨디션은 좋은 날도 포함한다.

---

## 10. 카카오 단톡방 불러오기 — W-UP-001~004 (P0)

**테이블:** `import_jobs`, `import_candidates`, `records`, `record_items`. 원본 파일 처리 후 삭제, 미선택 후보 24시간 후 삭제.

| Method | Endpoint | 우선 | 기능 |
| --- | --- | --- | --- |
| POST | `/v1/parents/{parent_id}/imports` | **P0** | TXT 업로드·동의·기간, 비동기 작업 시작 |
| GET | `/v1/imports/{job_id}` | **P0** | 처리 상태·진행률·원본 삭제 여부 |
| GET | `/v1/imports/{job_id}/candidates` | **P0** | AI 추출 후보 목록 |
| POST | `/v1/imports/{job_id}/save` | **P0** | 사용자가 선택한 후보만 기록에 저장 |

**POST `/v1/parents/{parent_id}/imports`** — `multipart/form-data`

| 필드 | 타입 | 조건 |
| --- | --- | --- |
| `file` | txt | 20MB 이하 |
| `consent` | bool | 반드시 `true` |
| `period_months` | int | 기본 6, DB 범위 1~60 |

**202**

```
{"data":{"job_id":"550e8400-e29b-41d4-a716-446655440060","status":"queued","processed_messages":0,"total_messages":0}}
```

**GET `/v1/imports/{job_id}`**

```
{"data":{"status":"review","processed_messages":2340,"total_messages":2340,"candidate_count":31,"original_deleted":true}}
```

**POST `/v1/imports/{job_id}/save`**

```
{"candidate_ids":["550e8400-e29b-41d4-a716-446655440061"]}
```

**201** `{"data":{"saved_records":1}}`

- 상태: `queued|processing|review|finished|failed`. 원본 카카오 TXT는 성공·실패에 관계없이 처리 후 지우며 삭제 완료 시각을 기록한다.
- iOS/Android/PC 카카오 TXT 형식의 날짜·보낸 사람 분리 검증 필요. 이모티콘/사진 표식 등 제외.
- **아무 후보도 자동으로 records에 저장하지 않는다.** 체크한 후보만 저장, 나머지는 24시간 안에 삭제. 서버 워커/cron 실제 삭제 작업은 별도 구현 필수.
- 저장된 기록은 `source=kakao`, `recorded_at`은 원래 메시지 시점, `author_id`는 가져온 사용자; 메시지 원 작성자는 필요 시 별도 출처 설명으로 기록.
- 최초 TXT에는 다른 가족의 개인정보가 포함될 수 있으므로 동의·권한·외부 AI 전송 범위를 출시 전 검토.

---

## 11. 조사원 전달 기록지·의사 요약·소명자료 — W-REP / W-DOC / W-APL

**테이블:** `reports`, `report_items`, `report_item_sources`, 기존 호환 `report_sources`, `records`. `report_group_id`별 버전을 구성하고, **확정본은 변경하지 않는다.**

| Method | Endpoint | 기능 ID | 우선 | 기능 |
| --- | --- | --- | --- | --- |
| POST | `/v1/parents/{parent_id}/reports` | W-REP-001 | **P0** | 선택 기간 기록을 AI가 요약, 새 초안 |
| GET | `/v1/parents/{parent_id}/reports` | W-REP-001 | P0 | 기존 보고서 초안/확정본 목록(설계 추가) |
| GET | `/v1/reports/{report_id}` | W-REP-002 | **P0** | 항목 문장·근거·세부사항 조회 |
| PATCH | `/v1/reports/{report_id}/items/{item_id}` | W-REP-002/003 | **P0** | 문장 수정·포함 제외·세부사항 |
| PUT | `/v1/reports/{report_id}/top5` | W-REP-006 | P1 | 최대 5개 항목·세부사항 지정 |
| POST | `/v1/reports/{report_id}/confirm` | W-REP-004 | **P0** | 가족 확인, admin 최종 확정 |
| GET | `/v1/reports/{report_id}/pdf` | W-REP-005 | **P0** | 확정본만 PDF 출력 |
| POST | `/v1/reports/{report_id}/revisions` | W-REP-004 | **P0** | 확정본 기반 **새 버전 초안** 생성 |

**POST `/v1/parents/{parent_id}/reports`**

```
{"type":"surveyor","period_months":3}
```

**202**

```
{"data":{"report_id":"550e8400-e29b-41d4-a716-446655440070","report_group_id":"550e8400-e29b-41d4-a716-446655440071","version":1,"status":"draft","generation_status":"processing"}}
```

> **DB 차이:** 현재 v0.7 `reports` 테이블에 `generation_status` 컬럼은 없다. 이 응답을 제공하려면 작업 테이블을 추가하거나 생성 API를 동기 처리하도록 명세를 간소화해야 한다. 첫 구현에서는 AI 처리 후 `201 + draft`로 반환하는 동기 방식도 가능하지만 요청 시간 제한은 별도 검증 필요.
> 

**GET `/v1/reports/{report_id}` (발췌)**

```
{"data":{"id":"550e8400-e29b-41d4-a716-446655440070","type":"surveyor","version":1,"status":"draft","items":[{"id":"550e8400-e29b-41d4-a716-446655440072","item_code":"phys_toilet_use","summary_text":"뒤처리를 도와드려야 함","detail_text":null,"included":true,"is_family_added":false,"is_top5":false,"sources":[{"record_id":"550e8400-e29b-41d4-a716-446655440020","recorded_at":"2026-10-13T19:40:00+09:00","source":"direct"}]}]}}
```

**PATCH `/v1/reports/{report_id}/items/{item_id}`**

```
{"summary_text":"화장실은 혼자 가시지만 뒤처리에는 도움이 필요함","detail_text":"실수하시는 날이 있었어요.","included":true}
```

- 세부사항 최대 **200자**, 근거 없는 가족 추가 문장은 `is_family_added=true`로 표시하고 AI가 원본처럼 꾸미지 않는다.
- **기록 없는 항목은 비워둔다**. 자료에 없는 내용 생성 금지.

**POST `/v1/reports/{report_id}/confirm`**

```
{"author_confirmed":true}
```

**200** `{"data":{"id":"550e8400-e29b-41d4-a716-446655440070","status":"confirmed","confirmed_at":"2026-10-25T11:00:00+09:00"}}`

- `author_confirmed=true` 요구, 서버에서 `confirmed_by`를 로그인 사용자로 기록. 확정 후 보고서 본문·항목·근거는 변경 금지.
- PDF는 확정 전 **403 `NOT_CONFIRMED`**. 흑백 A4 1~2장, 본문 12pt 이상 목표, 2장 초과는 내용 축약 안내.
- 보고서 출력 문구: **“가족이 작성한 평소 관찰 기록”**, 하단 **“이 기록은 가족의 관찰이며 판정은 공단이 합니다.”**
- `type=doctor` P1 의사 전달 1장; `type=appeal` P1 소명자료도 동일 확정·PDF 규칙. 진단/판정 추측 금지.

---

## 12. 모의 인터뷰·결과 이후 지원 — P1

**테이블:** `interview_sessions`, `interview_messages`, `reports`, `parents`; 일부 외부 자료/행정 기준은 DB 외부의 검증된 콘텐츠가 필요.

| Method | Endpoint | 기능 ID | 설명 |
| --- | --- | --- | --- |
| POST | `/v1/parents/{parent_id}/interviews` | W-SIM-001 | 영역 선택 후 AI 조사 질문 시작 |
| POST | `/v1/interviews/{session_id}/answers` | W-SIM-001 | 글/음성 답변 → 다음 질문, 중간 저장 |
| GET | `/v1/interviews/{session_id}/feedback` | W-SIM-002 | 기록과 다른 점·빠진 내용·원문 링크 |
| POST | `/v1/appeals/deadline-check` | W-APL-001 | 결과 인지일 기반 기한 안내 |
| GET | `/v1/appeals/options` | W-APL-002 | 이의신청/재신청/그대로 비교(검증 자료 필요) |
| GET | `/v1/regions/{sido}/{sigungu}/organizations` | W-ALT-001 | 지역 도움 기관 조회(정보 갱신일 포함) |
| POST | `/v1/documents/interpret` | W-NHI-001 | 서류 사진 OCR + 쉬운 설명, 즉시 삭제 |
| GET | `/v1/parents/{parent_id}/renewal` | W-RNW-001/002 | 판정 전후 기록 건수·새 보고서 경로 |

**모의 인터뷰**: 등급·점수·“더 나쁘게 말하세요” 등 표현 금지. 답변이 기록과 불일치하거나 누락된 부분을 근거와 함께 표시한다.

**행정 기한 주의:** 기능명세서에는 이의신청 90일·기관 연락처·금액 등의 구체적 수치/문구가 들어 있으나 **이 문서에서 법령상 정확성을 검증하지 않았다**. 따라서 API 계약에는 `result_known_on`, `deadline`, `rule_version`, `verified_at`, `source_url`처럼 출처·기준일을 반환하도록 제안한다. 실제 서비스에서는 최신 공식 자료 확인 후 적용하며, 검증되지 않은 수치를 하드코딩하지 않는다.

**POST `/v1/appeals/deadline-check`**

```
{"result_known_on":"2026-10-25"}
```

```
{"data":{"deadline":null,"rule_version":null,"verified_at":null,"message":"적용 기한 규정 확인 후 안내할 수 있습니다."}}
```

> 위 결과는 실제 규칙이 등록되지 않은 **안전한 미설정 예시**다. 규칙이 검증되면 기한을 계산해 채운다.
> 

---

## 13. 알림·설정 — P1

**테이블:** `notification_settings`, `devices`, `notifications`.

| Method | Endpoint | 기능 ID | 설명 |
| --- | --- | --- | --- |
| GET | `/v1/notifications` | POP_A_NOTI | 내 알림 목록, 읽음 여부 |
| PATCH | `/v1/notifications/{notification_id}/read` | POP_A_NOTI | 본인 알림 읽음 처리 |
| GET | `/v1/settings/notifications` | A-SET-002 | 알림 토글 조회 |
| PUT | `/v1/settings/notifications` | A-SET-002 | 컨디션/할 일/브리핑 켜기·끄기 |
| POST | `/v1/devices` | A-SET-002 | FCM/APNs 기기 등록 |
| DELETE | `/v1/devices/{device_id}` | A-SET-002 | 로그아웃·토큰 폐기 |

**PUT `/v1/settings/notifications`**

```
{"condition_enabled":true,"tasks_enabled":true,"briefing_enabled":false}
```

- 전날 브리핑 예정 시각 20:00, 할 일 마감 다음 날 오전 10:00 등은 **기능명세서의 알림 정책**. 알림을 꺼 두면 푸시를 보내지 않고 앱 내 D-day/할 일은 그대로 보여준다.
- 푸시는 서버 스케줄러/워커가 실행해야 하며 `notifications` 테이블만 생성해도 자동 발송되지는 않는다.

---

## 14. 데이터 무결성 및 보안 구현 계약

### 14.1 권한 확인 순서

1. Supabase access token의 서명·만료·대상 검증(초기에는 Supabase Auth 서버 확인).
2. `auth.users.id`와 서비스 `users.id` 연결. `login_type`은 개발 중 nullable 가능.
3. 필수 동의 및 부모님 관련 처리 권한 상태 확인(실제 건강정보 대상은 출시 전 법률 검토 기준 적용).
4. `family_members`에서 **해당 부모님** 역할 확인. 부모님을 알아낼 수 없는 UUID 요청에는 404 반환.
5. 수정·삭제·댓글·확정 등 개별 동작의 작성자 및 역할 확인.
6. 변경을 한 트랜잭션으로 적용, 필요 시 감사 이력 생성.

### 14.2 데이터 관련 중요 규칙

| 데이터/기능 | 규칙 |
| --- | --- |
| `records` | `original_text`, `audio_path`, `recorded_at`, `created_at` 일반 수정 금지 |
| `record_versions` | 원문 수정 전 상태를 자동·원자적으로 보존 |
| `record_items` | 허용된 `survey_items.code`만, `confidence` 0~1 |
| `conditions` | 부모님+날짜 당 최대 1행, 수정 시 이력 작성 |
| `tasks` | 체크리스트 담당자·대상 부모님·연결 기록 부모님 일치 확인 |
| `reports` | `confirmed` 이후 수정 금지, 재수정은 `version+1` 초안 |
| `report_item_sources` | 보고서와 근거 기록이 같은 부모님에 속해야 함 |
| `import_jobs` | 원본 파일 삭제 실패 시 정상 완료 처리하지 않음 |
| Storage | 비공개 버킷, 기기·클라이언트에 DB 비밀번호/서버 비밀키 노출 금지 |
| DB·RLS | 서비스 CRUD FastAPI만 허용, `anon/authenticated`의 직접 테이블 CRUD 제한 |

> **실제 마이그레이션 확인 사항:** 이미 실행한 v0.7 증분 SQL은 `survey_items.code`가 여전히 전역 PK이므로 `survey_versions`만으로 동일 코드를 서로 다른 조사표 버전에서 중복 정의할 수 없다. 버전별 항목 변경이 필요해지면 별도 마이그레이션이 필요하다. 또 기본 DB 트리거의 보호 범위와 실제 계정 삭제·법적 삭제 경로를 운영 전에 테스트해야 한다.
> 

### 14.3 개인정보 처리와 삭제

- 평상시 `hide/exclude`는 기록지 집계 제외이지 실제 삭제가 아니다.
- 사용자 탈퇴, 동의 철회, 정보주체의 삭제 요청은 `deletion_requests`로 접수하고 **DB/Storage/백업/외부 처리업체 데이터**까지 처리 범위를 결정하는 별도 절차가 필요하다.
- 정보 주체 적법성, 삭제 기한, 예외적 보존 의무는 개발자의 임의 정책으로 확정하지 않는다.

### 14.4 보안·성능·접근성 수용 기준

| ID | 기준 | 검증 방식 |
| --- | --- | --- |
| A-HOME-001 | 한 번 탭해 녹음 시작, 2초 미만 거부, 최대 180초, 전화 수신 일시정지 | 실기기 Flutter 테스트 |
| A-HOME-001 | 1분 녹음 후 저장 확인 10초 내 목표 | STT+네트워크 포함 성능 테스트 |
| A-HOME-002 | 오프라인 텍스트 작성 후 연결 시 손실 없이 업로드 | 네트워크 차단·재시도 테스트 |
| A-HOME-004 | 테스트 문장 20개 중 최소 16개 영역 정확 분류 | 팀 검증 세트 |
| A-DET-002 | 수정 후에도 원본·수정자·시간 확인 | DB 버전 이력 테스트 |
| W-DASH-001 | 앱 기록 작성 후 웹 새로고침 시 현황판 반영, 3초 내 로딩 목표 | E2E·성능 |
| W-REP-004/005 | 확정 전 PDF 차단, 문장별 근거 확인 | 권한·보고서 테스트 |
| W-UP-003/004 | 단톡방 원본 파일 남지 않음, 미선택 후보 저장 금지 | 작업 완료·삭제 검증 |
| POL-03 | 점수·예상 등급 반환하지 않음 | 응답 스키마 검사 |
| NFR | HTTPS, DB/Storage 보안, 접근성 대비 4.5:1·본문 16px·버튼 44px | 보안/접근성 테스트 |

---

## 15. 구현 단계와 엔드포인트 범위

| 단계 | 우선 | 구현 도메인 | 완료 체크 |
| --- | --- | --- | --- |
| 0 | 기반 | Auth 연동, DB 연결, 에러·권한 공통 함수, 동의 문서 등록 | JWT·프로필·권한 검사 |
| 1 | P0 | 동의 및 부모님 생성, 가족 admin 연결 | 가입→동의→부모님 등록 흐름 |
| 2 | **P0** | 텍스트/음성 기록, 원본 보존, AI 분류·실패 재시도 | 앱 기록 E2E |
| 3 | **P0** | 대시보드·타임라인, 사건 | 기록↔웹 집계 일치 |
| 4 | **P0** | 단톡방 비동기 작업, 후보 선택 | 원본 삭제·선택 기록만 저장 |
| 5 | **P0** | 보고서 초안·검토·확정·PDF | 근거 출처·확정 잠금 |
| 6 | P1 | 가족 초대·체크리스트·조사 일정·알림 | 공동 기록 및 브리핑 |
| 7 | P1/P2 | 증상·복용약·인터뷰·결과 후 지원·검색 | 기능별 시나리오 |

### API 코딩 전 확인해야 할 실제 DB/제품 갭

| 구분 | 현재 상태 | 결정/조치 |
| --- | --- | --- |
| Auth | `public.users.login_type` nullable; Supabase Auth 사용 | 프로필 생성 시 `id`만 입력 가능. 실제 공급자 정책 확인 |
| 동의 | `consent_documents` 테이블만 존재 | **실제 문구와 버전을 게시하기 전까지** 법적 동의 완료로 간주하지 않기 |
| 기록 상태 | `records.processing_status` 존재 | 비동기 AI 워커 및 상태 변경·에러 추적 구현 |
| 체크리스트 | `checklists`+`tasks` 존재, 과거 tasks는 묶음 없음 | 새 생성 API는 `checklist_id` 필수로 작성 |
| 보고서 AI Job | 별도 작업 테이블·`generation_status` 없음 | 동기 생성 또는 보고서 Job 스키마 추가 중 하나 선택 |
| QR 로그인 | QR 세션 테이블 없음 | P1 전에 추가 설계 |
| 조사표 버전 | 기존 `survey_items.code` PK | 본격적인 다중 조사표 버전 지원은 추가 마이그레이션 필요 |
| 저장소 | `audio_path`만 DB에 존재 | private Storage bucket·객체 정책·서명 링크 API 구현 |
| 알림 | 테이블만 존재 | 일정 작업·FCM/APNs 연동 별도 구현 |
| 건강정보 법적 근거 | 미확정 | 실제 정보 수집 전 전문 검토 필요 |

---

## 16. 변경 이력

- **v0.4 → v0.5 (2026-10-25):** 기능명세서 v0.4를 최상위 기준으로 재작성. Supabase Auth와 FastAPI 책임 분리, UUID·현재 DB enum·컬럼에 맞춰 예시 수정, AI 비동기/오프라인/수정 이력, 가족 권한, 보고서 근거/버전, DB v0.7 기능 추가분 반영. 부족한 DB 기능과 법적 미검증 사항은 명시적으로 표시.