import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException


logger = logging.getLogger("silvercare.api")


class AppError(Exception):
    """비즈니스 오류. API 명세서 0.2의 오류 코드를 사용한다."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details=None
    ):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def service_unavailable(service: str) -> AppError:
    """외부 서비스(Supabase Auth/Storage, AI) 장애. 앱은 "잠시 후 다시" 안내"""
    return AppError(
        503, "SERVICE_UNAVAILABLE",
        "잠시 후 다시 시도해 주세요.",
        details={"service": service}
    )


# FastAPI 기본 HTTPException을 공통 코드로 바꿀 때 사용
DEFAULT_CODES = {
    400: "INVALID_REQUEST",
    401: "UNAUTHORIZED",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    405: "INVALID_REQUEST",
    409: "CONFLICT",
    413: "FILE_TOO_LARGE",
    429: "RATE_LIMITED",
}


def error_response(
    status_code: int,
    code: str,
    message: str,
    details=None,
    headers=None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details
            }
        },
        headers=headers
    )


def register_exception_handlers(app: FastAPI):

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError):
        return error_response(
            exc.status_code, exc.code, exc.message, exc.details
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request,
        exc: StarletteHTTPException
    ):
        code = DEFAULT_CODES.get(exc.status_code, "INTERNAL_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else code
        return error_response(
            exc.status_code, code, message,
            headers=getattr(exc, "headers", None)
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError
    ):
        return error_response(
            422, "VALIDATION_ERROR", "입력값을 확인해 주세요.",
            details=jsonable_errors(exc)
        )

    @app.exception_handler(OperationalError)
    async def handle_database_unavailable(
        request: Request,
        exc: OperationalError
    ):
        logger.exception(
            "DB 연결 실패: %s %s", request.method, request.url.path
        )
        error = service_unavailable("database")
        return error_response(
            error.status_code, error.code, error.message, error.details
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception):
        # 원인은 로그에만 남기고, 응답에는 내부 정보를 넣지 않는다
        logger.exception(
            "처리하지 못한 오류: %s %s", request.method, request.url.path
        )
        return error_response(
            500, "INTERNAL_ERROR", "일시적인 오류가 발생했어요."
        )


def jsonable_errors(exc: RequestValidationError):
    return [
        {
            "loc": list(err.get("loc", [])),
            "msg": err.get("msg"),
            "type": err.get("type")
        }
        for err in exc.errors()
    ]
