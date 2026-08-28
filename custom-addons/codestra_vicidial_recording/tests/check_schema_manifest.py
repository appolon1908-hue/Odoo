import hashlib
import json
from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas" / "recording"
MANIFEST = SCHEMA_DIR / "manifest-v1.json"
EXPECTED_SOURCE = {
    "repository": "Codestra-SRL/telephony-event-gateway",
    "pull_request": 20,
    "head": "ae92b95240a5ff638837121bc2773545bfbf6fdc",
}


def main():
    manifest = json.loads(MANIFEST.read_text())
    assert manifest["contract_version"] == "1.0"
    assert manifest["source_repository"] == EXPECTED_SOURCE["repository"]
    assert manifest["source_pull_request"] == EXPECTED_SOURCE["pull_request"]
    assert manifest["source_head"] == EXPECTED_SOURCE["head"]
    assert manifest["source_schema_count"] == 6
    assert manifest["local_schema_count"] == 0
    declared = manifest["schemas"]
    actual_files = {
        path.name for path in SCHEMA_DIR.glob("recording-*-v1.json")
    }
    assert len(actual_files) == 6
    assert actual_files == set(declared)
    for name, expected in declared.items():
        actual = hashlib.sha256((SCHEMA_DIR / name).read_bytes()).hexdigest()
        assert actual == expected, f"schema drift: {name}"
    print("recording schema manifest and drift gates: PASS")


if __name__ == "__main__":
    main()
