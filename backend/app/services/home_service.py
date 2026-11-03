"""홈 묶음 조회 (A-HOME-007~009). 트랜잭션은 라우터가 연다.

- 최근 기록: status=normal 3건 (처리 중·실패 표시, 제외 기록 X)
- 앱 표시 구분: processing_status + stage + processing_error
"""
from sqlalchemy.orm import Session

from app.repositories import parent_repo, record_repo
from app.services import dday, record_service
from app.services.access import ParentAccess


RECENT_RECORDS = 3


def get_home(db: Session, access: ParentAccess) -> dict:
    parent = parent_repo.get_for_user(db, access.parent_id, access.user_id)
    today = dday.today_kst()
    records = record_repo.list_records(db, access.parent_id, "normal", RECENT_RECORDS)

    return {
        "today": today,
        "parent": {
            "id": str(parent["id"]),
            "nickname": parent["nickname"],
            "apply_stage": parent["apply_stage"],
            "judged_date": parent["judged_date"],
            "my_role": parent["my_role"],
        },
        "dday": dday.compute(parent["survey_date"], today),
        "recent_records": [
            record_service.to_list_item(record, access.user_id) for record in records
        ],
    }
