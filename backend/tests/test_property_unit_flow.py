import asyncio

import httpx
from bson import ObjectId
from fastapi import FastAPI

from auth import create_access_token
from crm import build_manual_lead, ensure_crm_settings, router as crm_router
from properties import router as properties_router
from sales_modules import router as sales_router
from tests.test_qualification_integration import isolated


def test_land_blocks_have_individual_statuses_in_plan(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "property-flow-test-long-signing-secret")

    async def run(db):
        user_id, ws_id = ObjectId(), ObjectId()
        await db.users.insert_one({"_id": user_id, "email": "builder@example.test"})
        await db.workspaces.insert_one({"_id": ws_id, "user_id": str(user_id), "modules": {"real_estate": True}})
        app = FastAPI()
        app.state.db = db
        app.include_router(properties_router)
        app.include_router(sales_router)
        app.include_router(crm_router)
        base = f"/workspaces/{ws_id}/properties"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            client.headers["Authorization"] = "Bearer " + create_access_token(str(user_id), "builder@example.test")
            response = await client.post(base, json={"name": "Five Block Site", "category": "land", "container_kind": "land",
                "attributes": {"area_sqft": "5000"}, "price": "1000000", "inventory_setup": {"mode": "manual", "total_units": 5}})
            assert response.status_code == 200, response.text
            property_id = response.json()["id"]
            plan = (await client.get(base + f"/{property_id}/units/plan")).json()["items"]
            assert len(plan) == 5
            assert {unit["unit_number"] for unit in plan} == {f"Block {number:02d}" for number in range(1, 6)}
            assert all(unit["status"] == "available" for unit in plan)
            offerings = (await client.get(f"/workspaces/{ws_id}/crm/offerings")).json()["items"]
            assert len(offerings) == 5
            assert all(item["kind"] == "unit" and "Block" in item["name"] for item in offerings)
            response = await client.patch(base + f"/{property_id}/units/{plan[0]['id']}", json={"status": "reserved", "expected_updated_at": plan[0]["updated_at"]})
            assert response.status_code == 200, response.text
            updated = (await client.get(base + f"/{property_id}/units/plan")).json()["items"]
            assert [unit["status"] for unit in updated].count("reserved") == 1
            assert [unit["status"] for unit in updated].count("available") == 4
            settings = await ensure_crm_settings(db, str(ws_id))
            lead = build_manual_lead(str(ws_id), {"field_values": {"phone": "+14155550123", "full_name": "Block buyer"}}, settings)
            await db.crm_leads.insert_one(lead)
            lead_id = str(lead["_id"])
            response = await client.patch(f"/workspaces/{ws_id}/crm/leads/{lead_id}/opportunity", json={
                "module": "real_estate", "item_id": plan[1]["id"], "quantity": 1, "amount": "1000000"})
            assert response.status_code == 200, response.text
            response = await client.post(f"/workspaces/{ws_id}/crm/leads/{lead_id}/convert", json={"conversion_type": "single_payment"})
            assert response.status_code == 200, response.text
            statuses = [unit["status"] for unit in (await client.get(base + f"/{property_id}/units/plan")).json()["items"]]
            assert statuses.count("reserved") == 1
            assert statuses.count("sold") == 1
            assert statuses.count("available") == 3

    asyncio.run(isolated(run))


