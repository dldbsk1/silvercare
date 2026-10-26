"""기록 AI 작업

classify_record: payload {record_id, text_version}
1. 트랜잭션 A: 버전 확인 + processing
2. AI 호출 (트랜잭션 밖, DB 연결 점유 X)
3. 트랜잭션 B: 행 잠금 + 버전 재확인 → 저장
"""
from app.ai.provider import get_record_classifier
from app.services import classification_service
from app.services.classification_service import StaleClassification
from app.workers.tasks import JobSuperseded, task


def mark_record_failed(db, payload):
    with db.begin():
        classification_service.mark_failed(
            db, payload["record_id"], payload["text_version"]
        )


@task(classification_service.CLASSIFY_JOB, on_failure=mark_record_failed)
def classify_record(db, payload):
    record_id = payload["record_id"]
    text_version = payload["text_version"]

    try:
        with db.begin():
            text = classification_service.start(db, record_id, text_version)

        if text is None:
            return

        results = get_record_classifier().classify(text) if text else []

        with db.begin():
            classification_service.save_result(db, record_id, text_version, results)

    except StaleClassification as e:
        raise JobSuperseded(str(e)) from e
