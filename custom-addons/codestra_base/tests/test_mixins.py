from odoo.tests.common import TransactionCase


class TestMixins(TransactionCase):
    def test_abstract_models_registered(self):
        for name in ("codestra.external.reference.mixin", "codestra.sync.state.mixin", "codestra.correlation.mixin", "codestra.audit.mixin"):
            self.assertIn(name, self.env)

    def test_abstract_mixins_expose_required_fields(self):
        expected = {
            "codestra.external.reference.mixin": {"external_reference", "source_system"},
            "codestra.sync.state.mixin": {"sync_state", "sync_error", "last_sync_at", "sync_version"},
            "codestra.correlation.mixin": {"correlation_id", "idempotency_key"},
            "codestra.audit.mixin": {"audit_note", "audit_source"},
        }
        for model_name, field_names in expected.items():
            model = self.env[model_name]
            self.assertTrue(field_names.issubset(model._fields), f"missing fields on {model_name}")
