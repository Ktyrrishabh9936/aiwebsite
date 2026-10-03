from datetime import date, datetime, timezone
import pytest
from fastapi import HTTPException
from crm_performance import date_bounds, PerformanceTotals
from crm import build_crm_analytics

def test_selected_day_uses_application_timezone_and_daylight_saving():
    start, end = date_bounds(date(2026, 10, 3), date(2026, 10, 3), "Asia/Kolkata")
    assert start.isoformat() == "2026-10-02T18:30:00+00:00"
    assert end.isoformat() == "2026-10-03T18:30:00+00:00"
    start, end = date_bounds(date(2026, 3, 8), date(2026, 3, 8), "America/New_York")
    assert (end - start).total_seconds() == 23 * 3600
    with pytest.raises(HTTPException):
        date_bounds(date(2026, 10, 3), date(2026, 10, 3), "invalid")

def test_reports_bucket_leads_on_the_selected_local_day():
    start, end = date_bounds(date(2026, 10, 4), date(2026, 10, 4), "Asia/Kolkata")
    lead = {"created_at": "2026-10-03T20:00:00+00:00", "status": "new"}
    totals = PerformanceTotals()
    totals.add(lead, start, end, zone_name="Asia/Kolkata")
    assert totals.output()["sales"]["trend"][0]["date"] == "2026-10-04"
    data = build_crm_analytics([lead], now=datetime(2026, 10, 3, 20, tzinfo=timezone.utc), zone_name="Asia/Kolkata")
    assert data["today"] == "2026-10-04"
