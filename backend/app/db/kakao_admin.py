"""카카오 관리자 호출 (서버 전용 Admin 키). 탈퇴 삭제 실행 때 연결 끊기

- 카카오 로그인 서비스 탈퇴 → 앱 연결 끊기 (카카오 정책). 끊어야 다음 로그인 때 동의 화면 다시
- Supabase 계정 삭제만으로는 카카오 쪽 연결 남음
- 이미 끊김 (-101) · 없는 사용자 (-103) → 오류 아님 (재실행 안전)
- KAKAO_ADMIN_KEY 없음 → 건너뜀 + 경고 (개발 DB)
"""
import logging

import httpx

from app.core.config import settings


logger = logging.getLogger("silvercare.kakao")

UNLINK_URL = "https://kapi.kakao.com/v1/user/unlink"
# 연결 안 된 사용자 · 없는 사용자
ALREADY_GONE = {-101, -103}
TIMEOUT = 10


class KakaoUnlinkError(Exception):
    pass


def unlink(kakao_user_id: str):
    if not settings.KAKAO_ADMIN_KEY:
        logger.warning("KAKAO_ADMIN_KEY 없음 → 카카오 연결 끊기 건너뜀")
        return

    response = httpx.post(
        UNLINK_URL,
        headers={"Authorization": f"KakaoAK {settings.KAKAO_ADMIN_KEY}"},
        data={"target_id_type": "user_id", "target_id": kakao_user_id},
        timeout=TIMEOUT,
    )
    if response.status_code == 200:
        return
    try:
        code = response.json().get("code")
    except ValueError:
        code = None
    if code in ALREADY_GONE:
        return
    # 키 오류·카카오 장애 → 삭제 실행 중단, 다음 실행에서 재시도
    raise KakaoUnlinkError(f"카카오 연결 끊기 실패 {response.status_code} code={code}")
