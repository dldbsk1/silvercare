"""FCM HTTP v1 발송 (푸시)

- 인증: Cloud Run 서비스 계정 토큰 (메타데이터 서버, wake.access_token 재사용). 키 파일 X
  서비스 계정 권한: Firebase Cloud Messaging API Admin (roles/firebasecloudmessaging.admin)
- 기기 1대 = 요청 1번 (v1 API에 여러 토큰 묶음 발송 없음)
- 결과
    SENT     발송 완료
    INVALID  토큰 무효 (앱 삭제·토큰 만료) → 기기 끄기
    RETRY    일시 오류 (429·5xx·연결) → 작업 재시도
    REJECTED 요청 자체 거부 (400 등) → 재시도 X, 로그
"""
import logging
from enum import Enum

import httpx

from app.core.config import settings
from app.workers import wake


logger = logging.getLogger("silvercare.fcm")

FCM_API = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"
TIMEOUT_SECONDS = 10


class Result(str, Enum):
    SENT = "sent"
    INVALID = "invalid"
    RETRY = "retry"
    REJECTED = "rejected"


def build_message(token: str, title: str, body: str | None, data: dict[str, str]) -> dict:
    notification = {"title": title}
    if body:
        notification["body"] = body
    return {
        "message": {
            "token": token,
            "notification": notification,
            # 앱: 알림 누르면 data의 type·id로 화면 이동
            "data": data,
            # 안드로이드 채널: FCM 기본 채널 (앱에서 따로 만들지 않음)
            "android": {"priority": "high"},
            "apns": {"payload": {"aps": {"sound": "default"}}},
        }
    }


def error_code(response: httpx.Response) -> str | None:
    """FCM 오류 상세 코드 (UNREGISTERED 등)"""
    try:
        details = response.json().get("error", {}).get("details", [])
    except ValueError:
        return None
    for detail in details:
        if isinstance(detail, dict) and detail.get("errorCode"):
            return detail["errorCode"]
    return None


def classify(response: httpx.Response) -> Result:
    if response.status_code == 200:
        return Result.SENT
    code = error_code(response)
    if response.status_code == 404 or code in ("UNREGISTERED", "SENDER_ID_MISMATCH"):
        return Result.INVALID
    if response.status_code in (401, 429) or response.status_code >= 500 or code in ("UNAVAILABLE", "INTERNAL", "QUOTA_EXCEEDED"):
        return Result.RETRY
    return Result.REJECTED


def send(token: str, title: str, body: str | None, data: dict[str, str]) -> Result:
    try:
        response = httpx.post(
            FCM_API.format(project=settings.fcm_project),
            headers={"Authorization": f"Bearer {wake.access_token()}"},
            json=build_message(token, title, body, data),
            timeout=TIMEOUT_SECONDS,
        )
    except httpx.HTTPError:
        logger.warning("FCM 연결 실패", exc_info=True)
        return Result.RETRY

    result = classify(response)
    if result in (Result.RETRY, Result.REJECTED):
        logger.warning("FCM %s %s %s", result.value, response.status_code, response.text[:500])
    return result
