"""migrations/ 파일 하나를 DB에 적용 (파일 전체 = 트랜잭션 하나)

    cd backend
    python -m scripts.apply_migration migrations/006_family_invites.sql

- 같은 파일 두 번 적용 X (이미 있는 컬럼·트리거 → 오류, 변경 없음)
- psycopg 직접 실행 (SQL 안의 % 문자 그대로)
"""
import sys
from pathlib import Path

from app.db.session import engine


def main():
    if len(sys.argv) != 2:
        raise SystemExit("사용법: python -m scripts.apply_migration migrations/<파일>.sql")

    path = Path(sys.argv[1])
    sql = path.read_bytes()

    raw = engine.raw_connection()
    try:
        connection = raw.driver_connection
        connection.cursor().execute(sql)
        connection.commit()
    finally:
        raw.close()

    print(f"적용 완료: {path.name}")


if __name__ == "__main__":
    main()
