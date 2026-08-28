#!/usr/bin/env python3
"""Read-only Odoo-shell audit for database, administrators, and modules."""

from __future__ import annotations

import os


EXPECTED_LOGIN = os.environ.get(
    "EXPECTED_ADMIN_LOGIN", "appolon1908@gmail.com"
).strip().lower()


def require_shell_environment():
    shell_env = globals().get("env")
    if shell_env is None:
        raise RuntimeError(
            "This script must run inside `odoo shell -d <database> --no-http`."
        )
    return shell_env


def main(shell_env) -> None:
    failures: list[str] = []
    users = shell_env["res.users"].sudo().with_context(active_test=False)
    modules = shell_env["ir.module.module"].sudo()
    group_system = shell_env.ref("base.group_system").sudo()

    admin_matches = users.search(
        [
            "|",
            ("login", "=ilike", EXPECTED_LOGIN),
            ("email", "=ilike", EXPECTED_LOGIN),
        ]
    )
    if len(admin_matches) != 1:
        failures.append(
            "expected exactly one user matching administrator login or email "
            f"{EXPECTED_LOGIN!r}; found {len(admin_matches)}"
        )
        designated = users.browse()
    else:
        designated = admin_matches

    active_admins = group_system.user_ids.filtered("active")
    if not active_admins:
        failures.append("no active users belong to base.group_system")

    if designated:
        normalized_login = (designated.login or "").strip().lower()
        normalized_email = (designated.email or "").strip().lower()
        if normalized_login != EXPECTED_LOGIN:
            failures.append(
                "designated administrator login does not match the identity policy"
            )
        if normalized_email != EXPECTED_LOGIN:
            failures.append(
                "designated administrator email does not match the identity policy"
            )
        if not designated.active:
            failures.append("designated administrator is inactive")
        if not designated.has_group("base.group_system"):
            failures.append(
                "designated administrator does not belong to base.group_system"
            )

    critical_states = {
        module.name: module.state
        for module in modules.search([("name", "in", ["base", "web"])])
    }
    for required_module in ("base", "web"):
        if critical_states.get(required_module) != "installed":
            failures.append(
                f"required module {required_module!r} is not installed "
                f"(state={critical_states.get(required_module)!r})"
            )

    pending = modules.search(
        [
            (
                "state",
                "in",
                ["to install", "to upgrade", "to remove"],
            )
        ]
    )
    if pending:
        failures.append(
            "modules have pending state transitions: "
            + ", ".join(f"{module.name}={module.state}" for module in pending)
        )

    expected_modules = [
        value.strip()
        for value in os.environ.get("EXPECTED_ODOO_MODULES", "").split(",")
        if value.strip()
    ]
    expected_states = {}
    for module_name in expected_modules:
        module = modules.search([("name", "=", module_name)], limit=1)
        expected_states[module_name] = module.state if module else "missing"
        if not module or module.state != "installed":
            failures.append(
                f"expected custom module {module_name!r} is "
                f"{expected_states[module_name]!r}, not 'installed'"
            )

    installed_count = modules.search_count([("state", "=", "installed")])
    uninstallable_count = modules.search_count([("state", "=", "uninstallable")])

    print(f"DATABASE={shell_env.cr.dbname}")
    print("DATABASE_REGISTRY=PASS")
    print(f"INSTALLED_MODULES={installed_count}")
    print(f"UNINSTALLABLE_MODULES={uninstallable_count}")
    print(f"ACTIVE_ADMINISTRATORS={len(active_admins)}")
    print(
        "DESIGNATED_ADMIN_LOGIN="
        + (designated.login if designated else "MISSING_OR_DUPLICATE")
    )
    print(
        "DESIGNATED_ADMIN_EMAIL="
        + ((designated.email or "") if designated else "MISSING_OR_DUPLICATE")
    )
    print(
        "DESIGNATED_ADMIN_IDENTITY="
        + (
            "PASS"
            if designated
            and (designated.login or "").strip().lower() == EXPECTED_LOGIN
            and (designated.email or "").strip().lower() == EXPECTED_LOGIN
            else "FAIL"
        )
    )
    print(
        "DESIGNATED_ADMIN_GROUP="
        + (
            "PASS"
            if designated and designated.has_group("base.group_system")
            else "FAIL"
        )
    )
    for module_name in sorted(expected_states):
        print(
            f"EXPECTED_MODULE_{module_name.upper().replace('-', '_')}="
            f"{expected_states[module_name]}"
        )

    if failures:
        for failure in failures:
            print(f"ERROR={failure}")
        raise SystemExit(1)

    print("ADMINISTRATOR_IDENTITY_AUDIT=PASS")
    print("MODULE_STATE_AUDIT=PASS")
    print("ODOO_STATE_AUDIT=PASS")


main(require_shell_environment())
