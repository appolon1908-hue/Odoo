from psycopg2.errors import UniqueViolation

from odoo.tests.common import TransactionCase


class TestLeadReconciliation(TransactionCase):
    def test_shared_phone_is_allowed_but_mapping_is_unique(self):
        first = self.env["res.partner"].create({"name": "One"})
        second = self.env["res.partner"].create({"name": "Two"})
        endpoint = self.env["vicidial.phone.endpoint"]
        endpoint.create({"partner_id": first.id, "raw_number": "+15551234567", "normalised_number": "+15551234567"})
        endpoint.create({"partner_id": second.id, "raw_number": "+1 555 123 4567", "normalised_number": "+15551234567"})
        mapping = self.env["vicidial.identity.map"]
        values = {
            "environment_id": "test",
            "connector_id": "c1",
            "odoo_model": "res.partner",
            "odoo_record_id": first.id,
            "external_entity_type": "lead",
            "external_id": "101",
        }
        mapping.create(values)
        with self.assertRaises(UniqueViolation), self.cr.savepoint():
            mapping.create(dict(values, external_id="102"))

    def test_review_resolution_is_audited(self):
        issue = self.env["vicidial.reconciliation.issue"].create(
            {"name": "Phone ambiguity", "connector_id": "c1", "issue_type": "phone_conflict", "evidence_json": "{}"}
        )
        issue.write({"status": "left_separate", "resolution_note": "Shared office number"})
        audit = self.env["codestra.integration.audit"].search(
            [("model_name", "=", issue._name), ("record_res_id", "=", issue.id)]
        )
        self.assertTrue(audit)