def test_saved_flat_count_can_generate_missing_inventory(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "property-flow-test-long-signing-secret")

    async def run(db):
        user_id, ws_id, property_id = ObjectId(), ObjectId(), ObjectId()
        await db.users.insert_one({"_id": user_id, "email": "builder@example.test"})
        await db.workspaces.insert_one({"_id": ws_id, "user_id": str(user_id), "modules": {"real_estate": True}})
        await db.properties.insert_one({
            "_id": property_id, "workspace_id": str(ws_id), "name": "7th Avenue", "created_at": "2026-09-24",
            "inventory_setup": {"total_units": 10, "unit_mix": [
                {"tower": "Tower A", "bhk": "2 BHK", "count": 10, "start_number": "3091", "price_min": "2000000"}
            ]},
        })
        app = FastAPI()
        app.state.db = db
        app.include_router(properties_router)
        base = f"/workspaces/{ws_id}/properties"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            client.headers["Authorization"] = "Bearer " + create_access_token(str(user_id), "builder@example.test")
            response = await client.get(base)
            assert response.status_code == 200
            assert response.json()["items"][0]["generated_units"] == 0
            response = await client.post(base + f"/{property_id}/generate-units")
            assert response.status_code == 200, response.text
            assert response.json()["generated_units"] == 10
            assert (await client.post(base + f"/{property_id}/generate-units")).json()["generated_units"] == 10
            rows = (await client.get(base + f"/{property_id}/units")).json()["items"]
            assert [row["unit_number"] for row in rows] == [str(number) for number in range(3091, 3101)]
            assert (await client.get(base)).json()["items"][0]["generated_units"] == 10

    asyncio.run(isolated(run))


def test_unlinked_generated_inventory_can_be_deleted_but_linked_inventory_cannot(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "property-flow-test-long-signing-secret")

    async def run(db):
        user_id, ws_id = ObjectId(), ObjectId()
        await db.users.insert_one({"_id": user_id, "email": "builder@example.test"})
        await db.workspaces.insert_one({"_id": ws_id, "user_id": str(user_id), "modules": {"real_estate": True}})
        app = FastAPI()
        app.state.db = db
        app.include_router(properties_router)
        base = f"/workspaces/{ws_id}/properties"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            client.headers["Authorization"] = "Bearer " + create_access_token(str(user_id), "builder@example.test")
            body = {"name": "Lake View", "category": "residential", "subtype": "Apartment", "container_kind": "project",
                    "inventory_setup": {"unit_mix": [{"tower": "A", "bhk": "2 BHK", "count": 2, "start_number": "101"}]}}
            response = await client.post(base, json=body)
            assert response.status_code == 200, response.text
            project_id = response.json()["id"]
            units = (await client.get(base + f"/{project_id}/units")).json()["items"]
            assert len(units) == 2
            await db.crm_leads.insert_one({"_id": ObjectId(), "workspace_id": str(ws_id),
                                            "opportunity": {"project_id": project_id, "item_id": units[0]["id"]}})
            response = await client.delete(base + f"/{project_id}")
            assert response.status_code == 409
            assert await db.property_units.count_documents({"property_id": project_id}) == 2
            await db.crm_leads.delete_many({"workspace_id": str(ws_id)})
            response = await client.delete(base + f"/{project_id}")
            assert response.status_code == 200, response.text
            assert await db.property_units.count_documents({"property_id": project_id}) == 0
            assert await db.properties.count_documents({"_id": ObjectId(project_id)}) == 0

    asyncio.run(isolated(run))


def test_removing_a_flat_group_deletes_only_its_unlinked_flats(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "property-flow-test-long-signing-secret")

    async def run(db):
        user_id, ws_id = ObjectId(), ObjectId()
        await db.users.insert_one({"_id": user_id, "email": "builder@example.test"})
        await db.workspaces.insert_one({"_id": ws_id, "user_id": str(user_id), "modules": {"real_estate": True}})
        app = FastAPI()
        app.state.db = db
        app.include_router(properties_router)
        base = f"/workspaces/{ws_id}/properties"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            client.headers["Authorization"] = "Bearer " + create_access_token(str(user_id), "builder@example.test")
            groups = [{"tower": "A", "bhk": "2 BHK", "count": 2, "start_number": "101"},
                      {"tower": "B", "bhk": "1 BHK", "count": 1, "start_number": "201"}]
            response = await client.post(base, json={"name": "Lake View", "inventory_setup": {"unit_mix": groups}})
            assert response.status_code == 200, response.text
            project_id = response.json()["id"]
            response = await client.patch(base + f"/{project_id}", json={"inventory_setup": {"unit_mix": groups[:1]}})
            assert response.status_code == 200, response.text
            rows = (await client.get(base + f"/{project_id}/units")).json()["items"]
            assert [(row["tower"], row["unit_number"]) for row in rows] == [("A", "101"), ("A", "102")]

    asyncio.run(isolated(run))


