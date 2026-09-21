import asyncio
from copy import deepcopy
from datetime import date
from types import SimpleNamespace

import httpx
import pytest
from bson import ObjectId
from fastapi import FastAPI, HTTPException

from auth import create_access_token
from crm_performance import (PerformanceTotals, canonical_calls, date_bounds, performance_pipeline,
                             qualification_source, review_state, router, source_version)

WS = str(ObjectId())
OTHER_WS = str(ObjectId())
USER = ObjectId()
DAY = "2026-09-20T10:00:00+00:00"
LOWER, UPPER = date_bounds(date(2026, 9, 1), date(2026, 9, 30))


def lead(status="QUALIFIED", review=None):
    doc = {"_id": ObjectId(), "workspace_id": WS, "created_at": DAY, "status": "new",
           "field_values": {"phone": "+14155550123"}, "lead_status": status,
           "qualification_call": {"call_uuid": "call", "qualification_profile_id": "profile",
               "engine_result": {"lead_status": status, "call_outcome": "CONNECTED",
                                 "next_action": "SALES_CALL", "qualification_data": {"location": "Gurgaon"}}}}
    if review:
        doc["qualification_review"] = {"status": review, "source_version": source_version(qualification_source(doc))}
    return doc


def log(outcome="CONNECTED", status="completed", duration=60, ident="call", when=DAY):
    return {"_id": ObjectId(), "provider": "plivo", "provider_call_id": ident, "created_at": when,
            "profile_id": "profile", "result": {"call_outcome": outcome},
            "call_result": {"call_status": status, "terminal": True, "duration_seconds": duration}}


def report(*leads):
    totals = PerformanceTotals()
    for doc in leads:
        totals.add(doc, LOWER, UPPER)
    return totals.output()


def test_no_reviews_is_unknown_not_zero_and_unreviewed_is_excluded():
    assert report()["reviews"]["accuracy"] is None
    assert report(lead())["reviews"] == {"reviewed": 0, "correct": 0, "incorrect": 0, "not_reviewed": 1, "accuracy": None}
    data = report(lead(review="correct"), lead(review="incorrect"), lead(), lead())
    assert data["reviews"] == {"reviewed": 2, "correct": 1, "incorrect": 1, "not_reviewed": 2, "accuracy": 50.0}


def test_accuracy_85_percent_and_changed_result_requires_review():
    data = report(*[lead(review="correct") for _ in range(85)], *[lead(review="incorrect") for _ in range(15)], lead())
    assert data["reviews"]["accuracy"] == 85
    doc = lead(review="correct")
    doc["qualification_call"]["engine_result"]["qualification_data"]["location"] = "Delhi"
    assert review_state(doc)["stale"]
    assert report(doc)["reviews"]["accuracy"] is None


def test_session_log_deduplication_attempt_rules_and_outcomes():
    doc = lead()
    doc["plivo_call_sessions"] = [
        {"_id": ObjectId(), "created_at": DAY, "profile_id": "profile", "provider_identifiers": {"call_uuid": "call", "request_uuid": "request"}, "call_status": "completed", "duration": 90},
        {"_id": ObjectId(), "created_at": DAY, "status": "failed", "provider_identifiers": {}},  # rejected before provider
    ]
    doc["crm_call_logs"] = [log(), log("NO_ANSWER", "completed", ident="no"), log("BUSY", "busy", ident="busy"), log("TECHNICAL_ISSUE", "failed", ident="failed"), log("DROPPED_CALL", "completed", ident="dropped"), log(ident="old", when="2026-08-31T23:59:59+00:00")]
    data = report(doc)
    assert data["calling"] == {"calls_attempted": 5, "connected": 2, "no_answer": 1, "busy": 1, "failed": 1,
                               "completed_conversations": 1, "average_duration_seconds": 60, "connection_rate": 40}
    assert data["funnel"]["leads_attempted"] == 1


def test_provider_ids_are_namespaced_and_legacy_is_not_double_counted():
    doc = lead()
    a, b = log(), log()
    b["provider"] = "sarvam"
    doc["crm_call_logs"] = [a, b]
    assert len(canonical_calls(doc)) == 2
    doc["crm_call_logs"] = []
    doc["qualification_call"].update({"call_timestamp": DAY, "duration": "25", "status": "completed"})
    assert report(doc)["calling"]["calls_attempted"] == 1


def test_eligibility_qualification_completion_and_followup():
    qualified, disqualified, partial, pending = lead(), lead("UNQUALIFIED"), lead("PARTIALLY_QUALIFIED"), lead("PENDING")
    pending["do_not_call"] = True
    disqualified["field_values"] = {}
    partial["qualification_call"]["engine_result"]["next_action"] = "FOLLOW_UP"
    data = report(qualified, disqualified, partial, pending)
    assert data["funnel"]["eligible_leads"] == 2
    assert data["qualification"]["qualified"] == 1
    assert data["qualification"]["disqualified"] == 1
    assert data["qualification"]["follow_up_required"] == 1
    assert data["qualification"]["completion_rate"] == 50


def test_profile_filter_does_not_assign_current_profile_to_old_calls():
    doc = lead()
    doc["crm_call_logs"] = [log()]
    doc["qualification_call"]["qualification_profile_id"] = "new-profile"
    totals = PerformanceTotals()
    totals.add(doc, LOWER, UPPER, "profile")
    data = totals.output()
    assert data["calling"]["calls_attempted"] == 1
    assert data["qualification"]["ai_results"] == 0


