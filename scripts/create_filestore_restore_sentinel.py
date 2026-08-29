"""Create a deterministic attachment that proves the filestore is recoverable.

Executed through ``odoo shell`` against a disposable CI database only.
"""

import base64
import hashlib
from pathlib import Path


SENTINEL_NAME = "CODESTRA-CI-PAIRED-RESTORE-SENTINEL.bin"
SENTINEL_BYTES = (
    b"Codestra disposable paired database and filestore restore rehearsal\n"
    + bytes(range(256)) * 16
)
SENTINEL_SHA256 = hashlib.sha256(SENTINEL_BYTES).hexdigest()

existing = env["ir.attachment"].sudo().search([("name", "=", SENTINEL_NAME)])
if existing:
    existing.unlink()

attachment = env["ir.attachment"].sudo().create({
    "name": SENTINEL_NAME,
    "type": "binary",
    "datas": base64.b64encode(SENTINEL_BYTES),
    "mimetype": "application/octet-stream",
    "description": "Synthetic CI-only paired restore sentinel.",
})
if not attachment.store_fname:
    raise RuntimeError("Filestore sentinel was stored in PostgreSQL instead of the filestore")
if hashlib.sha256(base64.b64decode(attachment.datas)).hexdigest() != SENTINEL_SHA256:
    raise RuntimeError("Filestore sentinel failed immediate checksum verification")

env.cr.commit()
filestore_database_dir = Path(attachment._full_path(attachment.store_fname)).parents[1]
print(f"FILESTORE_SENTINEL_ID={attachment.id}")
print(f"FILESTORE_SENTINEL_SHA256={SENTINEL_SHA256}")
print(f"FILESTORE_DATABASE_DIR={filestore_database_dir}")
print("FILESTORE_SENTINEL_CREATE=PASS")
