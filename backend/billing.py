"""Account-wide monthly AI credit reporting from workspace usage events."""
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from fastapi import APIRouter, HTTPException, Request

from crm import db_from
from workspace_access import member_context


router = APIRouter(prefix="/workspaces/{ws_id}/billing", tags=["Billing"])
CENT = Decimal("0.01")
MILLION = Decimal("1000000")
BEDROCK_PROVIDERS = {"bedrock", "bedrock_mantle"}


def usd(value):
    return str(value.quantize(CENT, rounding=ROUND_HALF_UP))


def monthly_credit():
    try:
        credit = Decimal(os.environ.get("AI_MONTHLY_CREDIT_USD", "100"))
        return credit if credit >= 0 and credit.is_finite() else Decimal("100")
    except InvalidOperation:
        return Decimal("100")


def rate_card():
    """Prices per million tokens, keyed by provider::model, set by the operator."""
    try:
        configured = json.loads(os.environ.get("AI_BILLING_RATES_JSON", "{}"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(configured, dict):
        return {}
    rates = {}
    for key, value in configured.items():
        if not isinstance(value, dict) or "::" not in key:
            continue
        try:
            input_rate = Decimal(str(value["input_per_million_usd"]))
            output_rate = Decimal(str(value["output_per_million_usd"]))
            cache_read = Decimal(str(value["cache_read_per_million_usd"])) if "cache_read_per_million_usd" in value else None
            cache_write = Decimal(str(value["cache_write_per_million_usd"])) if "cache_write_per_million_usd" in value else None
            if all(rate.is_finite() and rate >= 0 for rate in (input_rate, output_rate, cache_read, cache_write) if rate is not None):
                rates[key] = (input_rate, output_rate, cache_read, cache_write)
        except (KeyError, InvalidOperation, TypeError):
            continue
    return rates


def price_event(event, rates):
    """Return a dollar estimate only when a metered Bedrock call has a valid rate."""
    if not event.get("metered"):
        return None
    provider = event.get("provider") or ""
    if provider not in BEDROCK_PROVIDERS:
        return None
    key = f"{provider}::{event.get('model') or ''}"
    if key not in rates:
        return None
    input_rate, output_rate, *cache_rates = rates[key]
    input_tokens = max(0, int(event.get("input_tokens") or 0))
    output_tokens = max(0, int(event.get("output_tokens") or 0))
    cache_read = max(0, int(event.get("cache_read_input_tokens") or 0))
    cache_write = max(0, int(event.get("cache_write_input_tokens") or 0))
    cache_read_rate = cache_rates[0] if len(cache_rates) > 0 else None
    cache_write_rate = cache_rates[1] if len(cache_rates) > 1 else None
    if (cache_read and cache_read_rate is None) or (cache_write and cache_write_rate is None):
        return None
    # OpenAI-compatible usage includes cached input in prompt_tokens; Converse reports it separately.
    if provider == "bedrock_mantle":
        input_tokens = max(0, input_tokens - cache_read - cache_write)
    return (Decimal(input_tokens) * input_rate + Decimal(output_tokens) * output_rate
            + Decimal(cache_read) * (cache_read_rate or 0)
            + Decimal(cache_write) * (cache_write_rate or 0)) / MILLION


def billing_summary(events, workspace_count, now=None, rates=None, credit=None):
    now = now or datetime.now(timezone.utc)
    rates = rate_card() if rates is None else rates
    credit = monthly_credit() if credit is None else credit
    period_start = now.date().replace(day=1).isoformat()
    if now.month == 12:
        period_end = now.date().replace(year=now.year + 1, month=1, day=1).isoformat()
    else:
        period_end = now.date().replace(month=now.month + 1, day=1).isoformat()
    total = Decimal("0")
    priced_calls = unpriced_calls = unmetered_calls = 0
    input_tokens = output_tokens = 0
    by_model = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": Decimal("0"), "unpriced_calls": 0})
    for event in events:
        provider = event.get("provider") or "unknown"
        model = event.get("model") or "unknown"
        key = (provider, model)
        row = by_model[key]
        row["calls"] += 1
        row["input_tokens"] += max(0, int(event.get("input_tokens") or 0))
        row["output_tokens"] += max(0, int(event.get("output_tokens") or 0))
        input_tokens += max(0, int(event.get("input_tokens") or 0))
        output_tokens += max(0, int(event.get("output_tokens") or 0))
        cost = price_event(event, rates)
        if cost is not None:
            priced_calls += 1
            total += cost
            row["cost"] += cost
        elif event.get("metered"):
            unpriced_calls += 1
            row["unpriced_calls"] += 1
        else:
            unmetered_calls += 1
    complete = unpriced_calls == 0 and unmetered_calls == 0
    return {
        "period_start": period_start, "period_end_exclusive": period_end,
        "currency": "USD", "monthly_credit_usd": usd(credit),
        "estimated_usage_usd": usd(total),
        "estimated_remaining_usd": usd(max(Decimal("0"), credit - total)) if complete else None,
        "estimated_overage_usd": usd(max(Decimal("0"), total - credit)) if complete else None,
        "estimate_complete": complete, "workspace_count": workspace_count,
        "priced_calls": priced_calls, "unpriced_calls": unpriced_calls,
        "unmetered_calls": unmetered_calls, "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "models": [
            {"provider": provider, "model": model, "calls": row["calls"],
             "input_tokens": row["input_tokens"], "output_tokens": row["output_tokens"],
             "estimated_cost_usd": usd(row["cost"]), "unpriced_calls": row["unpriced_calls"]}
            for (provider, model), row in sorted(by_model.items())
        ],
        "enforcement": "report_only",
    }


@router.get("")
async def get_billing_summary(ws_id: str, request: Request):
    db = db_from(request)
    _, workspace, access = await member_context(request, db, ws_id)
    if access["role"] != "owner":
        raise HTTPException(403, "Billing is available to account owners only")
    owner_id = str(workspace["user_id"])
    workspaces = await db.workspaces.find({"user_id": owner_id}, {"_id": 1}).to_list(None)
    workspace_ids = [str(row["_id"]) for row in workspaces]
    now = datetime.now(timezone.utc)
    period_start = now.date().replace(day=1).isoformat()
    events = db.ai_usage_events.find(
        {"workspace_id": {"$in": workspace_ids}, "day": {"$gte": period_start, "$lte": now.date().isoformat()}},
        {"metadata": 0},
    )
    return billing_summary([event async for event in events], len(workspace_ids), now)
