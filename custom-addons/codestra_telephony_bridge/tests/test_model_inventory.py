import ast
from collections import defaultdict
from pathlib import Path

from odoo.tests.common import TransactionCase, tagged


def concrete_model_definitions(repository_root):
    definitions = defaultdict(list)
    for path in repository_root.glob("**/*.py"):
        if ".git" in path.parts or "ci_addons" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            has_inherit = any(
                isinstance(statement, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "_inherit"
                    for target in statement.targets
                )
                for statement in node.body
            )
            for statement in node.body:
                if not isinstance(statement, ast.Assign):
                    continue
                if has_inherit:
                    continue
                if not any(
                    isinstance(target, ast.Name) and target.id == "_name"
                    for target in statement.targets
                ):
                    continue
                if isinstance(statement.value, ast.Constant) and isinstance(
                    statement.value.value, str
                ):
                    definitions[statement.value.value].append(
                        {
                            "source_file": str(path.relative_to(repository_root)),
                            "class_name": node.name,
                            "definition_type": "_name",
                            "addon_name": path.relative_to(repository_root).parts[0],
                        }
                    )
    return definitions


@tagged("post_install", "-at_install")
class TestModelInventory(TransactionCase):
    def test_static_concrete_model_names_are_unique(self):
        repository_root = Path(__file__).resolve().parents[2]
        definitions = concrete_model_definitions(repository_root)
        duplicates = {
            model_name: locations
            for model_name, locations in definitions.items()
            if len(locations) > 1
        }
        self.assertEqual(duplicates, {})

    def test_runtime_registry_keeps_authoritative_models_and_extensions(self):
        expected = {
            "codestra.telephony.desired.state": {
                "observed_vicidial_user_exists",
                "observed_asterisk_endpoint_enabled",
                "observed_registration_status",
                "last_reconciliation_run_id",
            },
            "codestra.telephony.target.mapping": {
                "target_system",
                "mapping_status",
                "observed_state_version",
            },
            "codestra.telephony.transfer.request": {
                "transfer_public_id",
                "transition_ids",
                "callback_task_id",
            },
            "codestra.integration.result.inbox": {
                "result_domain",
                "application_status",
                "command_public_id",
                "readback_hash",
            },
        }
        for model_name, required_fields in expected.items():
            model = self.env[model_name]
            self.assertTrue(required_fields.issubset(model._fields))
            self.assertEqual(
                self.env["ir.model"].sudo().search_count(
                    [("model", "=", model_name)]
                ),
                1,
            )
            self.assertTrue(model._table)
        self.assertEqual(
            self.env["ir.rule"].sudo().search_count(
                [("id", "in", [
                    self.env.ref(
                        "codestra_telephony_bridge."
                        "rule_telephony_state_business_unit"
                    ).id,
                    self.env.ref(
                        "codestra_telephony_bridge."
                        "rule_telephony_mapping_business_unit"
                    ).id,
                    self.env.ref(
                        "codestra_telephony_bridge."
                        "rule_telephony_transfer_business_unit"
                    ).id,
                ])]
            ),
            3,
        )
