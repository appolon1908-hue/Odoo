import hashlib
import json


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
