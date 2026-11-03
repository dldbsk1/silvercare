"""고아 음성 파일 정리 (업로드만 되고 기록이 안 만들어진 파일)

1. 트랜잭션: 대상 선점 (SKIP LOCKED) → 참조 재확인 → expired (삭제 예정)
2. 트랜잭션 밖: Storage 삭제 (DB 잠금 없음)
3. 트랜잭션: storage_deleted_at

- expired → 기록 생성 API 사용 불가 (410 UPLOAD_EXPIRED)
- Storage 삭제 실패 / 3단계 실패 → expired + storage_deleted_at NULL 유지 → 다음 실행에서 재시도
- 없는 파일 삭제 → 오류 아님 → 재실행 안전
- 유예: 서명 URL 만료 후 7일 (멱등 키 보관 기간과 같음, 앱 재전송 기간 보호)
"""
import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import storage
from app.repositories import upload_repo


logger = logging.getLogger("silvercare.cleanup")

GRACE_DAYS = 7
BATCH_SIZE = 100


def run(db: Session) -> int:
    """삭제 완료 건수"""
    with db.begin():
        targets = select_targets(db)

    if not targets:
        return 0

    paths = [t["audio_path"] for t in targets]
    try:
        storage.remove_objects(settings.STORAGE_AUDIO_BUCKET, paths)
    except Exception:
        logger.exception("Storage 삭제 실패 %d건, 다음 실행에서 재시도", len(paths))
        return 0

    with db.begin():
        upload_repo.mark_storage_deleted(db, [str(t["id"]) for t in targets])

    logger.info("고아 음성 파일 삭제 %d건", len(targets))
    return len(targets)


def select_targets(db: Session) -> list[dict]:
    targets = []

    for upload in upload_repo.claim_cleanup(db, GRACE_DAYS, BATCH_SIZE):
        record_id = upload_repo.record_id_for_path(db, upload["audio_path"])

        if record_id is not None:
            if upload["status"] == "issued":
                upload_repo.repair_consumed(db, str(upload["id"]), record_id)
                logger.warning("기록 참조 중인 업로드 바로잡음 %s", upload["id"])
            else:
                logger.error("expired 업로드를 기록이 참조, 삭제 보류 %s", upload["id"])
            continue

        if upload["status"] == "issued":
            upload_repo.mark_expired(db, str(upload["id"]))
        targets.append(dict(upload))

    return targets
