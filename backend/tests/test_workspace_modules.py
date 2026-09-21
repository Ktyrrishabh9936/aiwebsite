import asyncio
import pytest
from bson import ObjectId
from fastapi import HTTPException

from catalog import clean_item
from sales_modules import finalize_opportunity, safe_money_minor
from workspace_modules import clean_currency, clean_modules, money_minor, require_module, workspace_currency, workspace_modules


def test_workspace_defaults_and_validation():
    assert workspace_modules({}) == {"real_estate": True, "agency": False}
    assert workspace_currency({}) == "INR"
    assert clean_modules({"agency": True}) == {"real_estate": False, "agency": True}
    assert clean_currency("usd") == "USD"
    assert money_minor("1,234.56") == 123456
    assert safe_money_minor("Price on request") == 0
    with pytest.raises(HTTPException):
        clean_currency("BTC")
    with pytest.raises(HTTPException):
        require_module({"modules": {"real_estate": False, "agency": False}}, "agency")


def test_catalog_normalizes_stock_and_prices():
    product = clean_item({"name": "Campaign kit", "kind": "product", "price": "49.99", "stock_quantity": "2"})
    assert product["price_minor"] == 4999
    assert product["stock_quantity"] == 2
    service = clean_item({"name": "SEO", "kind": "service", "price": 1000, "stock_quantity": 9})
    assert service["stock_quantity"] == 0
    with pytest.raises(HTTPException):
        clean_item({"name": "SEO", "kind": "service", "price": 100, "status": "sold_out"})


class Collection:
    def __init__(self, document):
        self.document = document

    async def find_one_and_update(self, query, update, return_document=None):
        expected_status = query.get("status")
        allowed_statuses = expected_status.get("$in", []) if isinstance(expected_status, dict) else [expected_status]
        enough_stock = self.document.get("stock_quantity", 0) >= query.get("stock_quantity", {}).get("$gte", 0)
        if str(self.document.get("_id")) != str(query.get("_id")) or expected_status and self.document.get("status") not in allowed_statuses or not enough_stock:
            return None
        self.document.update(update.get("$set", {}))
        if "$inc" in update:
            for key, value in update["$inc"].items():
                self.document[key] = self.document.get(key, 0) + value
        return self.document

    async def update_one(self, query, update):
        self.document.update(update.get("$set", {}))

    async def find_one(self, query):
        return self.document if str(self.document.get("_id")) == str(query.get("_id")) and self.document.get("status") == query.get("status") else None


class Db:
    def __init__(self, prop=None, item=None):
        self.properties = Collection(prop or {})
        self.catalog_items = Collection(item or {})


def test_property_conversion_marks_inventory_sold():
    item_id, lead_id = ObjectId(), ObjectId()
    prop = {"_id": item_id, "workspace_id": "workspace", "status": "available"}
    lead = {"_id": lead_id, "opportunity": {"module": "real_estate", "kind": "property", "item_id": str(item_id), "quantity": 1}}
    result = asyncio.run(finalize_opportunity(Db(prop=prop), "workspace", lead, {"modules": {"real_estate": True}}))
    assert prop["status"] == "sold"
    assert prop["sold_to_lead_id"] == str(lead_id)
    assert result["sale_status"] == "sold"


def test_product_conversion_decrements_stock_and_sells_out():
    item_id, lead_id = ObjectId(), ObjectId()
    item = {"_id": item_id, "workspace_id": "workspace", "kind": "product", "status": "active", "stock_quantity": 2}
    lead = {"_id": lead_id, "opportunity": {"module": "agency", "kind": "product", "item_id": str(item_id), "quantity": 2}}
    result = asyncio.run(finalize_opportunity(Db(item=item), "workspace", lead, {"modules": {"agency": True, "real_estate": False}}))
    assert item["stock_quantity"] == 0
    assert item["status"] == "sold_out"
    assert result["sale_status"] == "sold"


def test_service_conversion_keeps_service_reusable():
    item_id = ObjectId()
    item = {"_id": item_id, "workspace_id": "workspace", "kind": "service", "status": "active", "stock_quantity": 0}
    lead = {"_id": ObjectId(), "opportunity": {"module": "agency", "kind": "service", "item_id": str(item_id), "quantity": 1}}
    result = asyncio.run(finalize_opportunity(Db(item=item), "workspace", lead, {"modules": {"agency": True}}))
    assert item["status"] == "active"
    assert result["sale_status"] == "sold"
