#!/usr/bin/env python3
"""Validate login branding, asset safety, administrator identity, and audits."""

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
LOGIN_ASSET = "codestra_login_branding/static/src/css/login.css"


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
        LOGIN_ASSET in frontend_assets,
        "login CSS is not in web.assets_frontend",
        errors,
    )
    require(
        not any(str(asset).lower().endswith((".scss", ".sass", ".less")) for asset in frontend_assets),
        "login bundle still declares a custom preprocessor stylesheet",
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

    css_path = MODULE / "static" / "src" / "css" / "login.css"
    try:
        css_text = css_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"cannot read login CSS: {exc}")
        css_text = ""

    for token in ("#07080a", "#f4c223", "#f8fafc", "#a3a8b3"):
        require(
            token in css_text.lower(),
            f"login CSS missing brand token {token}",
            errors,
        )
    require(
        "@media (prefers-reduced-motion: reduce)" in css_text,
        "login CSS lacks reduced-motion handling",
        errors,
    )
    require(
        "width: min(" not in css_text,
        "login CSS uses mixed-unit min() instead of width/max-width",
        errors,
    )
    require(
        "$codestra-" not in css_text and "#{" not in css_text,
        "login CSS contains Sass-only syntax",
        errors,
    )
    require(
        not (MODULE / "static" / "src" / "scss").exists(),
        "legacy login SCSS directory still exists",
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

    appointment_browser_path = (
        ROOT
        / "custom-addons"
        / "codestra_appointments"
        / "tests"
        / "test_popouts_browser.py"
    )
    try:
        appointment_browser_text = appointment_browser_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"cannot read backend browser asset test: {exc}")
        appointment_browser_text = ""
    for required_text in (
        '"/odoo",',
        "style compilation failed",
        "link[rel~=\"stylesheet\"]",
        "ODOO_BACKEND_PRODUCTION_ASSET_BUNDLE=PASS",
    ):
        require(
            required_text in appointment_browser_text,
            f"backend production-bundle test missing {required_text!r}",
            errors,
        )
    require(
        "?debug=assets" not in appointment_browser_text,
        "backend browser test still bypasses the production asset bundle",
        errors,
    )

    login_test_path = (
        ROOT
        / "custom-addons"
        / "codestra_login_branding"
        / "tests"
        / "test_login_branding.py"
    )
    try:
        login_test_text = login_test_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"cannot read login production-bundle test: {exc}")
        login_test_text = ""
    for required_text in (
        "stylesheet_hrefs",
        '"text/css"',
        '".codestra-auth-body"',
        "LOGIN_PRODUCTION_ASSET_BUNDLE=PASS",
    ):
        require(
            required_text in login_test_text,
            f"login production-bundle test missing {required_text!r}",
            errors,
        )

    run_ci_path = ROOT / "scripts" / "run_ci.sh"
    try:
        run_ci_text = run_ci_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"cannot read source CI script: {exc}")
        run_ci_text = ""
    require(
        "python3 -I scripts/validate_asset_integrity.py" in run_ci_text,
        "source CI does not run the repository-wide asset validator",
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
    print("LOGIN_CUSTOM_PREPROCESSOR_STYLESHEETS=0")
    print("REPOSITORY_ASSET_VALIDATOR_REQUIRED=PASS")
    print("ADMINISTRATOR_IDENTITY_POLICY=PASS")
    print("ADMINISTRATOR_BOOTSTRAP_SAFETY=PASS")
    print("ADMINISTRATOR_LOGIN_EMAIL_AUDIT=PASS")
    print("DATABASE_ENTRYPOINT_CONNECTION_GUARD=PASS")
    print("DATABASE_RUNTIME_AUDIT_CONTRACT=PASS")
    print("CODESTRA_ODOO_READINESS_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
