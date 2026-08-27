#!/usr/bin/env python3
"""Idempotently provision the designated human Odoo administrator.

Execute only through ``odoo shell -d <database> --no-http``. The script is a
no-write dry run unless ``ODOO_ADMIN_BOOTSTRAP_APPLY=YES`` is present. Password
material must be mounted as a private file and is never printed.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from odoo import Command


EXPECTED_LOGIN = "appolon1908@gmail.com"
DEFAULT_NAME = "Ralph Appolon"
MIN_PASSWORD_LENGTH = 24


def require_shell_environment():
    shell_env = globals().get("env")
    if shell_env is None:
        raise RuntimeError(
            "This script must run inside `odoo shell -d <database> --no-http`."
        )
    return shell_env


def read_password_file() -> str:
    raw_path = os.environ.get("ODOO_ADMIN_PASSWORD_FILE", "").strip()
    if not raw_path:
        raise RuntimeError(
            "ODOO_ADMIN_PASSWORD_FILE must point to a mounted secret file."
        )

    path = Path(raw_path)
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Administrator password path must be a regular file.")

    file_mode = stat.S_IMODE(path.stat().st_mode)
    if file_mode & 0o077:
        raise RuntimeError(
            "Administrator password file must not be group/world accessible."
        )

    password = path.read_text(encoding="utf-8")
    if password != password.strip():
        raise RuntimeError(
            "Administrator password file must contain exactly one value "
            "without leading/trailing whitespace."
        )
    if len(password) < MIN_PASSWORD_LENGTH:
        raise RuntimeError(
            "Administrator password must contain at least "
            f"{MIN_PASSWORD_LENGTH} characters."
        )
    return password


def find_target_user(shell_env, login: str):
    users = shell_env["res.users"].sudo().with_context(active_test=False)
    candidates = users.search(
        ["|", ("login", "=ilike", login), ("email", "=ilike", login)]
    )
    if len(candidates) > 1:
        raise RuntimeError(
            "More than one user matches the administrator login/email. "
            "Resolve the duplicate accounts before provisioning."
        )
    if candidates:
        return candidates

    human_admin = shell_env.ref("base.user_admin").sudo()
    technical_root = shell_env.ref("base.user_root").sudo()
    if human_admin == technical_root:
        raise RuntimeError("Refusing to repurpose Odoo's technical superuser.")
    return human_admin


def main(shell_env) -> None:
    requested_login = os.environ.get(
        "ODOO_ADMIN_LOGIN", EXPECTED_LOGIN
    ).strip().lower()
    if requested_login != EXPECTED_LOGIN:
        raise RuntimeError(
            f"ODOO_ADMIN_LOGIN must remain {EXPECTED_LOGIN!r} for this "
            "reviewed bootstrap."
        )

    requested_name = os.environ.get(
        "ODOO_ADMIN_DISPLAY_NAME", DEFAULT_NAME
    ).strip()
    if not requested_name:
        raise RuntimeError("ODOO_ADMIN_DISPLAY_NAME must not be empty.")

    apply_changes = os.environ.get("ODOO_ADMIN_BOOTSTRAP_APPLY") == "YES"
    target = find_target_user(shell_env, requested_login)
    technical_root = shell_env.ref("base.user_root").sudo()
    if target == technical_root:
        raise RuntimeError("Refusing to provision the technical superuser as a human.")

    group_system = shell_env.ref("base.group_system").sudo()
    group_portal = shell_env.ref("base.group_portal").sudo()
    group_public = shell_env.ref("base.group_public").sudo()

    print(f"DATABASE={shell_env.cr.dbname}")
    print(f"TARGET_USER_ID={target.id}")
    print(f"TARGET_CURRENT_LOGIN={target.login}")
    print(f"TARGET_REQUIRED_LOGIN={requested_login}")
    print("TARGET_REQUIRED_GROUP=base.group_system")
    print(f"APPLY_CHANGES={'YES' if apply_changes else 'NO'}")

    if not apply_changes:
        print("RESULT=DRY_RUN_NO_DATABASE_CHANGE")
        return

    password = read_password_file()

    retained_groups = target.group_ids - group_portal - group_public
    required_groups = retained_groups | group_system
    allowed_companies = target.company_ids | target.company_id

    target.write(
        {
            "name": requested_name,
            "login": requested_login,
            "email": requested_login,
            "active": True,
            "company_ids": [Command.set(allowed_companies.ids)],
            "group_ids": [Command.set(required_groups.ids)],
            "password": password,
        }
    )
    shell_env.flush_all()

    refreshed = shell_env["res.users"].sudo().browse(target.id)
    if refreshed == technical_root:
        raise RuntimeError("Technical superuser protection verification failed.")
    if refreshed.login.lower() != requested_login:
        raise RuntimeError("Administrator login verification failed.")
    if refreshed.email.lower() != requested_login:
        raise RuntimeError("Administrator email verification failed.")
    if not refreshed.active:
        raise RuntimeError("Administrator account is not active.")
    if refreshed.company_id not in refreshed.company_ids:
        raise RuntimeError("Administrator default company is not allowed.")
    if not refreshed.has_group("base.group_system"):
        raise RuntimeError("Administrator group verification failed.")

    active_admins = group_system.user_ids.filtered("active")
    if not active_admins:
        raise RuntimeError("Odoo has no active human administrator.")

    shell_env.cr.commit()
    print(f"ADMIN_USER_ID={refreshed.id}")
    print(f"ADMIN_LOGIN={refreshed.login}")
    print("TECHNICAL_SUPERUSER_REPURPOSED=NO")
    print("ADMINISTRATOR_GROUP=PASS")
    print("PASSWORD_SOURCE=EXTERNAL_SECRET_FILE")
    print("RESULT=ADMINISTRATOR_PROVISIONED")


main(require_shell_environment())
