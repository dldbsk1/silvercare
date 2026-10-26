"""실제 로그인 토큰으로 가입 흐름(동의 → 부모님 등록)과 음성 업로드를 확인한다.

서버가 켜져 있어야 한다 (uvicorn app.main:app --reload --port 8001).
만든 부모님과 업로드 파일은 끝나면 지운다. 동의 기록과 users 프로필은 남긴다.

    cd backend
    python -m scripts.smoke_test
"""
import getpass

import httpx
from sqlalchemy import text
from supabase import create_client

from app.core.config import settings
from app.db import storage
from app.db.session import new_session


BASE_URL = "http://127.0.0.1:8001"
OTHER_PARENT_ID = "00000000-0000-0000-0000-000000000000"

results = []


def check(name: str, ok: bool, detail=""):
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


def main():
    # 앱과 같은 publishable key로 로그인
    app_client = create_client(
        settings.SUPABASE_URL, settings.SUPABASE_PUBLISHABLE_KEY
    )
    email = input("테스트 계정 이메일: ")
    password = getpass.getpass("비밀번호: ")
    session = app_client.auth.sign_in_with_password(
        {"email": email, "password": password}
    ).session
    headers = {"Authorization": f"Bearer {session.access_token}"}
    user_id = str(session.user.id)

    http = httpx.Client(base_url=BASE_URL, timeout=30)

    # 1. 서버·인증
    check("서버 켜짐 (/health)", http.get("/health").status_code == 200)

    response = http.get("/v1/auth/me")
    check("토큰 없으면 401", response.status_code == 401)

    response = http.get("/v1/auth/me", headers=headers)
    check("로그인 사용자 확인 (/v1/auth/me)", response.status_code == 200,
          response.text if response.status_code != 200 else "")

    db = new_session()
    with db.begin():
        has_profile = db.execute(
            text("SELECT count(*) FROM users WHERE id = :id"),
            {"id": user_id}
        ).scalar() == 1
    check("users 프로필 자동 생성", has_profile)

    # 2. 동의 → 부모님 등록 (온보딩)
    response = http.get("/v1/consents/required", headers=headers)
    documents = response.json()["data"]
    check("동의 문구 조회", response.status_code == 200 and len(documents) == 4)

    response = http.post("/v1/consents", headers=headers, json={"items": [
        {"type": doc["type"], "doc_version": doc["doc_version"], "agreed": True}
        for doc in documents
    ]})
    check("전체 동의", response.status_code == 200
          and response.json()["data"]["completed"] is True, response.text)

    response = http.post("/v1/parents", headers=headers, json={
        "nickname": "[smoke] 엄마", "age_band": "80s",
        "apply_stage": "waiting", "cohabiting": False
    })
    check("부모님 등록 → 관리자", response.status_code == 201
          and response.json()["data"]["my_role"] == "admin", response.text)
    if response.status_code != 201:
        print(f"\n{sum(results)}/{len(results)} 통과 (부모님 등록 실패로 중단)")
        return
    parent_id = response.json()["data"]["id"]

    me = http.get("/v1/auth/me", headers=headers).json()["data"]
    check("온보딩 완료 상태", me["onboarding"]["consents_completed"]
          and me["onboarding"]["parent_registered"])

    uploaded_path = None

    try:
        # 3. 음성 업로드 URL → Storage 직접 업로드
        url = f"/v1/parents/{parent_id}/records/audio/upload-url"
        response = http.post(url, headers=headers, json={"content_type": "audio/mp4"})
        check("업로드 URL 발급 (admin)", response.status_code == 201,
              response.text if response.status_code != 201 else "")

        if response.status_code == 201:
            data = response.json()["data"]
            app_client.storage.from_(data["bucket"]).upload_to_signed_url(
                data["audio_path"], data["token"], b"smoke-test-audio",
                {"content-type": "audio/mp4"}
            )
            uploaded_path = data["audio_path"]
            check("서명 URL로 Storage 업로드",
                  storage.object_exists(data["bucket"], uploaded_path))

        response = http.post(
            f"/v1/parents/{OTHER_PARENT_ID}/records/audio/upload-url",
            headers=headers, json={}
        )
        check("다른 부모님은 404", response.status_code == 404)

        # 역할 변경 API(A-FAM-002, P1)가 아직 없어서 DB에서 직접 바꾼다
        with db.begin():
            db.execute(
                text("UPDATE family_members SET role = 'viewer' WHERE parent_id = :p"),
                {"p": parent_id}
            )
        response = http.post(url, headers=headers, json={})
        check("viewer는 업로드 불가 403", response.status_code == 403)

    finally:
        # 4. 정리 (users 프로필은 실제 로그인 결과라 남긴다)
        if uploaded_path:
            storage.remove_objects(settings.STORAGE_AUDIO_BUCKET, [uploaded_path])
        with db.begin():
            db.execute(text("DELETE FROM parents WHERE id = :p"), {"p": parent_id})
        db.close()
        print("테스트 데이터 정리 완료")

    print(f"\n{sum(results)}/{len(results)} 통과")


if __name__ == "__main__":
    main()
