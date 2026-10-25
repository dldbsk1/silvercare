"""개발용 동의 문구 4종을 consent_documents에 넣는다.

- ENV=local일 때만 실행된다 (운영 DB에 가짜 법률 문구가 들어가지 않도록)
- 버전은 'dev-'로 시작한다. 운영(ENV != local)에서는 동의 API가 dev- 문구를 쓰지 않는다
- 여러 번 실행해도 결과가 같다

    cd backend
    python -m scripts.seed_dev_consents
"""
from sqlalchemy import text

from app.core.config import settings
from app.db.session import new_session


DEV_DOC_VERSION = "dev-0.1"
NOTICE = "[개발용] 실제 약관·동의 문구가 아닙니다. 테스트에만 사용하세요."

DOCUMENTS = [
    ("service", "서비스 이용 동의", True),
    ("privacy", "개인정보 수집·이용 동의", True),
    ("health", "건강정보(민감정보) 처리 동의", True),
    ("noti", "알림 수신 동의", False),
]


def main():
    if settings.ENV != "local":
        raise SystemExit(f"ENV={settings.ENV}: 개발 환경에서만 실행할 수 있습니다.")

    with new_session() as db:
        with db.begin():
            for consent_type, title, required in DOCUMENTS:
                db.execute(
                    text("""
                        INSERT INTO consent_documents
                            (type, doc_version, title, content, required)
                        VALUES
                            (CAST(:type AS consent_type_enum), :doc_version,
                             :title, :content, :required)
                        ON CONFLICT (type, doc_version) DO NOTHING
                    """),
                    {
                        "type": consent_type,
                        "doc_version": DEV_DOC_VERSION,
                        "title": f"[개발용] {title}",
                        "content": NOTICE,
                        "required": required
                    }
                )

        rows = db.execute(
            text("""
                SELECT type::text, doc_version, required, retired_at
                FROM consent_documents
                ORDER BY type
            """)
        ).all()

    for row in rows:
        print(tuple(row))


if __name__ == "__main__":
    main()
