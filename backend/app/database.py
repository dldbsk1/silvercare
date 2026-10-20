from sqlalchemy import create_engine, text
from app.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    # Supabase transaction pooler(6543)는 prepared statement 미지원
    connect_args={"prepare_threshold": None}
)

def check_database():
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT 1")
        ).scalar_one()
