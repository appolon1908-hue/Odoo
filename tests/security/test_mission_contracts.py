import csv
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class MissionContractTests(unittest.TestCase):
    def test_all_live_capabilities_are_closed(self):
        policy = json.loads((ROOT / "config/mission-safety-policy.json").read_text())
        self.assertTrue(policy["live_capabilities"])
        self.assertFalse(any(policy["live_capabilities"].values()))
        self.assertTrue(policy["test_data"]["synthetic_only"])
        self.assertFalse(policy["test_data"]["provider_delivery"])
        self.assertFalse(policy["test_data"]["pstn_calls"])

    def test_negative_authorization_matrix_is_complete(self):
        payload = json.loads(
            (ROOT / "tests/security/negative-authorization-matrix.json").read_text()
        )
        scenario_ids = {item["id"] for item in payload["scenarios"]}
        self.assertEqual(len(scenario_ids), 10)
        self.assertTrue(all(item["expected"] == "deny" for item in payload["scenarios"]))

    def test_api_inventory_remains_uncertified_without_runtime_evidence(self):
        payload = json.loads(
            (ROOT / "tests/contracts/canonical-endpoints.json").read_text()
        )
        self.assertEqual(payload["certification_status"], "blocked-runtime-evidence")
        self.assertTrue(
            all(
                item["certification_status"] == "blocked-runtime-evidence"
                for item in payload["endpoints"]
            )
        )

    def test_controller_inventory_rejects_no_authenticated_service_route(self):
        with (ROOT / "docs/reconciliation/ODOO-ENDPOINT-INVENTORY.csv").open(
            newline="", encoding="utf-8"
        ) as handle:
            rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 72)
        self.assertFalse(
            [row for row in rows if row["status"].startswith("REJECT")]
        )
        self.assertEqual(
            [row["path"] for row in rows if row["status"] == "RETIRED"],
            ["/codestra/integration/v1/results"],
        )
        unauthenticated_mutations = [
            row
            for row in rows
            if row["auth"] in {"none", "public"}
            and set(row["method"].split(";"))
            & {"POST", "PUT", "PATCH", "DELETE", "ANY"}
            and row["status"] != "RETIRED"
        ]
        self.assertFalse(unauthenticated_mutations)

    def test_upstream_sync_compilation_cannot_mutate_promoted_addon_trees(self):
        workflow = (
            ROOT / ".github/workflows/sync-codestra-odoo-addons.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'export PYTHONPYCACHEPREFIX="${RUNNER_TEMP}/destination-python-cache"',
            workflow,
        )

    def test_runtime_ci_passwords_cannot_be_parsed_as_cli_options(self):
        runner = (ROOT / "scripts/run_odoo_module_tests.sh").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("token_urlsafe", runner)
        self.assertGreaterEqual(runner.count("secrets.token_hex("), 2)


if __name__ == "__main__":
    unittest.main()