def test_flat_inventory_links_sells_and_relists_without_selling_project(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "property-flow-test-long-signing-secret")

    async def run(db):
        user_id, ws_id = ObjectId(), ObjectId()
        await db.users.insert_one({"_id": user_id, "email": "builder@example.test"})
        await db.workspaces.insert_one({"_id": ws_id, "user_id": str(user_id), "modules": {"real_estate": True, "agency": False}})
        await db.property_units.create_index([("workspace_id", 1), ("property_id", 1), ("tower", 1), ("unit_number", 1)], unique=True)
        app = FastAPI()
        app.state.db = db
        app.include_router(properties_router)
        app.include_router(sales_router)
        app.include_router(crm_router)
        base = f"/workspaces/{ws_id}"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            client.headers["Authorization"] = "Bearer " + create_access_token(str(user_id), "builder@example.test")
            response = await client.post(base + "/properties", json={
                "name": "Lake View", "location": "Pune", "category": "residential", "subtype": "Apartment",
                "container_kind": "project", "inventory_setup": {"unit_mix": [
                    {"tower": "A", "bhk": "2 BHK", "count": 2, "start_number": "4", "price_min": "2000000", "price_max": "2300000"},
                    {"tower": "B", "bhk": "1 BHK", "count": 1, "start_number": "101", "price_min": "1500000", "price_max": "1600000"},
                ]},
            })
            assert response.status_code == 200, response.text
            project_id = response.json()["id"]
            response = await client.get(base + f"/properties/{project_id}/units")
            assert response.status_code == 200, response.text
            units = response.json()["items"]
            assert [(unit["tower"], unit["unit_number"], unit["bhk"]) for unit in units] == [
                ("A", "4", "2 BHK"), ("A", "5", "2 BHK"), ("B", "101", "1 BHK")]
            flat = units[0]
            response = await client.patch(base + f"/properties/{project_id}/units/{flat['id']}", json={"asking_price": "2150000"})
            assert response.status_code == 200, response.text
            assert response.json()["asking_price_minor"] == 215000000
            settings = await ensure_crm_settings(db, str(ws_id))
            lead = build_manual_lead(str(ws_id), {"field_values": {"phone": "+14155550123", "full_name": "Praveen"}}, settings)
            await db.crm_leads.insert_one(lead)
            lead_id = str(lead["_id"])
            response = await client.patch(base + f"/crm/leads/{lead_id}/opportunity", json={
                "module": "real_estate", "item_id": flat["id"], "quantity": 1, "amount": "2100000",
            })
            assert response.status_code == 200, response.text
            assert response.json()["opportunity"]["unit_number"] == "4"
            other = build_manual_lead(str(ws_id), {"field_values": {"phone": "+14155550125", "full_name": "Other buyer"}}, settings)
            await db.crm_leads.insert_one(other)
            other_id = str(other["_id"])
            response = await client.patch(base + f"/crm/leads/{other_id}/opportunity", json={"module": "real_estate", "item_id": flat["id"], "amount": "2200000"})
            assert response.status_code == 200, response.text
            response = await client.post(base + f"/crm/leads/{lead_id}/convert", json={"conversion_type": "single_payment"})
            assert response.status_code == 200, response.text
            assert response.json()["opportunity"]["sold_value_minor"] == 210000000
            sold = await db.property_units.find_one({"_id": ObjectId(flat["id"])})
            assert sold["status"] == "sold"
            assert sold["sold_value_minor"] == 210000000
            assert (await db.properties.find_one({"_id": ObjectId(project_id)}))["status"] == "available"
            assert await db.property_units.count_documents({"property_id": project_id, "status": "available"}) == 2
            response = await client.post(base + f"/crm/leads/{other_id}/convert", json={"conversion_type": "single_payment"})
            assert response.status_code == 409
            # Retries do not append a second transaction.
            response = await client.post(base + f"/crm/leads/{lead_id}/convert", json={"conversion_type": "single_payment"})
            assert response.status_code == 200, response.text
            response = await client.patch(base + f"/properties/{project_id}/units/{flat['id']}", json={
                "status": "available", "listing_type": "rent", "asking_price": "25000",
            })
            assert response.status_code == 200, response.text
            assert response.json()["listing_type"] == "rent"
            assert response.json()["status"] == "available"
            assert response.json()["transactions"][0]["value_minor"] == 210000000
            response = await client.post(base + f"/crm/leads/{other_id}/convert", json={"conversion_type": "single_payment"})
            assert response.status_code == 409  # Previous listing's interest cannot claim a relisted flat.
            response = await client.get(base + "/crm/offerings")
            assert response.status_code == 200, response.text
            offerings = response.json()["items"]
            assert any(item["id"] == flat["id"] and item["listing_type"] == "rent" for item in offerings)
            assert not any(item["id"] == project_id for item in offerings)
            renter = build_manual_lead(str(ws_id), {"field_values": {"phone": "+14155550124", "full_name": "Renter"}}, settings)
            await db.crm_leads.insert_one(renter)
            renter_id = str(renter["_id"])
            response = await client.patch(base + f"/crm/leads/{renter_id}/opportunity", json={
                "module": "real_estate", "item_id": flat["id"], "amount": "24000",
            })
            assert response.status_code == 200, response.text
            response = await client.post(base + f"/crm/leads/{renter_id}/convert", json={"conversion_type": "single_payment"})
            assert response.status_code == 200, response.text
            assert response.json()["opportunity"]["sale_status"] == "rented"
            rented = await db.property_units.find_one({"_id": ObjectId(flat["id"])})
            assert rented["status"] == "rented"
            assert [record["value_minor"] for record in rented["transactions"]] == [210000000, 2400000]
            response = await client.post(base + f"/crm/leads/{renter_id}/convert", json={"conversion_type": "single_payment"})
            assert response.status_code == 200, response.text
            assert len((await db.property_units.find_one({"_id": ObjectId(flat["id"])}))["transactions"]) == 2
            # Updating a generated project must preserve customized flat prices and sold history.
            project = (await client.get(base + "/properties")).json()["items"][0]
            response = await client.patch(base + f"/properties/{project_id}", json={"inventory_setup": project["inventory_setup"]})
            assert response.status_code == 200, response.text
            retained = await db.property_units.find_one({"_id": ObjectId(flat["id"])})
            assert retained["asking_price_minor"] == 2500000
            assert len(retained["transactions"]) == 2
            # Two buyers racing to mark the second flat Won: exactly one succeeds.
            competing_ids = []
            for i in range(2):
                competitor = build_manual_lead(str(ws_id), {"field_values": {"phone": f"+1415555013{i}"}}, settings)
                await db.crm_leads.insert_one(competitor)
                competing_ids.append(str(competitor["_id"]))
                response = await client.patch(base + f"/crm/leads/{competitor['_id']}/opportunity", json={
                    "module": "real_estate", "item_id": units[1]["id"], "amount": "2300000",
                })
                assert response.status_code == 200, response.text
            closings = await asyncio.gather(*[
                client.patch(base + f"/crm/leads/{candidate}/", json={"status": "won"}, follow_redirects=True)
                for candidate in competing_ids
            ])
            assert sorted(response.status_code for response in closings) == [200, 409]
            closed_flat = await db.property_units.find_one({"_id": ObjectId(units[1]["id"])})
            assert closed_flat["status"] == "sold"
            assert closed_flat["sold_value_minor"] == 230000000
            assert len(closed_flat["transactions"]) == 1
            # Outsiders cannot read flat inventory or change its pricing.
            outsider = ObjectId()
            await db.users.insert_one({"_id": outsider, "email": "outsider@example.test"})
            client.headers["Authorization"] = "Bearer " + create_access_token(str(outsider), "outsider@example.test")
            assert (await client.get(base + f"/properties/{project_id}/units")).status_code == 403
            assert (await client.patch(base + f"/properties/{project_id}/units/{flat['id']}", json={"asking_price": "1"})).status_code == 403

    asyncio.run(isolated(run))
