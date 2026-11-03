"""D-day 계산 (DB 없이)"""
from datetime import date, datetime, timezone

import pytest

from app.services import dday


TODAY = date(2026, 11, 3)


@pytest.mark.parametrize("survey_date, days_left, status", [
    (None, None, "not_set"),
    (date(2026, 11, 20), 17, "upcoming"),
    (date(2026, 11, 4), 1, "upcoming"),
    (date(2026, 11, 3), 0, "today"),
    (date(2026, 11, 2), -1, "past"),
])
def test_compute(survey_date, days_left, status):
    result = dday.compute(survey_date, TODAY)

    assert result == {"survey_date": survey_date, "days_left": days_left, "status": status}


def test_postponed_and_cancelled():
    assert dday.compute(date(2026, 11, 20), TODAY)["days_left"] == 17
    assert dday.compute(date(2026, 11, 27), TODAY)["days_left"] == 24
    assert dday.compute(None, TODAY)["status"] == "not_set"


@pytest.mark.parametrize("utc, kst_date", [
    (datetime(2026, 11, 3, 14, 59, tzinfo=timezone.utc), date(2026, 11, 3)),
    (datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc), date(2026, 11, 4)),
])
def test_today_is_korea_time(utc, kst_date):
    assert dday.today_kst(utc) == kst_date
