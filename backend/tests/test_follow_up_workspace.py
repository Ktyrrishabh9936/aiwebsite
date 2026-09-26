"""Follow-up overview and manual fallback stay useful when AI is offline."""
from bson import ObjectId

from crm_workspace import _follow_up_snapshot, _manual_suggestion


def test_open_lead_without_next_action_is_flagged_and_uses_latest_response():
    lead = {"status": "contacted", "lead_notes": [{"body": "Asked to see the brochure", "created_at": "2026-09-25T09:00:00+00:00"}]}
    snapshot = _follow_up_snapshot(lead, [])
    assert snapshot["follow_up_pending"] is True
    assert snapshot["last_response"] == "Asked to see the brochure"
    assert "next follow-up" in _manual_suggestion(lead, snapshot)["reason"]


def test_completed_outcome_and_pending_action_are_visible_together():
    tasks = [
        {"_id": ObjectId(), "status": "done", "outcome": "No answer; try after lunch", "updated_at": "2026-09-25T10:00:00+00:00"},
        {"_id": ObjectId(), "status": "pending", "title": "Try calling again", "scheduled_time": "2026-09-26T12:00:00+00:00"},
    ]
    snapshot = _follow_up_snapshot({"status": "new"}, tasks)
    assert snapshot["last_response"] == "No answer; try after lunch"
    assert snapshot["next_action"]["title"] == "Try calling again"
    assert snapshot["follow_up_pending"] is False


def test_closed_lead_is_not_marked_pending():
    snapshot = _follow_up_snapshot({"status": "won"}, [])
    assert snapshot["closed"] is True
    assert snapshot["follow_up_pending"] is False
