import os
import jwt
import bcrypt
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from fastapi import APIRouter, Request, HTTPException, Depends, Response
from pydantic import BaseModel, EmailStr, Field

JWT_ALGORITHM = "HS256"


def get_jwt_secret():
    return os.environ["JWT_SECRET"]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, email: str) -> str:
    payload = {"sub": user_id, "email": email, "type": "access",
               "exp": datetime.now(timezone.utc) + timedelta(days=7)}
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


class RegisterInput(BaseModel):
    name: str
    email: EmailStr
    password: str = Field(min_length=6)


class LoginInput(BaseModel):
    email: EmailStr
    password: str


def build_auth_router(db):
    router = APIRouter(prefix="/api/auth", tags=["auth"])

    async def _issue(user, response: Response):
        token = create_access_token(str(user["_id"]), user["email"])
        response.set_cookie("access_token", token, httponly=True, secure=True,
                            samesite="none", max_age=604800, path="/")
        return {
            "token": token,
            "user": {"id": str(user["_id"]), "name": user.get("name"), "email": user["email"], "role": user.get("role", "user")},
        }

    @router.post("/register")
    async def register(body: RegisterInput, response: Response):
        email = body.email.lower()
        if await db.users.find_one({"email": email}):
            raise HTTPException(status_code=400, detail="Email already registered")
        doc = {"name": body.name, "email": email, "password_hash": hash_password(body.password),
               "role": "user", "created_at": datetime.now(timezone.utc).isoformat()}
        res = await db.users.insert_one(doc)
        doc["_id"] = res.inserted_id
        return await _issue(doc, response)

    @router.post("/login")
    async def login(body: LoginInput, response: Response):
        email = body.email.lower()
        user = await db.users.find_one({"email": email})
        if not user or not verify_password(body.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        return await _issue(user, response)

    @router.post("/logout")
    async def logout(response: Response):
        response.delete_cookie("access_token", path="/")
        return {"ok": True}

    @router.get("/me")
    async def me(request: Request):
        user = await get_current_user(request, db)
        return {"id": str(user["_id"]), "name": user.get("name"), "email": user["email"], "role": user.get("role", "user")}

    return router


async def get_current_user(request: Request, db) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def seed_admin(db):
    email = os.environ.get("ADMIN_EMAIL", "admin@arevei.ai")
    password = os.environ.get("ADMIN_PASSWORD", "arevei123")
    existing = await db.users.find_one({"email": email})
    if existing is None:
        await db.users.insert_one({"name": "Admin", "email": email,
                                   "password_hash": hash_password(password), "role": "admin",
                                   "created_at": datetime.now(timezone.utc).isoformat()})
    elif not verify_password(password, existing["password_hash"]):
        await db.users.update_one({"email": email}, {"$set": {"password_hash": hash_password(password)}})
