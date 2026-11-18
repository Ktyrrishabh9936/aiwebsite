"""A small in-memory stand-in for the Motor calls used by the daily AI run tests."""
from copy import deepcopy
from types import SimpleNamespace

from bson import ObjectId

MISSING = object()


def get_path(doc, path):
    current = doc
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return MISSING
        current = current[part]
    return current


def set_path(doc, path, value):
    parts = path.split(".")
    for part in parts[:-1]:
        if not isinstance(doc.get(part), dict):
            doc[part] = {}
        doc = doc[part]
    doc[parts[-1]] = value


def unset_path(doc, path):
    parts = path.split(".")
    for part in parts[:-1]:
        doc = doc.get(part) if isinstance(doc, dict) else None
        if not isinstance(doc, dict):
            return
    doc.pop(parts[-1], None)


def _compare(value, condition):
    if isinstance(condition, dict) and any(key.startswith("$") for key in condition):
        for op, target in condition.items():
            present = value is not MISSING
            plain = None if value is MISSING else value
            if op == "$in" and plain not in target: return False
            if op == "$nin" and plain in target: return False
            if op == "$ne" and plain == target: return False
            if op == "$exists" and present != bool(target): return False
            if op in {"$gt", "$gte", "$lt", "$lte"}:
                if plain is None: return False
                if op == "$gt" and not plain > target: return False
                if op == "$gte" and not plain >= target: return False
                if op == "$lt" and not plain < target: return False
                if op == "$lte" and not plain <= target: return False
        return True
    plain = None if value is MISSING else value
    if isinstance(plain, list) and not isinstance(condition, list):
        return condition in plain
    return plain == condition


def _operand(doc, operand):
    if isinstance(operand, str) and operand.startswith("$"):
        value = get_path(doc, operand[1:])
        return None if value is MISSING else value
    return operand


def matches(doc, query):
    for key, condition in (query or {}).items():
        if key == "$or":
            if not any(matches(doc, option) for option in condition): return False
        elif key == "$and":
            if not all(matches(doc, option) for option in condition): return False
        elif key == "$expr":
            left, right = (_operand(doc, item) for item in condition["$ne"])
            if left == right: return False
        elif not _compare(get_path(doc, key), condition):
            return False
    return True


def apply(doc, update, inserting=False):
    for key, value in (update.get("$set") or {}).items():
        set_path(doc, key, deepcopy(value))
    if inserting:
        for key, value in (update.get("$setOnInsert") or {}).items():
            set_path(doc, key, deepcopy(value))
    for key in update.get("$unset") or {}:
        unset_path(doc, key)
    for key, value in (update.get("$inc") or {}).items():
        current = get_path(doc, key)
        set_path(doc, key, (0 if current is MISSING else current) + value)
    for key, value in (update.get("$push") or {}).items():
        current = get_path(doc, key)
        set_path(doc, key, [*([] if current is MISSING else current), deepcopy(value)])
    for key, value in (update.get("$pull") or {}).items():
        current = get_path(doc, key)
        if isinstance(current, list):
            set_path(doc, key, [item for item in current if item != value])
    for key, value in (update.get("$addToSet") or {}).items():
        current = [] if get_path(doc, key) is MISSING else get_path(doc, key)
        if value not in current:
            set_path(doc, key, [*current, deepcopy(value)])


class Cursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, key, direction=1):
        for name, order in reversed(key if isinstance(key, list) else [(key, direction)]):
            self.docs.sort(key=lambda doc: (get_path(doc, name) is not MISSING and get_path(doc, name) is not None, str(get_path(doc, name))), reverse=order < 0)
        return self

    def limit(self, count):
        self.docs = self.docs[:count]
        return self

    async def to_list(self, length=None):
        return deepcopy(self.docs[:length] if length else self.docs)


class Collection:
    def __init__(self):
        self.docs = []

    def _find(self, query, sort=None):
        found = [doc for doc in self.docs if matches(doc, query)]
        return Cursor(found).sort(sort).docs if sort else found

    async def find_one(self, query=None, projection=None, sort=None):
        found = self._find(query, sort)
        return deepcopy(found[0]) if found else None

    def find(self, query=None, projection=None):
        return Cursor(list(self._find(query)))

    async def insert_one(self, doc):
        doc.setdefault("_id", ObjectId())
        self.docs.append(deepcopy(doc))
        return SimpleNamespace(inserted_id=doc["_id"])

    async def update_one(self, query, update, upsert=False):
        found = self._find(query)
        if found:
            before = deepcopy(found[0])
            apply(found[0], update)
            return SimpleNamespace(matched_count=1, modified_count=int(before != found[0]), upserted_id=None)
        if not upsert:
            return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)
        doc = {key: value for key, value in query.items() if not key.startswith("$") and not isinstance(value, dict)}
        doc.setdefault("_id", ObjectId())
        apply(doc, update, inserting=True)
        self.docs.append(doc)
        return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=doc["_id"])

    async def update_many(self, query, update):
        found = self._find(query)
        for doc in found:
            apply(doc, update)
        return SimpleNamespace(matched_count=len(found), modified_count=len(found))

    async def find_one_and_update(self, query, update, sort=None, return_document=None, upsert=False):
        found = self._find(query, sort)
        if not found:
            return None
        apply(found[0], update)
        return deepcopy(found[0])

    async def count_documents(self, query=None):
        return len(self._find(query))

    async def delete_one(self, query):
        found = self._find(query)
        if found:
            self.docs.remove(found[0])
        return SimpleNamespace(deleted_count=len(found[:1]))


class FakeDb:
    """Collections are created on first use, like MongoDB."""
    def __init__(self):
        self._collections = {}

    def __getitem__(self, name):
        return self._collections.setdefault(name, Collection())

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]
