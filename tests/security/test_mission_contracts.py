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


if __name__ == "__main__":
    unittest.main()
