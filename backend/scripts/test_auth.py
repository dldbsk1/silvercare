import getpass
import httpx

from supabase import create_client
from app.core.config import settings


client = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_PUBLISHABLE_KEY
)

email = input("테스트 계정 이메일: ")
password = getpass.getpass("비밀번호: ")

try:
    result = client.auth.sign_in_with_password({
        "email": email,
        "password": password
    })

    token = result.session.access_token

    response = httpx.get(
        "http://127.0.0.1:8001/v1/auth/me",
        headers={
            "Authorization": f"Bearer {token}"
        },
        timeout=15
    )

    print("HTTP 상태:", response.status_code)
    print("응답:", response.json())

except Exception as e:
    print("테스트 실패:", type(e).__name__, str(e))
