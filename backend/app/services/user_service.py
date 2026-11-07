"""내 정보·온보딩 상태 (GET·PATCH /v1/auth/me). 트랜잭션은 라우터가 연다."""
from sqlalchemy.orm import Session

from app.repositories import parent_repo, user_repo
from app.schemas.auth import ME_IMMUTABLE_FIELDS, MeUpdateIn
from app.services import consent_service
from app.services.patch_rules import check_patch


def get_me(db: Session, user_id: str) -> dict:
    user = user_repo.get_user(db, user_id)
    consent_status = consent_service.get_status(db, user_id)
    parents = parent_repo.list_for_user(db, user_id)

    return {
        "user": {
            "id": str(user["id"]),
            "login_type": user["login_type"],
            "display_name": user["display_name"],
        },
        "onboarding": {
            "consents_completed": consent_status["completed"],
            "missing_consents": consent_status["missing_required"],
            "name_set": user["display_name"] is not None,
            # 접근 가능한 부모님 공간 1개 이상 (직접 등록 또는 초대 수락)
            "parent_registered": bool(parents),
        },
        "parent_ids": [str(parent["id"]) for parent in parents],
    }


def update_me(db: Session, user_id: str, body: MeUpdateIn) -> dict:
    check_patch(body, ME_IMMUTABLE_FIELDS, nullable=set())
    user_repo.set_display_name(db, user_id, body.display_name)
    return get_me(db, user_id)
