import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AdditionalAddonReviewTests(unittest.TestCase):
    def setUp(self):
        self.validator = load('validate_integration_boundary')
        self.document = json.loads((ROOT / 'config/canonical-addon-baseline.json').read_text())

    def validate(self, document):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'registry.json'
            path.write_text(json.dumps(document))
            errors = []
            with patch.object(self.validator, 'BASELINE', path):
                result = self.validator.load_review_registry(errors)
            return errors, result

    def test_additional_review_is_exact_tree_and_path_scoped(self):
        errors, (_, overrides, exceptions) = self.validate(self.document)
        self.assertEqual(errors, [])
        self.assertIn('codestra_kyqra_review_hub', overrides)
        self.assertEqual(set(exceptions['codestra_kyqra_review_hub']), {'models/kyqra_data.py'})
        self.assertEqual(self.document['module_count'], 33)
        self.assertEqual(len(self.document['modules']) + len(self.document['strict_mission_overrides']), 33)

    def test_changed_subtree_invalidates_the_exception(self):
        self.document['additional_strict_overrides']['codestra_kyqra_review_hub']['current_tree'] = '0' * 40
        errors, (_, overrides, _) = self.validate(self.document)
        self.assertTrue(any('exact current tree' in error for error in errors))
        self.assertNotIn('codestra_kyqra_review_hub', overrides)

    def test_additional_review_cannot_replace_canonical_authority(self):
        self.document['additional_strict_overrides']['call_center_campaign'] = self.document['strict_mission_overrides']['call_center_campaign']
        errors, _ = self.validate(self.document)
        self.assertIn('additional overrides cannot replace canonical registry entries', errors)
