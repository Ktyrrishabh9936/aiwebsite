"""Workspace module and currency configuration shared by vertical add-ons."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from fastapi import HTTPException

MODULES = {"real_estate", "agency"}
CURRENCIES = {"INR", "USD", "EUR", "GBP", "AED", "CAD", "AUD", "SGD", "JPY"}
DEFAULT_MODULES = {"real_estate": True, "agency": False}


def workspace_modules(workspace):
    stored = workspace.get("modules") or {}
    return {key: bool(stored.get(key, enabled)) for key, enabled in DEFAULT_MODULES.items()}


def workspace_currency(workspace):
    value = str(workspace.get("currency") or "INR").upper()
    return value if value in CURRENCIES else "INR"


def clean_modules(value):
    if not isinstance(value, dict):
        raise HTTPException(400, "modules must be an object")
    unknown = set(value) - MODULES
    if unknown:
        raise HTTPException(400, "Unknown workspace module")
    return {key: bool(value.get(key, False)) for key in MODULES}


def clean_currency(value):
    currency = str(value or "").strip().upper()
    if currency not in CURRENCIES:
        raise HTTPException(400, "Unsupported workspace currency")
    return currency


def require_module(workspace, key):
    if not workspace_modules(workspace).get(key):
        raise HTTPException(403, f"The {key.replace('_', ' ')} module is not active for this workspace")


def money_minor(value):
    try:
        amount = Decimal(str(value or "0").replace(",", "").strip())
    except (InvalidOperation, ValueError):
        raise HTTPException(400, "Price must be a valid number") from None
    if amount < 0:
        raise HTTPException(400, "Price cannot be negative")
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def minor_to_price(value):
    return format(Decimal(int(value or 0)) / Decimal(100), ".2f")
