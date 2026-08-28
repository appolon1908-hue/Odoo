#!/usr/bin/env python3
"""Generate sanitized live-server reconciliation artifacts (no secrets/data)."""
from __future__ import annotations

import ast
import csv
import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDONS = ROOT / "custom-addons"
OUT = ROOT / "docs" / "reconciliation"

# Read-only capture from codestra-odoo-1 on 2026-08-28. Hashes cover sorted module files.
SERVER = {
"call_center_campaign":("b4ecb2097e088dec5f8a1386dae38f46501dcb5c39e2ba77e50251334d30241a", "19.0.5.2.0", "installed"), "call_center_compliance":("4e04f7458c6d5976ac9a3af2d8e27ff4042f0ab5414e3e98fb3202c95729fd72", "19.0.1.0.0", "installed"),
"call_center_core":("38c484481ea301431ba599accb6c562179f0ec7b6b9418998e40e95567b6a3a0", "19.0.2.0.2", "installed"), "call_center_lead_validation":("fd8edac28e4a156a101f1fd67ed37b431e61da62b1651b243c85931a3af1a13d", "19.0.1.1.0", "installed"),
"call_center_orchestration":("69bf38d3963f0a352120a6d9416a148eb46b54e9aa275d19f365d253f3b2fddf", "19.0.1.0.0", "installed"), "codestra":("183c7586f0be5441ed77fbfc485407f973383b7887b97fcf2002ebfb8a6eb983", "19.0.1.0.0", "installed"),
"codestra_ai_call_audit":("fe01454519f93e984fcd3f40147fc3016f20177ab6af3aaf80f889acd0c5608b", "19.0.1.0.0", "installed"), "codestra_ai_core":("da8f751f02507f46390d88fe86a2be1f43f554e0c272929ff09980e4cd4a1058", "19.0.1.0.0", "installed"),
"codestra_ai_qualification":("c20a13219678d05d2ba12784318ec7fc2ece0fa13cfd432e4095796e19ba2ada", "19.0.1.0.0", "installed"), "codestra_ai_realtime_assistant":("e22306b4086a79ad46545007d3b6512c423cc34ce374d514530647f7451a8834", "19.0.1.0.0", "installed"),
"codestra_ai_review":("aa8a1a3dce8d0cde807bcc4ad2193ca057d730f654dabee0754d53931f887ad2", "19.0.1.0.0", "installed"), "codestra_analytics_reporting":("e19d83459d33c9536465e7b906ac75c7fee016e8788da054be8602a01ecbf586", "19.0.1.0.0", "installed"),
"codestra_appointments":("04454932f83c61165ef58109ea005b697a2e6c087864fbe92a79bbf6416b29ed", "19.0.3.0.0", "installed"), "codestra_base":("b8cd45836227490e1c692314ef8ad5a7c26c331af942891f368a0356961b9f10", "19.0.1.0.0", "installed"),
"codestra_campaign_crm_os":("97eaed9ef30f8766e8300107b71d4176d7064329226824f320f56f2d88cb6704", "19.0.1.2.1", "installed"), "codestra_daily_reporting":("94a92735c62fab438da62486c95b1ec866b01e67888a0fcef4ef53dbbc91d96b", "19.0.1.0.0", "installed"),
"codestra_identity_provisioning":("4e1860e505e88f6c040e1fcddc742b083e7e17e5eb6fd3163ebf8496e6b96bbe", "19.0.1.1.2", "installed"), "codestra_integration_hub":("02a68b75b54b925830d151d64053096f0bd40d10b08bfa0cd49377cefd8430ff", "19.0.1.0.0", "installed"),
"codestra_ivr_control":("67ff23cf5a560b4b917b03fe67366de11fc23570f6bed3f01bc46862bab3e0f9", "19.0.1.0.0", "installed"), "codestra_lead_ingestion":("78d84854c1d9ca585270e501c1ae57ce286c5dde23f0e1bcbd9b6fae5e002b02", "19.0.1.0.0", "installed"),
"codestra_middleware_bridge":("c2093f3cf0cc01e505649d153399e7dd9fbbb21d0d385baa98493dc20358f568", "19.0.1.0.1", "installed"), "codestra_social_orchestration":("a33cfb57be960298317f925dca91aa10e25e09b0447d65b69d204013521c77db", "19.0.1.0.0", "uninstalled"),
"codestra_transcription":("e0a2dcacce5c237b62e483e1bde031d73e2662708aa3339e38d2e1250650aaa4", "19.0.1.0.0", "installed"), "codestra_vicidial_connector":("9e8568d818caf2f570669ab1ad3e22b41811e5de19b92474972a2fc876cb159b", "19.0.1.0.0", "installed"),
"codestra_vicidial_crm":("857c38ac3fd52201fe96d734f13c405685e63991fa9081f90539e98d4f8eb193", "19.0.3.0.0", "installed"),
"codestra_mail_inbox":("NOT_CAPTURED_SHARED_PATH", "19.0.1.1.0", "installed"),
"codestra_odoo_certification":("NOT_CAPTURED_SHARED_PATH", "19.0.1.0.0", "installed"),
"codestra_interaction_workflow":("ABSENT", "19.0.1.0.0", "uninstalled"), "codestra_lead_automation":("ABSENT", "19.0.1.0.0", "uninstalled"),
"codestra_staging_campaign_design":("ABSENT", "19.0.1.0.0", "uninstalled"), "codestra_telephony_bridge":("ABSENT", "19.0.1.0.0", "uninstalled"),
"codestra_vicidial_recording":("ABSENT", "19.0.1.0.0", "uninstalled"),
}

