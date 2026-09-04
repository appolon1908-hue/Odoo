"""Load Klyrow SMTP passwords from a protected file inside ``odoo shell``.

This script intentionally leaves live delivery disabled and never prints secrets.
"""

import os
import stat
from pathlib import Path

from odoo import fields
from odoo.exceptions import UserError


SECRET_PATH = Path(
    os.environ.get("KLYROW_ODOO_SMTP_ENV_FILE", "/etc/klyrow/odoo-postal.env")
)
SHARED_SECRET_KEY = os.environ.get(
    "KLYROW_ODOO_SMTP_PASSWORD_KEY",
    "KLYROW_ODOO_SMTP_PASSWORD",
)
BEYVRA_SECRET_KEY = os.environ.get(
    "KLYROW_BEYVRA_SMTP_PASSWORD_KEY",
    "KLYROW_BEYVRA_SMTP_PASSWORD",
)
MAX_SECRET_FILE_SIZE = 64 * 1024


def _parse_protected_env(path):
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise UserError(f"Cannot read the Klyrow SMTP secret file: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise UserError("The Klyrow SMTP secret file must not be a symlink.")
    if not stat.S_ISREG(metadata.st_mode):
        raise UserError("The Klyrow SMTP secret path must be a regular file.")
    if metadata.st_uid not in {0, os.geteuid()}:
        raise UserError("The Klyrow SMTP secret file has an unexpected owner.")
    if metadata.st_mode & 0o077:
        raise UserError("The Klyrow SMTP secret file must not grant group/world access.")
    if metadata.st_size > MAX_SECRET_FILE_SIZE:
        raise UserError("The Klyrow SMTP secret file exceeds the permitted size.")

    values = {}
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise UserError(f"Invalid secret file line {number}.")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]
        if not key or not value:
            raise UserError(f"Empty key or value on secret file line {number}.")
        if key in values:
            raise UserError(f"Duplicate key on secret file line {number}.")
        values[key] = value
    return values


secrets = _parse_protected_env(SECRET_PATH)
shared_secret = secrets.get(SHARED_SECRET_KEY)
if not shared_secret:
    raise UserError(f"Required secret key {SHARED_SECRET_KEY!r} is missing.")

shared = env.ref("codestra_klyrow_smtp.mail_server_klyrow_production")
beyvra = env.ref("codestra_klyrow_smtp.mail_server_beyvra_production")

shared.write(
    {
        "smtp_pass": shared_secret,
        "active": False,
        "codestra_secret_loaded_at": fields.Datetime.now(),
    }
)

beyvra_secret = secrets.get(BEYVRA_SECRET_KEY)
if beyvra_secret:
    beyvra.write(
        {
            "smtp_pass": beyvra_secret,
            "active": False,
            "codestra_credential_state": "hold",
            "codestra_secret_loaded_at": fields.Datetime.now(),
        }
    )
else:
    beyvra.write({"active": False})

env["ir.config_parameter"].sudo().set_param(
    "codestra.mail.live_delivery_enabled",
    "false",
)
env.cr.commit()

print("KLYROW_SMTP_SHARED_SECRET_LOADED=YES")
print(
    "KLYROW_SMTP_BEYVRA_SECRET_LOADED="
    + ("YES" if bool(beyvra_secret) else "NO")
)
print("KLYROW_SMTP_SERVERS_ACTIVE=NO")
print("KLYROW_LIVE_DELIVERY_ENABLED=NO")
