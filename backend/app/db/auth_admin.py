"""Supabase Auth 관리자 호출 (서버 전용 secret key). 탈퇴 삭제 실행용"""
from supabase_auth.errors import AuthApiError

from app.db.storage import get_admin_client


def delete_user(user_id: str):
    """로그인 계정 삭제. 없는 계정 → 오류 아님 (재실행 안전)

    soft delete: auth.users 행 유지 (public.users 연쇄 삭제 X), 로그인·식별 정보 제거
    → 같은 카카오·전화번호로 새 계정 가입 가능
    """
    try:
        get_admin_client().auth.admin.delete_user(user_id, should_soft_delete=True)
    except AuthApiError as e:
        if e.status != 404:
            raise
