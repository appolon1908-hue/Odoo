from __future__ import annotations

import importlib.util
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "validate_production_certification.py"
POLICY = ROOT / "config" / "production-certification.v1.json"
TEMPLATE = ROOT / "evidence" / "production" / "production-evidence.template.json"

spec = importlib.util.spec_from_file_location("production_certification", SCRIPT)
assert spec and spec.loader
certification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(certification)


class TestProductionCertification(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = certification.load_json(POLICY)
        self.template = certification.load_json(TEMPLATE)
        self.required = set(self.policy["required_gates"])

    def test_policy_is_valid_and_defaults_no_go(self) -> None:
        self.assertEqual(certification.validate_policy(self.policy), [])
        self.assertFalse(self.policy["production_certified"])
        self.assertEqual(self.policy["default_verdict"], "NO_GO")

    def test_template_is_well_formed_but_not_certified(self) -> None:
        errors = certification.validate_evidence(
            self.template,
            self.required,
            "0" * 40,
        )
        self.assertEqual(errors, [])
        self.assertFalse(self.template["production_certified"])
        self.assertEqual(self.template["verdict"], "NO_GO")

    def test_single_blocked_gate_cannot_claim_go(self) -> None:
        evidence = deepcopy(self.template)
        for gate in evidence["gates"].values():
            gate["status"] = "PASS"
        evidence["gates"]["rollback"]["status"] = "BLOCKED"
        evidence["production_certified"] = True
        evidence["verdict"] = "GO"
        errors = certification.validate_evidence(evidence, self.required, "0" * 40)
        self.assertTrue(
            any("cannot be true unless every gate is PASS" in error for error in errors)
        )

    def test_gate_binding_must_match_release_identity(self) -> None:
        evidence = deepcopy(self.template)
        evidence["gates"]["source_ci"]["source_sha"] = "1" * 40
        errors = certification.validate_evidence(evidence, self.required, "0" * 40)
        self.assertTrue(
            any("source_ci.source_sha must match" in error for error in errors)
        )


if __name__ == "__main__":
    unittest.main()
