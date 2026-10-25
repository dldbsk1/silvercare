from typing import Generic, TypeVar

from pydantic import BaseModel, Field


T = TypeVar("T")


class DataResponse(BaseModel, Generic[T]):
    """단일 객체 응답: {"data": ..., "meta": {}}"""

    data: T
    meta: dict = Field(default_factory=dict)


class ListMeta(BaseModel):
    next_cursor: str | None = None
    has_more: bool = False


class ListResponse(BaseModel, Generic[T]):
    """목록 응답 (커서 기반)"""

    data: list[T]
    meta: ListMeta = Field(default_factory=ListMeta)


class JobAccepted(BaseModel):
    """비동기 작업 접수 응답 (202)"""

    job_id: str
    status: str
