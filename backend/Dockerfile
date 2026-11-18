# silvercare 백엔드 — API 서버·워커 같은 이미지, 실행 명령만 다르게
#
#   docker build -t silvercare-backend .
#   API 서버: docker run --env-file .env.production -p 8000:8000 silvercare-backend
#   워커:     docker run --env-file .env.production silvercare-backend python -m app.workers.worker
#   워커 (Cloud Run, 요청 올 때만): python -m app.workers.http  → deploy/cloud-run.md
#
# 환경 변수: .env.production.example 참고 (이미지에 .env 포함 X → 배포처 설정에서 주입)

FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

WORKDIR /app

# 의존성 먼저 (코드만 바뀌면 이 층 재사용)
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY migrations ./migrations
COPY scripts ./scripts

# root 아닌 사용자로 실행
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# 기본: API 서버. 앞단 프록시 IP 처리는 앱 TRUSTED_PROXY_HOPS로 (uvicorn 쪽 X)
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
