"""동의 (POL-05, 기능명세서 A-ON-002 / A-SET-001).

- 필수: 서비스 이용·개인정보·건강정보. 선택: 알림
- 동의 이력은 지우지 않고 revoked_at으로 철회를 표시한다
- 동의 문구가 새 버전으로 바뀌면 이전 버전 동의는 "완료"로 보지 않는다 (다시 동의)
- 운영(ENV != local)에서는 개발용(dev-) 문구를 유효한 문구로 보지 않는다
- 필수 문구가 하나라도 발행되지 않았으면 누구도 동의 완료가 아니다
- family_share: 가입 동의 X. 초대 수락 때 부모님별 동의 (family_members에 기록)
- 필수 동의 철회 → 삭제 예약 (내가 쓴 기록, deletion_service). 예정일 전 다시 동의 → 예약 취소

트랜잭션은 라우터가 연다.
"""
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.repositories import consent_repo
from app.services import deletion_service


REQUIRED_TYPES = ("service", "privacy", "health")
SHARE_TYPE = "family_share"


def published_documents(db: Session) -> dict[str, dict]:
    if settings.ENV == "local":
        rows = consent_repo.list_active_documents(db)
    else:
        rows = consent_repo.list_active_documents_excluding_dev(db)
    return {row["type"]: dict(row) for row in rows}


def active_documents(db: Session) -> dict[str, dict]:
    """가입 동의 문서 (가족 공유 동의 제외)"""
    return {
        t: doc for t, doc in published_documents(db).items() if t != SHARE_TYPE
    }


def share_document(db: Session) -> dict | None:
    """가족 공유 동의 문서 (초대 미리보기·수락). 미발행 → None"""
    return published_documents(db).get(SHARE_TYPE)


def required_types(documents: dict[str, dict]) -> list[str]:
    extra = [t for t, doc in documents.items() if doc["required"]]
    return sorted(set(REQUIRED_TYPES) | set(extra))


def list_required_documents(db: Session) -> list[dict]:
    documents = active_documents(db)
    required = required_types(documents)

    return [
        {**doc, "required": doc["type"] in required}
        for doc in sorted(documents.values(), key=lambda d: d["type"])
    ]


def get_status(db: Session, user_id: str) -> dict:
    documents = active_documents(db)
    consents = consent_repo.list_active_consents(db, user_id)

    current = []
    agreed_latest = set()

    for consent in consents:
        doc = documents.get(consent["type"])
        is_latest = doc is not None and doc["doc_version"] == consent["doc_version"]
        if is_latest:
            agreed_latest.add(consent["type"])
        current.append({
            "type": consent["type"],
            "doc_version": consent["doc_version"],
            "agreed_at": consent["agreed_at"],
            "is_latest": is_latest,
        })

    missing = [
        t for t in required_types(documents)
        if t not in agreed_latest
    ]

    return {
        "completed": not missing,
        "missing_required": missing,
        "current": current,
        "deletion_scheduled_for": deletion_service.consent_withdrawal_scheduled_for(db, user_id),
    }


def get_my_consents(db: Session, user_id: str) -> dict:
    return {
        **get_status(db, user_id),
        "history": [
            dict(row) for row in consent_repo.list_consent_history(db, user_id)
        ],
    }


def save_consents(db: Session, user_id: str, items: list) -> dict:
    """제출한 항목만 반영한다. 온보딩은 4개를 한 번에, 설정 화면은 알림 1개만 보낼 수 있다."""
    consent_repo.lock_user(db, user_id)

    documents = active_documents(db)
    required = required_types(documents)
    active = {c["type"]: c for c in consent_repo.list_active_consents(db, user_id)}

    for item in items:
        doc = documents.get(item.type)

        # 클라이언트가 임의 버전을 만들어 동의할 수 없다 (API 명세서 2장)
        if doc is None or doc["doc_version"] != item.doc_version:
            raise AppError(
                400, "INVALID_REQUEST",
                "동의 문구가 바뀌었어요. 화면을 새로 고쳐 주세요.",
                details={"type": item.type}
            )

        if not item.agreed:
            if item.type in required:
                raise AppError(
                    403, "CONSENT_REQUIRED", "필수 동의를 완료해 주세요.",
                    details={"type": item.type}
                )
            consent_repo.revoke_consents(db, user_id, item.type)
            continue

        current = active.get(item.type)
        if current is not None and current["doc_version"] == item.doc_version:
            continue

        # 이전 버전 동의가 남아 있으면 철회하고 새 버전으로 동의
        consent_repo.revoke_consents(db, user_id, item.type)
        consent_repo.insert_consent(db, user_id, item.type, item.doc_version)

    status = get_status(db, user_id)
    if status["completed"] and status["deletion_scheduled_for"] is not None:
        deletion_service.cancel_consent_withdrawal(db, user_id)
        status = get_status(db, user_id)
    return status


def revoke(db: Session, user_id: str, consent_type: str) -> dict:
    """철회. 필수 동의 → 기록 기능 중지 (ConsentedUser 의존성) + 삭제 예약 (예정일 응답)"""
    consent_repo.lock_user(db, user_id)

    if consent_repo.revoke_consents(db, user_id, consent_type) == 0:
        raise AppError(404, "NOT_FOUND", "철회할 동의가 없어요.")

    if consent_type in required_types(active_documents(db)):
        deletion_service.schedule_consent_withdrawal(db, user_id)

    return get_status(db, user_id)


def ensure_completed(db: Session, user_id: str):
    status = get_status(db, user_id)
    if not status["completed"]:
        raise AppError(
            403, "CONSENT_REQUIRED", "필수 동의를 완료해 주세요.",
            details={"missing": status["missing_required"]}
        )
