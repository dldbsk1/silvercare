"""내 정보·온보딩 상태 (GET /v1/auth/me). 트랜잭션은 라우터가 연다."""
from sqlalchemy.orm import Session

from app.repositories import parent_repo, user_repo
from app.services import consent_service


def get_me(db: Session, user_id: str) -> dict:
    user = user_repo.get_user(db, user_id)
    consent_status = consent_service.get_status(db, user_id)
    parents = parent_repo.list_for_user(db, user_id)

    return {
        "user": {
            "id": str(user["id"]),
            "login_type": user["login_type"],
        },
        "onboarding": {
            "consents_completed": consent_status["completed"],
            "missing_consents": consent_status["missing_required"],
            "parent_registered": bool(parents),
        },
        "parent_ids": [str(parent["id"]) for parent in parents],
    }
