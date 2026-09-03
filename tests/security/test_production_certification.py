from __future__ import annotations

import hashlib
import importlib.util
import tempfile
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

    def certified_bundle(self, root: Path) -> dict:
        source_sha = "1" * 40
        artifact_digest = "sha256:" + "2" * 64
        evidence = deepcopy(self.template)
        evidence.update(
            template=False,
            release_version="odoo-2026.09.03.1",
            source_sha=source_sha,
            artifact_digest=artifact_digest,
            production_certified=True,
            verdict="GO",
        )
        evidence["producer"] = {
            "repository": "appolon1908-hue/Odoo",
            "workflow": ".github/workflows/odoo-production-evidence.yml",
            "run_id": 12345,
            "run_attempt": 1,
            "head_sha": source_sha,
            "artifact_name": "odoo-production-evidence-12345",
        }
        for name, gate in evidence["gates"].items():
            payload = f"verified evidence for {name}\n".encode()
            path = root / f"{name}.txt"
            path.write_bytes(payload)
            gate.update(
                status="PASS",
                source_sha=source_sha,
                artifact_digest=artifact_digest,
                evidence_refs=[
                    {
                        "reference": path.name,
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                ],
            )
        return evidence

    def validate_certified(self, evidence: dict, root: Path) -> list[str]:
        return certification.validate_evidence(
            evidence,
            self.required,
            "1" * 40,
            assert_certified=True,
            evidence_root=root,
            expected_run_id=12345,
            expected_run_attempt=1,
            expected_workflow=".github/workflows/odoo-production-evidence.yml",
            expected_artifact="odoo-production-evidence-12345",
        )

    def test_policy_is_valid_and_defaults_no_go(self) -> None:
        self.assertEqual(certification.validate_policy(self.policy), [])
        self.assertFalse(self.policy["production_certified"])
        self.assertEqual(self.policy["default_verdict"], "NO_GO")

    def test_template_is_structurally_valid_but_not_certified(self) -> None:
        errors = certification.validate_evidence(
            self.template,
            self.required,
            "0" * 40,
        )
        self.assertEqual(errors, [])
        self.assertFalse(self.template["production_certified"])
        self.assertEqual(self.template["verdict"], "NO_GO")

    def test_forged_pass_labels_do_not_certify_template_evidence(self) -> None:
        evidence = deepcopy(self.template)
        for gate in evidence["gates"].values():
            gate["status"] = "PASS"
        evidence["production_certified"] = True
        evidence["verdict"] = "GO"
        errors = certification.validate_evidence(
            evidence,
            self.required,
            "0" * 40,
            assert_certified=True,
            evidence_root=Path(tempfile.gettempdir()),
        )
        self.assertTrue(any("template to false" in error for error in errors))
        self.assertTrue(any("zero source SHA" in error for error in errors))
        self.assertTrue(any("zero artifact digest" in error for error in errors))
        self.assertTrue(any("zero SHA-256" in error for error in errors))

    def test_materialized_external_evidence_can_certify(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = self.certified_bundle(root)
            self.assertEqual(self.validate_certified(evidence, root), [])

    def test_reference_hash_must_match_materialized_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = self.certified_bundle(root)
            evidence["gates"]["rollback"]["evidence_refs"][0]["sha256"] = "f" * 64
            errors = self.validate_certified(evidence, root)
            self.assertTrue(any("does not match materialized" in error for error in errors))

    def test_reference_must_not_escape_artifact_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = self.certified_bundle(root)
            evidence["gates"]["rollback"]["evidence_refs"][0]["reference"] = "../outside"
            errors = self.validate_certified(evidence, root)
            self.assertTrue(any("must remain inside" in error for error in errors))

    def test_external_run_identity_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = self.certified_bundle(root)
            evidence["producer"]["run_id"] = 99999
            errors = self.validate_certified(evidence, root)
            self.assertTrue(any("producer.run_id does not match" in error for error in errors))

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
        self.assertTrue(any("source_ci.source_sha must match" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
