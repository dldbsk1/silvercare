"""실제 Supabase DB로 API를 테스트한다.

테스트 하나 = DB 트랜잭션 하나. 코드 안의 db.begin()은 SAVEPOINT가 되고,
테스트가 끝나면 전부 롤백하므로 DB에 데이터가 남지 않는다.
로그인은 가짜 사용자로 바꾸고, 그 사용자는 auth.users에 트랜잭션 안에서만 만든다.
"""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import AuthUser, get_auth_user
from app.db.session import engine, get_db
from app.main import app


@pytest.fixture
def db():
    connection = engine.connect()
    outer = connection.begin()
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        autoflush=False,
        expire_on_commit=False
    )
    yield session
    session.close()
    outer.rollback()
    connection.close()


def run_sql(session: Session, query: str, **params):
    """테스트에서 직접 SQL 실행. 끝나면 트랜잭션을 닫는다 (SAVEPOINT 해제만, 바깥은 나중에 롤백)

    닫지 않으면 앱 코드의 db.begin()이 "이미 트랜잭션 중" 오류를 낸다.
    """
    result = session.execute(text(query), params)
    rows = result.all() if result.returns_rows else None
    session.commit()
    return rows


def sql_scalar(session: Session, query: str, **params):
    return run_sql(session, query, **params)[0][0]


def create_auth_user(session: Session) -> str:
    user_id = str(uuid.uuid4())
    run_sql(
        session,
        """
            INSERT INTO auth.users (id, aud, role, email)
            VALUES (:id, 'authenticated', 'authenticated', :email)
        """,
        id=user_id, email=f"{user_id}@test.invalid"
    )
    return user_id


class ApiClient(TestClient):
    """로그인 사용자를 바꿔 가며 요청할 수 있는 TestClient"""

    def login(self, user_id: str):
        app.dependency_overrides[get_auth_user] = lambda: AuthUser(
            id=user_id, provider="email", phone=None
        )


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    client = ApiClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def user_id(db, client):
    user_id = create_auth_user(db)
    client.login(user_id)
    return user_id


@pytest.fixture
def other_user_id(db):
    return create_auth_user(db)


@pytest.fixture
def consent_docs(db):
    """테스트 전용 동의 문구. 기존 문구는 이 트랜잭션 안에서만 폐기 처리한다"""
    version = "test-1"
    run_sql(
        db,
        "UPDATE consent_documents SET retired_at = now() WHERE retired_at IS NULL"
    )
    for consent_type, required in [
        ("service", True), ("privacy", True), ("health", True), ("noti", False)
    ]:
        run_sql(
            db,
            """
                INSERT INTO consent_documents
                    (type, doc_version, title, content, required, published_at)
                VALUES
                    (CAST(:type AS consent_type_enum), :version, '테스트',
                     '테스트 문구', :required, now() - interval '1 minute')
            """,
            type=consent_type, version=version, required=required
        )
    return version


def agree_all(client, version, noti=True):
    return client.post("/v1/consents", json={"items": [
        {"type": "service", "doc_version": version, "agreed": True},
        {"type": "privacy", "doc_version": version, "agreed": True},
        {"type": "health", "doc_version": version, "agreed": True},
        {"type": "noti", "doc_version": version, "agreed": noti},
    ]})
