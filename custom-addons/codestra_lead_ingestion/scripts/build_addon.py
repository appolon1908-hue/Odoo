#!/usr/bin/env python3
"""Recreate a deterministic installable ZIP from this checked-out addon."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

root = Path(__file__).resolve().parents[1]
output = root.parent / "codestra_lead_ingestion.zip"
excluded = {"__pycache__", ".pytest_cache"}
with ZipFile(output, "w", ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in excluded for part in path.parts):
            continue
        relative = Path(root.name) / path.relative_to(root)
        info = ZipInfo(str(relative), (2026, 7, 26, 0, 0, 0))
        info.compress_type = ZIP_DEFLATED
        info.external_attr = (0o755 if path.name == "build_addon.py" else 0o644) << 16
        archive.writestr(info, path.read_bytes())
print(output)
