from datetime import date

from pydantic import BaseModel

from app.schemas.parents import ApplyStage, DdayOut, FamilyRole
from app.schemas.records import RecordListItemOut


class HomeParentOut(BaseModel):
    id: str
    # 가족 공통 호칭 (관리자가 정함, 가족 모두 같은 값)
    nickname: str
    apply_stage: ApplyStage
    judged_date: date | None
    my_role: FamilyRole


class HomeOut(BaseModel):
    """A-HOME-007~009. 컨디션·할 일: B단계에서 칸 추가 (기존 칸 변경 X)"""

    # 한국 시간 기준 오늘 (D-day 계산 기준)
    today: date
    parent: HomeParentOut
    dday: DdayOut
    # 정상 기록 최신 3건 (처리 중·실패 포함, 제외 기록 X). recorded_at DESC, id DESC
    recent_records: list[RecordListItemOut]