def digest(path: Path) -> str:
    """Hash the committed module files, independent of checkout line endings."""
    module_path = path.relative_to(ROOT).as_posix()
    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD", "--", module_path],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    h = hashlib.sha256()
    for tracked_path in sorted(listing):
        relative_path = tracked_path.removeprefix(f"{module_path}/")
        blob = subprocess.run(
            ["git", "show", f"HEAD:{tracked_path}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
        h.update(relative_path.encode())
        h.update(b"\0")
        h.update(blob)
        h.update(b"\0")
    return h.hexdigest()

def main() -> None:
    inv = {r["module"]: r for r in csv.DictReader((OUT / "ODOO-MODULE-INVENTORY.csv").open())}
    cols = "module server_path server_checksum server_version server_installed_state github_path github_checksum github_version approved_checksum source_branch source_commit dependencies migration_required security_status test_status classification disposition owner".split()
    rows=[]
    for module in sorted(set(inv) | set(SERVER)):
        item=inv.get(module, {}); server=SERVER.get(module); github_path=ADDONS/module
        gh_hash=digest(github_path) if github_path.is_dir() else ""
        gh_ver=item.get("manifest_version", "")
        if not server: classification="GITHUB_ONLY"
        elif server[0] in {"ABSENT", "NOT_CAPTURED_SHARED_PATH"}: classification="GITHUB_ONLY" if server[0]=="ABSENT" else "SENSITIVE_EXCLUDED"
        elif server[1] != gh_ver: classification="VERSION_DRIFT"
        elif not server[0].startswith(gh_hash): classification="CONTENT_DRIFT"
        else: classification="MATCH"
        security="REVIEW_REQUIRED" if module=="call_center_campaign" else "SOURCE_CI_PASS"
        rows.append(dict(zip(cols,[module, f"/mnt/extra-addons/{module}" if server and server[0] not in {"ABSENT","NOT_CAPTURED_SHARED_PATH"} else "", server[0] if server else "", server[1] if server else "", server[2] if server else "absent", f"custom-addons/{module}" if github_path.is_dir() else "", gh_hash, gh_ver, gh_hash, item.get("source_branch",""), item.get("source_commit",""), item.get("dependencies",""), "YES" if item.get("migrations","0") not in {"","0"} else "NO", security, "PASS_CURRENT_RUNTIME_SUITE", classification, "RECONCILE_IN_STAGING" if classification not in {"MATCH","GITHUB_ONLY"} else ("INSTALL_ONLY_IF_APPROVED" if classification=="GITHUB_ONLY" else "RETAIN"), item.get("ownership","")])))
    with (ROOT/"SERVER-VS-GITHUB-MODULE-LEDGER.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=cols,lineterminator="\n"); w.writeheader(); w.writerows(rows)
    counts={c:sum(r["classification"]==c for r in rows) for c in sorted({r["classification"] for r in rows})}
    (ROOT/"SERVER-VS-GITHUB-DRIFT.md").write_text(f"""# Server vs GitHub drift — 2026-08-28

This is a sanitized, read-only baseline. No production service, database, filestore, flag, or integration was changed.

## Result

- Candidate: `4681d755039ee7f4fec21228bac234a668541de8` reconstructed on `reconcile/odoo-canonical-source-v1`.
- Candidate modules: 67. Active `/mnt/extra-addons` modules: 25. Registry custom rows: 32.
- Classifications: {counts}.
- Production source is a mutable host checkout mounted read-only into Odoo and does not match the candidate. It must not be promoted as canonical.
- Two installed registry modules were on a separate/shared addon path and their content was deliberately not copied; they are `SENSITIVE_EXCLUDED`, not unknown.

## Runtime baseline

- Odoo: `19.0-20260630`; image `odoo@sha256:f54272f31d5f77e4146b887efb3761c98480317daf687e4b4b5e76ed8bcc08c5`.
- PostgreSQL: 17.6; database size 92,425,363 bytes.
- Filestore: `/var/lib/odoo/.local/share/Odoo/filestore/codestra_odoo`, 93,816,150 bytes, 224 files; 630 attachment rows.
- Proxy mode enabled; worker/cron process settings were not explicit in the captured config. Registry had 39 cron records.
- Compose project `codestra`; Odoo has no published host port and is attached to backend/edge/integration networks.
- Routing/auth components observed: Caddy, Kong 3.14, Keycloak. Only metadata was captured.

## Effects and flags

All captured production-effect flags were false except `CODESTRA_CALLBACK_SYNC_ENABLED=true`; `CODESTRA_PRODUCTION_CALLBACKS=false` and the database callback/production flags were false. Email, SMS, PSTN, campaign activation, n8n production, transfer, provider-write, and VICIdial-write flags were false. No flag was changed.

## Backups and recovery

The latest observed paired backup was `klyrow-unified-20260822T200000Z` (database plus filestore with checksums), not a current release pair. Existing evidence records a 30-second mechanics exercise but says representative Odoo 19 rollback remains blocked. Recovery is therefore **not certified**.

## Security and correctness blockers

- Fresh isolated Odoo 19/PostgreSQL 17.6 install passed 451 tests, but four campaign integration models emitted missing-ACL warnings.
- Installed-vs-manifest version drift exists on live modules; content drift requires staged migrations, not direct copying.
- Campaign isolation negative tests, deployed-baseline upgrade, interruption restart, paired restore, and staging certification remain required.
- HTTP health is not accepted as business certification.
""", encoding="utf-8")

if __name__ == "__main__": main()
