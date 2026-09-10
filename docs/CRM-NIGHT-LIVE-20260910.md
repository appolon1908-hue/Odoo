# Codestra CRM night theme and call-popup repair

The night theme is installed on the existing production Odoo service. The
call-popup startup error reported by the user is repaired in the served backend
JavaScript bundle. Verification completed on 2026-09-10 at 18:04 UTC.

## Applied changes

- Theme: merged PR #101, source
  `cc87205e4a71a6f9af872ddaca2943bbb1e9b2b9`, module version `19.0.1.0.0`.
- RPC repair: source `ba1b079cff92adac561c8b9d1a6a3e0587fc4519`, the narrow
  runtime snapshot in `deploy/hotfixes/odoo19-call-popup-rpc`. It imports RPC
  directly instead of requesting the removed Odoo 19 `rpc` service. Other
  deployed call behavior remains unchanged.
- Both use immutable release files mounted read only. The original integration
  release is unchanged. Only Odoo was recreated; no calls were placed, no
  credentials were changed and no business-module upgrade was performed.
- Production Compose adds `compose.codestra-workspace-theme.yaml` followed by
  `compose.codestra-call-popup-rpc.yaml` to the existing file list.

The user explicitly approved making the theme live after the cloud-browser
visual limitation had been disclosed. PR #101 had approval on its final head
and all required checks passed before the rollout.

## Verification

The Odoo container is healthy. The root returns the existing 303 login redirect;
the branded login returns HTTP 200 and preserves its password and CSRF fields.
The workspace module is installed.

The served backend CSS contains the night-theme rules. The served backend
JavaScript contains the direct RPC import/assignment and no `useService("rpc")`
request in the popup module. Both URLs return HTTP 200; their hashes and exact
URLs are in `deploy/evidence/crm-night-live-20260910.json`.

Source validation passed 172 existing contract tests and two new focused popup
startup tests. The latter run the popup's real setup with an Odoo 19 service map
that has no RPC service and verify a transport error does not reject startup.
They use mocked requests and do not dispatch calls.

An authenticated visual/browser walkthrough remains unverified: the cloud
browser times out opening the CRM. HTTP/static-bundle verification is not a
claim that every browser interaction was tested. Existing user tabs must fully
reload to replace the former `cec4feb` JavaScript bundle with the current asset
URL. On Windows Chrome use Ctrl+Shift+R.

## Recovery

A consistent database/filestore pair was captured with Odoo stopped before
installation, encrypted and read back. Both decrypted component SHA-256 values
matched. Theme maintenance lasted approximately 17.5 seconds; the subsequent
asset-only repair restart took approximately 6.3 seconds.

The encrypted recovery archive and checksum manifest are under
`/opt/codestra/backups/workspace-theme-20260910T175416Z`. The external encryption
key remains at its existing protected location. Plaintext backup intermediates
were removed. No new offhost copy or independent restore rehearsal is claimed.

For RPC rollback, remove only its Compose overlay and recreate Odoo with the
preceding complete file list. For theme rollback, follow the module-uninstall
procedure in `CRM-NIGHT-THEME-ROLLOUT.md` while its source is still mounted.
Regenerate backend assets and reload tabs after either rollback. A database
restore is not required for the JavaScript repair.