def test_dates_are_inclusive_utc_and_every_lookup_is_workspace_scoped():
    start, end = date_bounds(date(2026, 9, 20), date(2026, 9, 20))
    assert end.day == 21 and start.hour == 0
    with pytest.raises(HTTPException):
        date_bounds(date(2026, 9, 21), date(2026, 9, 20))
    pipeline = performance_pipeline(WS, start, end, "won")
    assert pipeline[0]["$match"]["workspace_id"] == WS
    assert pipeline[0]["$match"]["status"] == "won"
    assert pipeline[0]["$match"]["created_at"]["$lt"] == end.isoformat()
    for stage in pipeline:
        if "$lookup" in stage:
            assert stage["$lookup"]["pipeline"][0]["$match"]["workspace_id"] == WS


class Collection:
    def __init__(self, docs=()):
        self.docs = deepcopy(list(docs))

    async def find_one(self, query):
        return next((deepcopy(d) for d in self.docs if all(d.get(k) == v for k, v in query.items())), None)

    async def update_one(self, query, updates):
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                doc.update(deepcopy(updates.get("$set", {})))
                for key, value in updates.get("$push", {}).items():
                    doc.setdefault(key, []).append(deepcopy(value))
                return SimpleNamespace(matched_count=1)
        return SimpleNamespace(matched_count=0)


def fixture_db(doc):
    return SimpleNamespace(crm_leads=Collection([doc]), users=Collection([{"_id": USER, "name": "John", "email": "review@example.test"}]),
        workspaces=Collection([{"_id": ObjectId(WS), "user_id": str(USER)}, {"_id": ObjectId(OTHER_WS), "user_id": str(ObjectId())}]))


def test_review_api_auth_persistence_audit_and_stale_results(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "crm-review-test-signing-key-only-32chars")
    async def run():
        original = lead()
        db = fixture_db(original)
        app = FastAPI(); app.state.db = db; app.include_router(router)
        path = f"/workspaces/{WS}/crm/leads/{original['_id']}/qualification-review"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get(path)).status_code == 401
            assert (await client.put(path, json={"status": "correct", "source_version": "a" * 64})).status_code == 401
            client.headers["Authorization"] = "Bearer " + create_access_token(str(USER), "review@example.test")
            assert (await client.get(path.replace(WS, OTHER_WS))).status_code == 403
            assert (await client.get(path.replace(str(original['_id']), str(ObjectId())))).status_code == 404
            state = (await client.get(path)).json()
            assert state["review"]["status"] == "not_reviewed"
            body = {"status": "correct", "source_version": state["source_version"], "note": "Confirmed on a sales call"}
            saved = await client.put(path, json=body)
            assert saved.status_code == 200, saved.text
            assert saved.json()["review"]["reviewed_by"] == str(USER)
            assert saved.json()["review"]["reviewed_by_name"] == "John"
            assert saved.json()["review"]["reviewed_at"]
            body.update(status="incorrect", note="Location is Delhi", incorrect_fields=["location"])
            assert (await client.put(path, json=body)).status_code == 200
            stored = db.crm_leads.docs[0]
            assert stored["qualification_call"] == original["qualification_call"]
            assert stored["qualification_review"]["note"] == "Location is Delhi"
            assert [e["new_status"] for e in stored["timeline"]] == ["correct", "incorrect"]
            assert stored["timeline"][1]["previous_status"] == "correct"
            assert report(stored)["reviews"]["accuracy"] == 0
            assert (await client.put(path, json={**body, "incorrect_fields": ["invented"]})).status_code == 422
            assert (await client.put(path, json={**body, "reviewed_by": "impersonation"})).status_code == 422
            body.update(status="not_reviewed", incorrect_fields=[])
            assert (await client.put(path, json=body)).status_code == 200
            assert report(stored)["reviews"]["accuracy"] is None
            stored["qualification_call"]["engine_result"]["qualification_data"]["location"] = "Delhi"
            assert (await client.put(path, json=body)).status_code == 409
            assert (await client.get(path)).json()["review"]["status"] == "not_reviewed"
            stored["qualification_call"] = {}
            assert (await client.put(path, json=body)).status_code == 409
    asyncio.run(run())


def test_foreign_lead_and_concurrent_review_cannot_be_overwritten(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "crm-review-test-signing-key-only-32chars")
    async def run():
        doc = lead(); db = fixture_db(doc)
        app = FastAPI(); app.state.db = db; app.include_router(router)
        path = f"/workspaces/{WS}/crm/leads/{doc['_id']}/qualification-review"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"Authorization": "Bearer " + create_access_token(str(USER), "review@example.test")}) as client:
            db.crm_leads.docs[0]["workspace_id"] = OTHER_WS
            body = {"status": "correct", "source_version": source_version(qualification_source(doc))}
            assert (await client.put(path, json=body)).status_code == 404
            db.crm_leads.docs[0]["workspace_id"] = WS
            original_update = db.crm_leads.update_one
            async def race(query, updates):
                db.crm_leads.docs[0]["qualification_review"] = {"status": "incorrect"}
                return await original_update(query, updates)
            db.crm_leads.update_one = race
            assert (await client.put(path, json=body)).status_code == 409
    asyncio.run(run())
