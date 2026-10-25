from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy ORM 모델 기반 클래스.

    테이블은 Supabase에 SQL 마이그레이션으로 이미 만들어져 있다.
    모델은 기존 테이블에 매핑만 하고 create_all()은 쓰지 않는다.
    """
