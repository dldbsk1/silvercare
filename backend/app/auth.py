from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client

from app.config import settings


supabase = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_PUBLISHABLE_KEY
)

bearer_scheme = HTTPBearer()


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(
        bearer_scheme
    )
) -> str:

    token = credentials.credentials

    try:
        response = supabase.auth.get_user(token)
        user = response.user

        if user is None:
            raise ValueError("User not found")

        return str(user.id)

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않거나 만료된 토큰입니다.",
            headers={"WWW-Authenticate": "Bearer"}
        )
