# 실버케어 백엔드 아키텍처

> **스택**: Flutter(앱) · React/Next(웹) · **FastAPI(모든 로직)** · Supabase(Postgres·Auth·Storage)
**원칙**: 앱/웹은 FastAPI만 호출. Supabase는 "DB·인증·파일 저장소"로만 쓴다. 로직은 전부 FastAPI 안.
> 

---

## 1. 전체 구조

```
┌─────────────┐     ┌─────────────┐
│ Flutter 앱   │     │ React 웹     │
└──────┬──────┘     └──────┬──────┘
       │   HTTPS / REST (JWT)      │
       └───────────┬──────────────┘
                   ▼
         ┌───────────────────┐
         │     FastAPI        │  ← 모든 비즈니스 로직·권한·AI 호출
         │  router/service/   │
         │  repository        │
         └─────┬──────┬───────┘
               │      │
        ┌──────▼──┐ ┌─▼────────────┐
        │Supabase │ │ Celery 워커   │ ← STT·분류·단톡방·요약 (무거운 작업)
        │Postgres │ │ + Redis(큐)   │
        │Auth     │ └─┬────────────┘
        │Storage  │   │
        └─────────┘   ▼
                ┌──────────────┐
                │ 외부 AI API   │ STT(Whisper/Clova) · LLM(분류·요약)
                └──────────────┘
```

**역할 분담**

| 컴포넌트 | 담당 |
| --- | --- |
| **FastAPI** | 모든 엔드포인트·권한 검증·비즈니스 로직·AI 오케스트레이션 |
| **Supabase Auth** | 회원가입·로그인·JWT 발급 (직접 안 만듦) |
| **Supabase Postgres** | ERD 14개 테이블. FastAPI가 쿼리 |
| **Supabase Storage** | 음성·사진·단톡방 .txt 파일 |
| **Celery + Redis** | STT·분류·단톡방 처리 등 오래 걸리는 작업 비동기 |
| **외부 AI** | STT, LLM(분류·기록지 요약) |

---

## 2. FastAPI 레이어 구조

**4계층**으로 책임 분리. 요청이 위에서 아래로 흐른다.

```
Router (엔드포인트·입력검증)
  → Dependency (인증·권한 주입)
  → Service (비즈니스 로직)
  → Repository (DB 접근)
  → Supabase / Celery / AI
```

### 폴더 구조

```
app/
├── main.py                 # FastAPI 앱·미들웨어
├── core/
│   ├── config.py           # 환경변수 (Supabase URL/Key, AI Key)
│   ├── security.py         # JWT 검증 (Supabase 토큰)
│   └── deps.py             # 공통 의존성 (현재 유저·부모님 권한)
├── routers/                # 엔드포인트
│   ├── auth.py
│   ├── records.py
│   ├── coverage.py         # 현황판
│   ├── timeline.py
│   ├── imports.py          # 단톡방
│   ├── reports.py          # 기록지
│   ├── checklists.py
│   └── ...
├── services/               # 비즈니스 로직
│   ├── record_service.py
│   ├── coverage_service.py
│   ├── ai_service.py       # STT·분류·요약 호출
│   └── ...
├── repositories/           # DB 접근 (Supabase 쿼리)
│   ├── record_repo.py
│   └── ...
├── models/                 # Pydantic 스키마 (요청/응답)
├── workers/                # Celery 태스크
│   ├── transcribe.py       # 음성 → STT → 분류
│   ├── classify.py
│   └── import_kakao.py
└── db/
    └── supabase.py         # Supabase 클라이언트
```

### 각 계층 책임

| 계층 | 하는 일 | 하지 않는 일 |
| --- | --- | --- |
| **Router** | URL·HTTP 메서드·요청/응답 스키마·상태코드 | 비즈니스 로직 X |
| **Dependency** | JWT 검증, "이 유저가 이 부모님 가족인가" 권한 주입 | — |
| **Service** | 집계·분류 호출·규칙(POL) 적용 | DB 직접 접근 X |
| **Repository** | Supabase 쿼리(SELECT/INSERT) | 로직 X |

---

## 3. 인증 흐름 (Supabase Auth + FastAPI 검증)

Supabase가 로그인·토큰 발급을 하고, **FastAPI는 그 토큰을 검증만** 한다.

```
1. 앱 → Supabase Auth 로그인 (카카오/휴대폰) → JWT 받음
2. 앱 → FastAPI 요청 (Authorization: Bearer <JWT>)
3. FastAPI → JWT 서명 검증 (Supabase JWT Secret) → user_id 추출
4. 이후 모든 로직에서 user_id로 권한 판단
```

