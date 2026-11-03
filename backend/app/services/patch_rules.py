"""PATCH 공통 검사 (기록·부모님·내 정보)

- 바꿀 수 없는 칸 → 400 IMMUTABLE_FIELD
- 알 수 없는 칸 → 422 VALIDATION_ERROR
- 빈 요청 {} → 400 INVALID_REQUEST
- 비울 수 없는 칸에 null → 422 VALIDATION_ERROR
- 안 보낸 칸 / null로 보낸 칸 구분: model_fields_set
- 스키마 조건: model_config extra="allow" (모르는 칸을 받아서 여기서 판정)
"""
from pydantic import BaseModel

from app.core.errors import AppError


def check_patch(body: BaseModel, immutable: set[str], nullable: set[str]) -> set[str]:
    """보낸 칸 반환"""
    extra = set(body.model_extra or {})

    blocked = extra & immutable
    if blocked:
        raise AppError(
            400, "IMMUTABLE_FIELD", "바꿀 수 없는 항목이 있어요.",
            details={"fields": sorted(blocked)}
        )
    if extra:
        raise AppError(
            422, "VALIDATION_ERROR", "알 수 없는 항목이 있어요.",
            details={"fields": sorted(extra)}
        )

    sent = set(body.model_fields_set)
    if not sent:
        raise AppError(400, "INVALID_REQUEST", "바꿀 내용이 없어요.")

    for field in sorted(sent - nullable):
        if getattr(body, field) is None:
            raise AppError(
                422, "VALIDATION_ERROR", "비울 수 없는 항목이에요.",
                details={"fields": [field]}
            )

    return sent
