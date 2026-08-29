#!/usr/bin/env python3
"""Require every GitHub Action reference to use an immutable commit SHA."""
from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parents[1]
errors = []
for workflow in sorted((root / ".github/workflows").glob("*.y*ml")):
    for number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
        match = re.search(r"\buses:\s*([^\s#]+)", line)
        if match and not re.search(r"@[0-9a-f]{40}$", match.group(1)):
            errors.append(f"{workflow.relative_to(root)}:{number}: {match.group(1)}")
if errors:
    print("Unpinned GitHub Actions:", *errors, sep="\n  - ", file=sys.stderr)
    raise SystemExit(1)
print("GITHUB_ACTIONS_PIN_VALIDATION=PASS")