```python
# core/security.py
from jose import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer

bearer = HTTPBearer()

def get_current_user(cred = Depends(bearer)) -> str:
    try:
        payload = jwt.decode(
            cred.credentials,
            settings.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
        )
        return payload["sub"]           # user_id
    except Exception:
        raise HTTPException(401, "invalid token")
```

> 가입/온보딩은 Supabase Auth SDK로 앱이 직접(인증번호 발송 등). FastAPI는 로그인 이후만 담당.
> 

---

## 4. 권한 공통화 — 패턴 B의 핵심 (RLS 대체)

RLS 없이 **FastAPI 의존성 주입**으로 권한을 막는다. 건강정보라 이게 제일 중요.

```python
# core/deps.py
async def get_parent_access(
    parent_id: str,
    user_id: str = Depends(get_current_user),
    repo = Depends(get_family_repo),
) -> ParentAccess:
    """현재 유저가 이 부모님의 가족인지 + 권한(role) 확인."""
    member = await repo.find(parent_id, user_id)
    if not member:
        raise HTTPException(403, "이 부모님에 대한 권한이 없어요")
    return ParentAccess(parent_id=parent_id, user_id=user_id, role=member.role)

def require_write(access: ParentAccess = Depends(get_parent_access)):
    if access.role == "viewer":
        raise HTTPException(403, "보기 전용 권한이에요")
    return access
```

**모든 엔드포인트가 이 의존성을 통과** → 권한 누락 실수 방지.

```python
# routers/records.py
@router.post("/parents/{parent_id}/records/text")
async def create_text_record(
    parent_id: str, body: TextRecordIn,
    access = Depends(require_write),        # ← 가족+쓰기권한 보장
    svc = Depends(get_record_service),
):
    return await svc.create_text(access, body)
```

**권한 규칙표**

| 작업 | 규칙 |
| --- | --- |
| 조회 | 가족(viewer 포함) |
| 기록 생성·수정 | 가족 + role ≠ viewer |
| 남의 기록 수정 | 작성자 본인만 (타인 → 댓글만) |
| 가족 권한 변경 | 관리자만 (관리자 최소 1명) |
| 보존 필드(original_text 등) | 누구도 수정 불가 → 수정 시도 400 |

---

## 5. 핵심 플로우 설계

### 5-1. 음성 기록 (A-HOME-001) — 비동기

```
① 앱: 음성 녹음 → Supabase Storage 직접 업로드 (파일 경로 획득)
② 앱 → FastAPI: POST /records/audio { storage_path, source }
③ FastAPI: records row 생성 (status=processing) → Celery 태스크 큐잉 → 즉시 응답(record_id)
④ Celery 워커: Storage에서 파일 → STT → LLM 분류(52항목) → record_items 저장 → status=done
⑤ 앱: record_id로 폴링 or Supabase Realtime 구독으로 완료 감지 → 저장 확인 카드
```

> **왜 비동기?** STT+분류가 수 초~십수 초 걸림. 동기로 하면 요청이 타임아웃. 완료기준 "10초 이내"는 워커 처리 속도로 맞춤.
**오프라인(TC-2.7)**: 앱이 로컬(Drift)에 먼저 저장 → 연결되면 ①부터 실행. `Idempotency-Key`로 중복 방지.
> 

### 5-2. 단톡방 불러오기 (W-UP) — 비동기 Job

```
① 앱/웹 → Storage에 .txt 업로드
② → FastAPI: POST /imports { storage_path, period_months } → Celery Job 생성(202)
③ 워커: 파싱 → 부모님 문장 추출 → 분류 → 후보 저장 → 원본 파일 삭제
④ 앱 → GET /imports/{job_id} 폴링 (진행률)
⑤ 후보 확인 → POST /imports/{job_id}/save (체크한 것만)
```

### 5-3. 현황판 (W-DASH-001) — 동기 집계

```
GET /parents/{pid}/coverage
→ Service: record_items를 item_code별 GROUP BY + 최근 날짜 집계
→ 52항목 마스터와 조인 → 충분/부족/없음 판정 (점수·등급 X, POL-03)
→ 응답
```

> 복잡한 집계라 Supabase 자동 API보다 **FastAPI에서 SQL/뷰로 처리**가 자유로움. 무거우면 Materialized View나 캐시.
> 

