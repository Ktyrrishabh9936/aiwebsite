"""Workspace membership, owner permissions, and safe member workspace discovery."""
from bson import ObjectId
from fastapi import HTTPException

MEMBER_ROLES = {"sales_agent", "channel_partner"}


async def resolve_access(db, user, workspace):
    if str(workspace.get("user_id")) == str(user["_id"]) or user.get("role") == "admin":
        return {"role": "owner", "user_id": str(user["_id"]), "workspace_id": str(workspace["_id"]), "active": True}
    membership = await db.workspace_memberships.find_one({"workspace_id": str(workspace["_id"]), "user_id": str(user["_id"]), "active": True})
    if not membership or membership.get("role") not in MEMBER_ROLES or not ObjectId.is_valid(membership.get("sales_person_id", "")):
        raise HTTPException(403, "Workspace access has been revoked or is unavailable")
    person = await db.crm_sales_people.find_one({"workspace_id": str(workspace["_id"]), "_id": ObjectId(membership["sales_person_id"]), "active": True, "role": membership["role"]})
    if not person or person.get("user_id") != str(user["_id"]):
        raise HTTPException(403, "Workspace membership is inactive")
    return membership


async def member_context(request, db, ws_id):
    from auth import get_current_user
    user = await get_current_user(request, db)
    if not ObjectId.is_valid(ws_id):
        raise HTTPException(404, "Workspace not found")
    workspace = await db.workspaces.find_one({"_id": ObjectId(ws_id)})
    if not workspace:
        raise HTTPException(404, "Workspace not found")
    return user, workspace, await resolve_access(db, user, workspace)


async def accessible_workspaces(db, user):
    owned = await db.workspaces.find({"user_id": str(user["_id"])}).sort("created_at", -1).to_list(100)
    rows = [{"id": str(doc["_id"]), "name": doc.get("name", "Workspace"), "access_role": "owner"} for doc in owned]
    memberships = await db.workspace_memberships.find({"user_id": str(user["_id"]), "active": True}).to_list(100)
    existing = {row["id"] for row in rows}
    for member in memberships:
        ws_id = member.get("workspace_id", "")
        if ws_id in existing or not ObjectId.is_valid(ws_id):
            continue
        workspace = await db.workspaces.find_one({"_id": ObjectId(ws_id)})
        if not workspace:
            continue
        try:
            access = await resolve_access(db, user, workspace)
        except HTTPException:
            continue
        rows.append({"id": ws_id, "name": workspace.get("name", "Workspace"), "access_role": access["role"]})
        existing.add(ws_id)
    return rows


def workspace_shell(workspace, membership):
    from workspace_modules import workspace_currency
    return {"id": str(workspace["_id"]), "name": workspace.get("name", "Workspace"), "access_role": membership["role"], "currency": workspace_currency(workspace)}


def permitted_leads(ws_id, membership):
    query = {"workspace_id": ws_id, "deleted_at": None}
    person_id = membership.get("sales_person_id")
    if membership["role"] == "sales_agent":
        query["sales_assignment.sales_agent_id"] = person_id
    elif membership["role"] == "channel_partner":
        query["$or"] = [{"sales_assignment.channel_partner_id": person_id}, {"sales_assignment.introduced_by_id": person_id}]
    elif membership["role"] != "owner":
        raise HTTPException(403, "Invalid workspace role")
    return query
