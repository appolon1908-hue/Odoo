from odoo import fields
from odoo.tests.common import TransactionCase

SCOPED_ACTIONS = (
    "CREATE_LEAD",
    "UPDATE_ALLOWLISTED_FIELDS",
    "ASSIGN_AUTHORIZED_TEAM",
    "ASSIGN_AUTHORIZED_USER",
    "CHANGE_AUTHORIZED_STAGE",
    "CREATE_INTERNAL_CALLBACK_ACTIVITY",
)


class LeadAutomationMultiCompanyIsolationTest(TransactionCase):
    """Exercise the signed company boundary with synthetic records only."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company_model = cls.env["res.company"]
        cls.company_a = company_model.create({"name": "synthetic-logistics-a"})
        cls.company_b = company_model.create({"name": "synthetic-logistics-b"})
        cls.unit_a = cls._unit(cls.company_a, "synthetic-a")
        cls.unit_b = cls._unit(cls.company_b, "synthetic-b")
        cls.campaign_a = cls._campaign(cls.company_a, cls.unit_a, "SYNTHETIC_A")
        cls.campaign_b = cls._campaign(cls.company_b, cls.unit_b, "SYNTHETIC_B")
        cls._authorize(cls.company_a, cls.unit_a, cls.campaign_a)
        cls._authorize(cls.company_b, cls.unit_b, cls.campaign_b)
        cls.lead_a = cls._lead(cls.company_a, cls.unit_a, cls.campaign_a, "LEAD-synthetic-a")
        cls.lead_b = cls._lead(cls.company_b, cls.unit_b, cls.campaign_b, "LEAD-synthetic-b")
        cls.receipts = cls.env["codestra.lead.automation.receipt"]

    @classmethod
    def _unit(cls, company, code):
        return cls.env["call.center.business.unit"].with_company(company).create({
            "name": code,
            "code": code,
            "company_id": company.id,
            "default_currency_id": company.currency_id.id,
            "default_language_id": cls.env.ref("base.lang_en").id,
        })

    @classmethod
    def _campaign(cls, company, unit, code):
        return cls.env["call.center.campaign"].with_company(company).create({
            "name": code,
            "code": code,
            "business_unit_id": unit.id,
            "currency_id": company.currency_id.id,
        })

    @classmethod
    def _authorize(cls, company, unit, campaign):
        scoped = cls.env["codestra.lead.automation.config"].with_company(company)
        scoped.create({
            "environment": "test",
            "business_unit_id": unit.id,
            "campaign_id": campaign.id,
            "enabled": True,
        })
        policy_model = cls.env["codestra.lead.automation.policy"].with_company(company)
        for action in SCOPED_ACTIONS:
            policy_model.create({
                "name": f"Synthetic company policy: {action}",
                "environment": "test",
                "business_unit_id": unit.id,
                "campaign_id": campaign.id,
                "policy_version": "synthetic-v1",
                "action": action,
                "channel": "internal",
                "purpose": "LEAD_SERVICE",
                "decision": "ALLOW",
                "effective_from": fields.Datetime.now(),
                "approved_by_public_id": "USER-synthetic-security-reviewer",
                "approval_reference": "TEST-multicompany",
                "active": True,
            })

    @classmethod
    def _lead(cls, company, unit, campaign, uid):
        return cls.env["crm.lead"].with_company(company).create({
            "name": uid,
            "company_id": company.id,
            "business_unit_id": unit.id,
            "call_center_campaign_id": campaign.id,
            "codestra_lead_uid": uid,
        })

    def _body(self, company, unit, campaign, lead):
        return {
            "contract_version": "1.1",
            "automation_event_id": "LAE-synthetic-company-test",
            "idempotency_key": "a" * 64,
            "environment": "test",
            "company_key": f"COMPANY-{company.id}",
            "business_unit_key": unit.code,
            "campaign_key": campaign.code,
            "automation_action": "UPDATE_ALLOWLISTED_FIELDS",
            "policy_version": "synthetic-v1",
            "correlation_id": "00000000-0000-4000-8000-000000000001",
            "attributes_schema_key": "web-mobile-ai-lead-v1",
            "attributes": {"solution_type": "AI"},
            "consent_snapshot": {
                "consent_status": "granted",
                "consent_purpose": "LEAD_SERVICE",
                "consent_source": "odoo",
                "consent_updated_at": "2026-01-01T00:00:00Z",
                "dnc_status": False,
                "dnc_updated_at": "2026-01-01T00:00:00Z",
                "jurisdiction": "DO",
                "source_system": "odoo",
            },
            "workflow_execution_id": "N8N-synthetic-company-test",
            "result_code": "NO_CHANGE",
            "lead_uid": lead.codestra_lead_uid,
        }

    def _apply(self, body, suffix):
        return self.receipts.apply_authorized(body, "test", suffix * 64, suffix * 64)

    def test_same_company_operation_succeeds(self):
        ack = self._apply(self._body(self.company_a, self.unit_a, self.campaign_a, self.lead_a), "a")
        self.assertEqual(ack["result"], "NO_CHANGE")
        self.assertEqual(ack["company_key"], f"COMPANY-{self.company_a.id}")

    def test_create_is_restricted_to_synthetic_canary_prefix(self):
        body = self._body(self.company_a, self.unit_a, self.campaign_a, self.lead_a)
        body["automation_action"] = "CREATE_LEAD"
        body["automation_event_id"] = "LAE-synthetic-canary-create"
        body.pop("lead_uid")
        ack = self._apply(body, "f")
        lead = self.env["crm.lead"].browse(ack["odoo_record_id"])
        self.assertEqual(ack["result"], "APPLIED")
        self.assertTrue(lead.name.startswith("ZZ_CDX_SCRAPER_CANARY_"))
        self.assertEqual(
            lead.name,
            "ZZ_CDX_SCRAPER_CANARY_LAE-synthetic-canary-create",
        )

    def test_cross_company_read_write_and_numeric_substitution_are_denied(self):
        before = self.lead_b.write_date
        body = self._body(self.company_a, self.unit_a, self.campaign_a, self.lead_b)
        ack = self._apply(body, "b")
        self.assertEqual(ack["result"], "DENIED")
        self.assertEqual(self.lead_b.write_date, before)
        self.assertFalse(ack["applied_fields"])

    def test_cross_company_assignment_stage_and_callback_are_denied_without_mutation(self):
        protected_fields = ("team_id", "user_id", "stage_id", "write_date")
        before = {name: self.lead_b[name] for name in protected_fields}
        callback_count = self.env["codestra.lead.callback.request"].sudo().search_count([])
        for index, action in enumerate(SCOPED_ACTIONS[1:], start=1):
            body = self._body(self.company_a, self.unit_a, self.campaign_a, self.lead_b)
            body["automation_action"] = action
            body["automation_event_id"] = f"LAE-synthetic-cross-company-{index}"
            body["idempotency_key"] = str(index) * 64
            ack = self._apply(body, format(index, "x"))
            self.assertEqual(ack["result"], "DENIED", action)
            self.assertFalse(ack["applied_fields"], action)
        self.lead_b.invalidate_recordset()
        self.assertEqual(
            {name: self.lead_b[name] for name in protected_fields},
            before,
        )
        self.assertEqual(
            self.env["codestra.lead.callback.request"].sudo().search_count([]),
            callback_count,
        )

    def test_cross_company_campaign_and_business_unit_are_denied(self):
        body = self._body(self.company_a, self.unit_b, self.campaign_b, self.lead_b)
        ack = self._apply(body, "c")
        self.assertEqual(ack["result"], "DENIED")
        self.assertIsNone(ack["odoo_record_id"])

    def test_unknown_company_is_denied_without_mutation(self):
        body = self._body(self.company_a, self.unit_a, self.campaign_a, self.lead_a)
        body["company_key"] = "COMPANY-2147483647"
        ack = self._apply(body, "d")
        self.assertEqual(ack["result"], "DENIED")
        self.assertIsNone(ack["odoo_record_id"])

    def test_signed_company_scope_cannot_be_bypassed_by_scoped_sudo(self):
        before = self.lead_b.write_date
        body = self._body(self.company_a, self.unit_a, self.campaign_a, self.lead_b)
        body["automation_event_id"] = "LAE-synthetic-sudo-boundary"
        ack = self._apply(body, "e")
        self.lead_b.invalidate_recordset()
        self.assertEqual(ack["result"], "DENIED")
        self.assertIsNone(ack["odoo_record_id"])
        self.assertEqual(self.lead_b.write_date, before)
