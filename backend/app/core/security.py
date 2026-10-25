from dataclasses import dataclass

import httpx
from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client
from supabase_auth.errors import AuthRetryableError

from app.core.config import settings
from app.core.errors import AppError, service_unavailable


supabase = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_PUBLISHABLE_KEY
)

# auto_error=False: 토큰이 없을 때도 공통 오류 형식(401)으로 응답하기 위해
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthUser:
    """Supabase Auth 토큰에서 확인한 사용자"""

    id: str
    provider: str | None
    phone: str | None


def get_auth_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer_scheme
    )
) -> AuthUser:

    if credentials is None:
        raise AppError(401, "UNAUTHORIZED", "로그인이 필요합니다.")

    token = credentials.credentials

    try:
        # 초기에는 Supabase Auth 서버에서 토큰을 확인한다 (API 명세서 14.1)
        response = supabase.auth.get_user(token)
        user = response.user

        if user is None:
            raise ValueError("User not found")

    # Auth 서버 장애를 401로 주면 앱이 로그아웃시켜 버리므로 503으로 구분한다
    except (AuthRetryableError, httpx.TransportError):
        raise service_unavailable("auth")

    except Exception:
        raise AppError(
            401, "UNAUTHORIZED", "유효하지 않거나 만료된 토큰입니다."
        )

    return AuthUser(
        id=str(user.id),
        provider=(user.app_metadata or {}).get("provider"),
        phone=user.phone or None
    )
