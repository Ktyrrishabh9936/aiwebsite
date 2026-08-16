from datetime import datetime, timezone
from typing import Any, List, Optional
from bson import ObjectId
from pydantic import BaseModel, Field, ConfigDict, BeforeValidator
from typing_extensions import Annotated


def _validate_objectid(v: Any) -> str:
    if isinstance(v, ObjectId):
        return str(v)
    return str(v)


PyObjectId = Annotated[str, BeforeValidator(_validate_objectid)]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BaseDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: Optional[PyObjectId] = Field(default=None, alias="_id")

    @classmethod
    def from_mongo(cls, doc: dict):
        if not doc:
            return None
        return cls(**doc)

    def to_mongo(self, exclude_none: bool = True) -> dict:
        data = self.model_dump(by_alias=True, exclude_none=exclude_none)
        if data.get("_id") is None:
            data.pop("_id", None)
        return data


# ---------- Workspace / Brain ----------
class Workspace(BaseDocument):
    user_id: str
    name: str
    website_url: str
    public_key: str
    model_id: str = "gpt-5.4"
    brain: dict = Field(default_factory=dict)
    brain_status: str = "pending"  # pending | building | ready | error
    roadmap: List[dict] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class Task(BaseDocument):
    workspace_id: str
    title: str
    objective: str
    agent: str  # content | seo | creative | analytics
    deliverable_type: str = "blog_post"
    success_criteria: str = ""
    month_number: int = 1
    requires_approval: bool = False
    scheduled_time: str = Field(default_factory=now_iso)
    status: str = "pending"  # pending | running | awaiting_approval | done | failed
    output_ref: Optional[str] = None
    output_summary: str = ""
    logs: List[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class Blog(BaseDocument):
    workspace_id: str
    title: str
    slug: str
    excerpt: str = ""
    hero_image: str = ""
    author: str = "Arevei AI"
    read_time: str = "5 min read"
    tags: List[str] = Field(default_factory=list)
    blocks: List[dict] = Field(default_factory=list)
    meta_title: str = ""
    meta_description: str = ""
    keywords: List[str] = Field(default_factory=list)
    status: str = "draft"  # draft | published
    generated_by: str = ""
    created_at: str = Field(default_factory=now_iso)
    published_at: Optional[str] = None


class Notification(BaseDocument):
    workspace_id: str
    kind: str = "info"  # info | success | approval | error
    title: str
    body: str = ""
    read: bool = False
    created_at: str = Field(default_factory=now_iso)


BLOG_IMAGE_POOL = [
    "https://images.unsplash.com/photo-1742292042826-cc35ffd81c74?crop=entropy&cs=srgb&fm=jpg&q=85&w=1600",
    "https://images.unsplash.com/photo-1737442528819-5526652236e8?crop=entropy&cs=srgb&fm=jpg&q=85&w=1600",
    "https://images.unsplash.com/photo-1633365088446-9e0d76f54ce5?crop=entropy&cs=srgb&fm=jpg&q=85&w=1600",
    "https://images.unsplash.com/photo-1662505172500-5dd7a764c746?crop=entropy&cs=srgb&fm=jpg&q=85&w=1600",
    "https://images.unsplash.com/photo-1449247709967-d4461a6a6103?crop=entropy&cs=srgb&fm=jpg&q=85&w=1600",
    "https://images.unsplash.com/photo-1497215842964-222b430dc094?crop=entropy&cs=srgb&fm=jpg&q=85&w=1600",
    "https://images.unsplash.com/photo-1499951360447-b19be8fe80f5?crop=entropy&cs=srgb&fm=jpg&q=85&w=1600",
]
