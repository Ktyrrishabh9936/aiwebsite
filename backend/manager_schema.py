"""Shared schema helpers for AI Manager tool definitions."""


def tool(name, label, section, description, properties=None, required=(), *, writes=False, agent="AI Manager", page=""):
    return {"name": name, "label": label, "section": section, "writes": writes, "agent": agent, "page": page,
            "schema": {"type": "function", "function": {"name": name, "description": description,
                "parameters": {"type": "object", "properties": properties or {}, "required": list(required), "additionalProperties": False}}}}


TEXT = {"type": "string", "minLength": 1, "maxLength": 4000}
SHORT = {"type": "string", "maxLength": 200}
ID = {"type": "string", "pattern": "^[a-fA-F0-9]{24}$"}
TIME = {"type": "string", "description": "ISO 8601 timestamp with explicit UTC offset. Ask for timezone if unknown."}
DATE = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$", "description": "YYYY-MM-DD"}
MONEY = {"type": "string", "pattern": r"^\d{1,13}(\.\d{1,2})?$", "description": "Plain amount without currency symbol or commas, e.g. 25000 or 1499.50"}
OFFSET = {"type": "integer", "minimum": 0, "maximum": 10000}
FIELDS = {"type": "object", "description": "Configured lead field keys from get_crm_configuration.", "maxProperties": 40, "additionalProperties": {"type": ["string", "number", "boolean", "null"]}}
