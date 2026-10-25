from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    # Supabase transaction pooler(6543)는 prepared statement 미지원
    connect_args={"prepare_threshold": None}
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False
)


def get_db():
    """요청 하나에 세션 하나. 트랜잭션은 라우터가 db.begin()으로 연다 (service는 그 안에서 실행)."""
    with SessionLocal() as db:
        yield db


def new_session() -> Session:
    """워커 등 요청 밖에서 쓰는 세션."""
    return SessionLocal()
