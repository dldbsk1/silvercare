"""부모님 등록·조회·수정 (기능명세서 A-ON-003, A-SET). 트랜잭션은 라우터가 연다.

수정 (관리자만)
- 날짜 규칙: 판정일 미래 X, 조사일 1년 넘는 미래 X
- 판정일 < 조사일 X (요청값 + 기존값 합친 최종 상태 기준). 갱신 준비(renewal) 예외
- 조사일 변경·비움 → 판정일·신청 단계 자동 변경 X
- 범위: 조사 일정 1회분. 재신청·다회차 이력은 추후 신청 이력 모델
"""
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.repositories import parent_repo
from app.schemas.parents import (
    PARENT_IMMUTABLE_FIELDS,
    PARENT_NULLABLE_FIELDS,
    ParentCreateIn,
    ParentUpdateIn,
)
from app.services import account_service, dday
from app.services.access import ParentAccess
from app.services.patch_rules import check_patch


SURVEY_DATE_MAX_AHEAD = timedelta(days=366)


def to_out(row, today: date | None = None) -> dict:
    return {
        **dict(row),
        "id": str(row["id"]),
        "dday": dday.compute(row["survey_date"], today or dday.today_kst()),
    }


def create_parent(db: Session, user_id: str, body: ParentCreateIn) -> dict:
    """부모님 프로필 생성 + 만든 사람 = 관리자. 같은 트랜잭션 안에서 실행돼야 한다"""
    account_service.lock_active_user(db, user_id)
    parent_id = parent_repo.create_parent(
        db, body.nickname, body.age_band, body.apply_stage, body.cohabiting
    )
    parent_repo.add_member(db, parent_id, user_id, "admin")

    return to_out(parent_repo.get_for_user(db, parent_id, user_id))


def get_parent(db: Session, user_id: str, parent_id: str) -> dict:
    row = parent_repo.get_for_user(db, parent_id, user_id)
    if row is None:
        raise AppError(404, "NOT_FOUND", "부모님 정보를 찾을 수 없어요.")
    return to_out(row)


def list_parents(db: Session, user_id: str) -> list[dict]:
    today = dday.today_kst()
    return [to_out(row, today) for row in parent_repo.list_for_user(db, user_id)]


def update_parent(db: Session, access: ParentAccess, body: ParentUpdateIn) -> dict:
    """관리자 확인은 AdminAccess. 행 잠금 → 최종 상태 검증 → 바뀐 칸만 저장"""
    sent = check_patch(body, PARENT_IMMUTABLE_FIELDS, PARENT_NULLABLE_FIELDS)

    current = parent_repo.get_for_update(db, access.parent_id)
    fields = {
        field: getattr(body, field)
        for field in sent
        if getattr(body, field) != current[field]
    }

    check_dates({**dict(current), **fields}, dday.today_kst())

    if fields:
        parent_repo.update_fields(db, access.parent_id, fields)

    return get_parent(db, access.user_id, access.parent_id)


def check_dates(state: dict, today: date):
    survey_date = state["survey_date"]
    judged_date = state["judged_date"]

    if survey_date is not None and survey_date > today + SURVEY_DATE_MAX_AHEAD:
        raise AppError(400, "INVALID_REQUEST", "조사일이 너무 먼 미래예요.")

    if judged_date is not None and judged_date > today:
        raise AppError(400, "INVALID_REQUEST", "판정일은 이미 지난 날짜만 넣을 수 있어요.")

    if (
        state["apply_stage"] != "renewal"
        and survey_date is not None
        and judged_date is not None
        and judged_date < survey_date
    ):
        raise AppError(400, "INVALID_REQUEST", "판정일이 조사일보다 빨라요.")
