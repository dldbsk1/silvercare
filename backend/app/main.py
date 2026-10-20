from fastapi import FastAPI, Depends

from app.database import check_database
from app.auth import get_current_user_id


app = FastAPI(title="SilverCare API")


@app.get("/health")
def health():
    return {"status": "ok"}


# 개발 전용
@app.get("/dev/db-check")
def db_check():
    count = check_database()
    return {
        "database_connected": True,
        "survey_item_count": count
    }


@app.get("/auth/me")
def get_my_info(
    user_id: str = Depends(get_current_user_id)
):
    return {
        "authenticated": True,
        "user_id": user_id
    }
