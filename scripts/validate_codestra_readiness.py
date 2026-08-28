#!/usr/bin/env python3
"""Validate login branding, administrator identity, and runtime audit controls."""

from __future__ import annotations

import ast
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "custom-addons" / "codestra_login_branding"
EXPECTED_LOGIN = "appolon1908@gmail.com"


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    errors: list[str] = []

    identity_path = ROOT / "config" / "admin-identity.json"
    try:
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"cannot load admin identity policy: {exc}")
        identity = {}

    human = identity.get("human_administrator", {})
    require(
        human.get("login") == EXPECTED_LOGIN,
        "administrator login is not canonical",
        errors,
    )
    require(
        human.get("email") == EXPECTED_LOGIN,
        "administrator email is not canonical",
        errors,
    )
    require(
        human.get("required_odoo_group") == "base.group_system",
        "administrator must require base.group_system",
        errors,
    )
    require(
        identity.get("technical_superuser", {}).get("must_not_be_repurposed")
        is True,
        "technical superuser must not be repurposed",
        errors,
    )
    require(
        identity.get("password_policy", {}).get("committed_to_git") is False,
        "password policy must prohibit Git storage",
        errors,
    )

    manifest_path = MODULE / "__manifest__.py"
    try:
        manifest = ast.literal_eval(manifest_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError) as exc:
        errors.append(f"cannot parse login module manifest: {exc}")
        manifest = {}

    require(
        "web" in manifest.get("depends", []),
        "login module must depend on web",
        errors,
    )
    require(
        "views/login_templates.xml" in manifest.get("data", []),
        "login templates are not loaded by the manifest",
        errors,
    )
    frontend_assets = manifest.get("assets", {}).get("web.assets_frontend", [])
    require(
        "codestra_login_branding/static/src/scss/login.scss" in frontend_assets,
        "login SCSS is not in web.assets_frontend",
        errors,
    )

    template_path = MODULE / "views" / "login_templates.xml"
    try:
        ET.parse(template_path)
        template_text = template_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ET.ParseError) as exc:
        errors.append(f"login template XML is invalid: {exc}")
        template_text = ""

    for required_text in (
        'inherit_id="web.login_layout"',
        'inherit_id="web.login"',
        "codestra-login-shell",
        "Codestra CRM",
        "Continue securely",
        '<t t-out="0"',
    ):
        require(
            required_text in template_text,
            f"login template missing {required_text!r}",
            errors,
        )
    require(
        "Powered by" not in template_text,
        "login template reintroduces vendor branding",
        errors,
    )
    require(
        "/web/database/manager" not in template_text,
        "login template exposes database manager",
        errors,
    )

    scss_text = (MODULE / "static" / "src" / "scss" / "login.scss").read_text(
        encoding="utf-8"
    )
    for token in ("#07080a", "#f4c223", "#f8fafc", "#a3a8b3"):
        require(
            token in scss_text.lower(),
            f"login SCSS missing brand token {token}",
            errors,
        )
    require(
        "@media (prefers-reduced-motion: reduce)" in scss_text,
        "login SCSS lacks reduced-motion handling",
        errors,
    )
    require(
        "width: min(" not in scss_text,
        "login SCSS uses mixed-unit Sass min() instead of width/max-width",
        errors,
    )

    admin_script = (ROOT / "scripts" / "ensure_codestra_admin.py").read_text(
        encoding="utf-8"
    )
    for required_text in (
        EXPECTED_LOGIN,
        "ODOO_ADMIN_BOOTSTRAP_APPLY",
        "ODOO_ADMIN_PASSWORD_FILE",
        "base.group_system",
        "base.user_root",
        "Command.set",
        "shell_env.cr.commit()",
    ):
        require(
            required_text in admin_script,
            f"administrator bootstrap missing {required_text!r}",
            errors,
        )
    require(
        not re.search(
            r"(?i)password\s*=\s*['\"](?!external|password)[^'\"]+['\"]",
            admin_script,
        ),
        "administrator bootstrap appears to contain a literal password",
        errors,
    )

    runtime_script = (ROOT / "scripts" / "audit_odoo_runtime.sh").read_text(
        encoding="utf-8"
    )
    for required_text in (
        "pg_isready",
        "to_regclass('public.ir_module_module')",
        "test -x /entrypoint.sh",
        '"$ODOO_ENTRYPOINT" -- shell',
        "ODOO_SHELL_CONNECTION_MODE=ENTRYPOINT_ENV_TRANSLATION",
        "audit_odoo_state.py",
        "RUNTIME_AUDIT=PASS",
    ):
        require(
            required_text in runtime_script,
            f"runtime audit missing {required_text!r}",
            errors,
        )

    state_audit_text = (ROOT / "scripts" / "audit_odoo_state.py").read_text(
        encoding="utf-8"
    )
    for required_text in (
        '("login", "=ilike", EXPECTED_LOGIN)',
        '("email", "=ilike", EXPECTED_LOGIN)',
        "normalized_login",
        "normalized_email",
        "DESIGNATED_ADMIN_IDENTITY",
        "ADMINISTRATOR_IDENTITY_AUDIT=PASS",
    ):
        require(
            required_text in state_audit_text,
            f"Odoo state audit missing {required_text!r}",
            errors,
        )

    runtime_ci_path = ROOT / "scripts" / "run_odoo_module_tests.sh"
    try:
        runtime_ci_text = runtime_ci_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"cannot read runtime CI script: {exc}")
        runtime_ci_text = ""

    for required_text in (
        "odoo@sha256:f54272f31d5f77e4146b887efb3761c98480317daf687e4b4b5e76ed8bcc08c5",
        "postgres:17.6-alpine@sha256:ef257d85f76e48da1c64832459b59fcaba1a4dac97bf5d7450c77753542eee94",
        "--without-demo \\",
        "--test-enable",
        "ODOO_ASSET_COMPILATION_INTERNAL_ERROR",
        "ODOO_ASSET_COMPILATION=PASS",
        "ensure_codestra_admin.py",
        "audit_odoo_state.py",
        "ODOO_POSTGRESQL_RUNTIME_CI=PASS",
    ):
        require(
            required_text in runtime_ci_text,
            f"runtime CI missing {required_text!r}",
            errors,
        )

    workflow_path = ROOT / ".github" / "workflows" / "odoo-addons-ci.yml"
    try:
        workflow_text = workflow_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"cannot read Odoo CI workflow: {exc}")
        workflow_text = ""

    for required_text in (
        "source-head-validation:",
        "merge-result-validation:",
        "runtime-validation:",
        "main-runtime-validation:",
        "bash scripts/run_odoo_module_tests.sh",
    ):
        require(
            required_text in workflow_text,
            f"Odoo CI workflow missing {required_text!r}",
            errors,
        )

    if errors:
        print("Codestra readiness validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print("LOGIN_BRANDING_CONTRACT=PASS")
    print("LOGIN_ASSET_COMPATIBILITY_GUARD=PASS")
    print("ADMINISTRATOR_IDENTITY_POLICY=PASS")
    print("ADMINISTRATOR_BOOTSTRAP_SAFETY=PASS")
    print("ADMINISTRATOR_LOGIN_EMAIL_AUDIT=PASS")
    print("DATABASE_ENTRYPOINT_CONNECTION_GUARD=PASS")
    print("DATABASE_RUNTIME_AUDIT_CONTRACT=PASS")
    print("CODESTRA_ODOO_READINESS_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
