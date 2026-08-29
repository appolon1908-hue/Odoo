"""Verify the restored database can read its matching filestore sentinel.

Executed through ``odoo shell`` against the disposable restored CI database.
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

attachments = env["ir.attachment"].sudo().search([("name", "=", SENTINEL_NAME)])
if len(attachments) != 1:
    raise RuntimeError(
        f"Expected one restored filestore sentinel, found {len(attachments)}"
    )
attachment = attachments[0]
if not attachment.store_fname:
    raise RuntimeError("Restored attachment does not reference the filestore")

restored_bytes = base64.b64decode(attachment.datas)
actual_sha256 = hashlib.sha256(restored_bytes).hexdigest()
if actual_sha256 != SENTINEL_SHA256:
    raise RuntimeError(
        f"Restored filestore checksum mismatch: {actual_sha256}"
    )
full_path = Path(attachment._full_path(attachment.store_fname))
if not full_path.is_file():
    raise RuntimeError(f"Restored filestore object is missing: {full_path}")

print(f"RESTORED_FILESTORE_SENTINEL_ID={attachment.id}")
print(f"RESTORED_FILESTORE_SENTINEL_SHA256={actual_sha256}")
print("RESTORED_FILESTORE_OBJECT=PASS")
