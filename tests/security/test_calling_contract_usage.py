"""Offline regressions for the calling-contract usage drift gate."""

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/validate_calling_contract_usage.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "_calling_contract_usage_under_test", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


usage = _load_module()


class CallingContractUsageTest(unittest.TestCase):
    """The gate must accept the committed state and reject every drift shape."""

    @classmethod
    def setUpClass(cls):
        cls.document, cls.paths, cls.families, cls.lock = usage.load()
        cls.source_endpoints, cls.source_families = usage.scan_source()

    def _validate(self, document=None, endpoints=None, families=None, lock=None):
        usage.validate(
            self.document if document is None else document,
            self.paths,
            self.families,
            self.lock if lock is None else lock,
            self.source_endpoints if endpoints is None else endpoints,
            self.source_families if families is None else families,
        )

    def _mutated(self):
        return copy.deepcopy(self.document)

    def test_committed_declaration_matches_authority_and_source(self):
        self._validate()

    def test_self_test_passes(self):
        usage.self_test()

    def test_contract_exposes_the_canonical_command_surface(self):
        # Guards against a contract refresh that silently drops the envelope the
        # migration in appolon1908-hue/Odoo#75 targets.
        self.assertIn("/v1/telephony/commands", self.paths)
        self.assertIn("/v1/telephony/operations/{operation_id}", self.paths)
        self.assertIn("telephony.call.originate.v1", self.families)

    def test_legacy_route_is_declared_and_absent_from_the_authority(self):
        legacy = "/v1/telephony/calls/originate"
        declared = {e["path"]: e for e in self.document["endpoints"]}
        self.assertEqual(declared[legacy]["status"], usage.LEGACY_STATUS)
        self.assertNotIn(legacy, self.paths)
        self.assertIn(legacy, self.source_endpoints)

    def test_undeclared_source_endpoint_is_rejected(self):
        with self.assertRaises(usage.UsageError):
            self._validate(endpoints=self.source_endpoints | {"/v1/telephony/sneaky"})

    def test_undeclared_source_family_is_rejected(self):
        with self.assertRaises(usage.UsageError):
            self._validate(families=self.source_families | {"telephony.call.x.v1"})

    def test_lock_digest_drift_is_rejected(self):
        lock = dict(self.lock)
        lock["sha256"] = "0" * 64
        with self.assertRaises(usage.UsageError):
            self._validate(lock=lock)

    def test_lock_version_drift_is_rejected(self):
        lock = dict(self.lock)
        lock["version"] = "9.9.9"
        with self.assertRaises(usage.UsageError):
            self._validate(lock=lock)

    def test_canonical_claim_absent_from_authority_is_rejected(self):
        document = self._mutated()
        document["endpoints"].append(
            {
                "path": "/v1/telephony/invented",
                "status": "in_use",
                "reason": "A canonical claim for a route the authority never defines.",
            }
        )
        with self.assertRaises(usage.UsageError):
            self._validate(document=document)

    def test_legacy_claim_present_in_authority_is_rejected(self):
        document = self._mutated()
        document["endpoints"].append(
            {
                "path": "/v1/telephony/commands",
                "status": usage.LEGACY_STATUS,
                "reason": "Calling the canonical command envelope legacy debt is wrong.",
                "tracking": "appolon1908-hue/Odoo#75",
            }
        )
        with self.assertRaises(usage.UsageError):
            self._validate(document=document)

    def test_legacy_entry_requires_a_tracking_reference(self):
        document = self._mutated()
        for entry in document["endpoints"]:
            if entry["status"] == usage.LEGACY_STATUS:
                del entry["tracking"]
        with self.assertRaises(usage.UsageError):
            self._validate(document=document)

    def test_malformed_tracking_reference_is_rejected(self):
        document = self._mutated()
        for entry in document["endpoints"]:
            if entry["status"] == usage.LEGACY_STATUS:
                entry["tracking"] = "issue 75"
        with self.assertRaises(usage.UsageError):
            self._validate(document=document)

    def test_canonical_entry_may_not_carry_tracking(self):
        document = self._mutated()
        for entry in document["endpoints"]:
            if entry["status"] == "planned":
                entry["tracking"] = "appolon1908-hue/Odoo#75"
                break
        with self.assertRaises(usage.UsageError):
            self._validate(document=document)

    def test_thin_reason_is_rejected(self):
        document = self._mutated()
        document["command_families"][0]["reason"] = "because"
        with self.assertRaises(usage.UsageError):
            self._validate(document=document)

    def test_unsupported_status_is_rejected(self):
        document = self._mutated()
        document["endpoints"][0]["status"] = "probably_fine"
        with self.assertRaises(usage.UsageError):
            self._validate(document=document)

    def test_duplicate_declaration_is_rejected(self):
        document = self._mutated()
        document["command_families"].append(dict(document["command_families"][0]))
        with self.assertRaises(usage.UsageError):
            self._validate(document=document)

    def test_unknown_top_level_field_is_rejected(self):
        document = self._mutated()
        document["extra"] = True
        with self.assertRaises(usage.UsageError):
            self._validate(document=document)

    def test_missing_top_level_field_is_rejected(self):
        document = self._mutated()
        del document["policy"]
        with self.assertRaises(usage.UsageError):
            self._validate(document=document)

    def test_in_use_claim_without_source_backing_is_rejected(self):
        # A declaration may not outlive the code that justified it.
        document = self._mutated()
        for entry in document["endpoints"]:
            if entry["path"] == "/v1/telephony/commands":
                entry["status"] = "in_use"
        with self.assertRaises(usage.UsageError):
            self._validate(document=document)

    def test_endpoint_outside_telephony_scope_is_rejected(self):
        document = self._mutated()
        document["endpoints"].append(
            {
                "path": "/web/login",
                "status": "planned",
                "reason": "An unrelated route has no business in the telephony surface.",
            }
        )
        with self.assertRaises(usage.UsageError):
            self._validate(document=document)

    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaises(usage.UsageError):
            usage.parse_json('{"a": 1, "a": 2}')

    def test_declaration_file_is_valid_json_on_disk(self):
        json.loads((ROOT / "config/calling-contract-usage.json").read_text("utf-8"))


if __name__ == "__main__":
    unittest.main()