### 5-4. 기록지 생성 (W-REP-001) — 비동기(LLM)

```
POST /reports { type, period } → Celery: 항목별 기록 모아 LLM 요약(근거 날짜 연결) → 초안 저장
확정(POST /reports/{id}/confirm) 전까지 PDF 잠금(POL-01)
```

---

## 6. 외부 연동 (AI)

| 작업 | 1차 선택 | 대안 | 비고 |
| --- | --- | --- | --- |
| STT (음성→글) | Whisper (자체 호스팅) | 네이버 Clova, Google STT | 노인 한국어 발화 정확도로 베타 전 비교 |
| 분류 (글→52항목) | LLM API (프롬프트) | 파인튜닝(나중) | 52항목 label을 프롬프트에 주입, code로 반환 |
| 기록지 요약 | LLM API | — | 환각 방지 가드레일(기록 없는 항목 비움) |
| OCR (약·서류) | Google Vision / Clova OCR | — | 처리 후 사진 삭제 |

> **비용 주의**: STT·LLM은 호출당 과금. "기록 1건당 원가" 계산 필요. Whisper 자체 호스팅으로 STT 비용 절감 가능.
> 

---

## 7. 데이터 접근 (Supabase as DB)

FastAPI는 Supabase를 **service_role 키**로 접근(RLS 우회) — 권한은 FastAPI가 책임지므로.

```python
# db/supabase.py
from supabase import create_client
supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
```

> ⚠️ `service_role` 키는 **서버에만** 둔다. 앱/웹엔 절대 노출 금지(모든 RLS 우회 가능).
앱이 Storage에 직접 업로드할 때만 `anon` 키 + Storage 정책 사용.
> 

**보존 필드 가드 (POL-02)**: DB 트리거로 2중 방어

```sql
create trigger protect_original before update on records
for each row execute function reject_protected_fields();
-- original_text, audio_url, recorded_at 변경 시 예외
```

---

## 8. 배포

| 구성 | 방법 |
| --- | --- |
| FastAPI | Docker 컨테이너 (Railway/Render/Fly.io 등 — 베타엔 관리형) |
| Celery 워커 | 별도 컨테이너 (같은 이미지, 커맨드만 다름) |
| Redis | 관리형 (Upstash 등) |
| DB·Auth·Storage | Supabase (관리형) |
| 웹(Next) | Vercel |
| 앱(Flutter) | Google Play (베타 트랙) |

> 베타는 **관리형 서비스로 운영 부담 최소화**. 트래픽 늘면 그때 최적화.
> 

---

## 9. 환경변수 (.env)

```
SUPABASE_URL=
SUPABASE_SERVICE_KEY=        # 서버 전용, 절대 노출 금지
SUPABASE_JWT_SECRET=         # 토큰 검증용
SUPABASE_ANON_KEY=           # 앱 Storage 업로드용 (앱에만)
REDIS_URL=
OPENAI_API_KEY= / LLM_KEY=
STT_API_KEY=
OCR_API_KEY=
```

---

## 10. 앞선 문서에서 바뀌는 점 (패턴 B 확정 반영)

| 문서 | 변경 |
| --- | --- |
| **API 명세서** | 🟢 거의 유지 — 전부 FastAPI 엔드포인트. multipart → "Storage 업로드 후 경로 전달"로만 조정 |
| **권한** | 🟡 RLS 대신 **FastAPI 의존성(get_parent_access)** 으로. 보존 필드만 DB 트리거 2중 방어 |
| **ERD** | 🟢 그대로. `users.id` = Supabase `auth.users.id` 공유만 명시 |
| **파일** | 🟡 Supabase Storage. 음성·사진·txt 버킷 분리 |
| **앱(Flutter)** | 🟢 FastAPI만 호출(+Storage 직접 업로드, Realtime으로 완료 감지는 선택). 로컬 Drift + 동기화 |
| **테스트** | 🟡 TS-7 권한 테스트를 "FastAPI 의존성 단위 테스트"로 |

---

## 11. 다음 할 일

1. **API 명세서 v2** — 패턴 B 반영(비동기 플로우·Storage·에러코드) 미세 업데이트
2. **AI 분류 설계** — STT 3종 비교·분류 프롬프트·테스트 세트 20문장 (리스크 1순위)
3. **DB 마이그레이션 SQL** — ERD → Supabase 테이블 생성 + 보존 트리거
4. **앱 동기화 설계** — Flutter 로컬 DB·오프라인 큐·음성 Platform Channel