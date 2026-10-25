from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DbSession


router = APIRouter()


@router.get("/db-check")
def db_check(db: DbSession):
    count = db.execute(
        text("SELECT count(*) FROM survey_items")
    ).scalar_one()

    return {
        "data": {
            "database_connected": True,
            "survey_item_count": count
        }
    }
