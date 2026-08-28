from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestOrchestration(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env.ref("call_center_core.business_unit_test")
        cls.department = cls.env["call.center.department"].create({
            "name": "Synthetic SDR", "code": "X1-SDR",
            "business_unit_id": cls.unit.id,
        })
        agent_group = cls.env.ref("call_center_core.group_call_center_agent")
        supervisor_group = cls.env.ref(
            "call_center_core.group_call_center_supervisor"
        )
        cls.agent = cls.env["res.users"].create({
            "name": "Synthetic Agent", "login": "synthetic-agent@example.invalid",
            "group_ids": [(6, 0, agent_group.ids)],
        })
        cls.agent.call_center_business_unit_ids = cls.unit
        cls.supervisor = cls.env["res.users"].create({
            "name": "Synthetic Supervisor",
            "login": "synthetic-supervisor@example.invalid",
            "group_ids": [(6, 0, supervisor_group.ids)],
        })
        cls.supervisor.call_center_business_unit_ids = cls.unit
        cls.team = cls.env["call.center.team"].create({
            "name": "Synthetic Team", "business_unit_id": cls.unit.id,
            "department_id": cls.department.id,
            "agent_ids": [(6, 0, cls.agent.ids)],
            "supervisor_ids": [(6, 0, cls.supervisor.ids)],
        })
        cls.campaign = cls.env["call.center.campaign"].create({
            "name": "Synthetic Campaign", "code": "X1-AUTO",
            "business_unit_id": cls.unit.id, "campaign_type": "sales",
            "direction": "outbound", "timezone": "UTC",
            "default_list_reference": "STAGING_LIST_X1",
        })

    def test_hierarchy_and_provisioning_queue(self):
        request = self.env["call.center.provisioning.request"].create({
            "request_uid": "x1-provision-1", "business_unit_id": self.unit.id,
            "user_id": self.agent.id, "department_id": self.department.id,
            "team_id": self.team.id, "supervisor_id": self.supervisor.id,
            "campaign_ids": [(6, 0, self.campaign.ids)],
            "requested_roles": "agent", "state": "approved",
            "correlation_id": "x1-corr-1", "idempotency_key_hash": "a" * 64,
            "expires_at": fields.Datetime.now() + timedelta(hours=1),
        })
        request.action_queue()
        self.assertEqual(request.state, "queued")
        self.assertEqual(self.agent.identity_lifecycle_state, "requested")

    def test_credential_reference_rejects_raw_secret_shape(self):
        with self.assertRaises(ValidationError):
            self.env["call.center.credential.reference"].create({
                "provisioning_request_id": self.env[
                    "call.center.provisioning.request"
                ].create({
                    "request_uid": "x1-provision-2",
                    "business_unit_id": self.unit.id, "user_id": self.agent.id,
                    "department_id": self.department.id, "team_id": self.team.id,
                    "supervisor_id": self.supervisor.id,
                    "requested_roles": "agent", "state": "draft",
                    "correlation_id": "x1-corr-2",
                    "idempotency_key_hash": "b" * 64,
                    "expires_at": fields.Datetime.now() + timedelta(hours=1),
                }).id,
                "business_unit_id": self.unit.id,
                "credential_type": "vicidial",
                "vault_reference": "raw password with spaces",
                "fingerprint": "f" * 64,
                "retrieval_token_hash": "c" * 64,
                "expires_at": fields.Datetime.now() + timedelta(minutes=15),
            })

    def test_lead_sync_is_approved_but_delivery_disabled(self):
        lead = self.env["crm.lead"].create({
            "name": "Synthetic Eligible", "business_unit_id": self.unit.id,
            "call_center_campaign_id": self.campaign.id,
            "phone": "+18005550199", "email_from": "lead@example.invalid",
        })
        self.env["call.center.compliance.rule"].create({
            "name": "Synthetic Rule", "business_unit_id": self.unit.id,
            "campaign_id": self.campaign.id, "consent_required": True,
            "calling_hour_start": 0, "calling_hour_end": 24,
        })
        self.env["call.center.consent"].create({
            "business_unit_id": self.unit.id, "lead_id": lead.id,
            "channel": "phone", "status": "granted", "source": "synthetic",
            "evidence_reference": "fixture:x1",
        })
        lead.action_approve_vicidial_sync()
        self.assertEqual(lead.sync_state, "queued_disabled")
        self.assertEqual(lead.vicidial_list_reference, "STAGING_LIST_X1")

    def test_callback_escalation(self):
        lead = self.env["crm.lead"].create({
            "name": "Synthetic Callback", "business_unit_id": self.unit.id,
            "call_center_campaign_id": self.campaign.id,
        })
        callback = self.env["call.center.callback.task"].create({
            "business_unit_id": self.unit.id, "lead_id": lead.id,
            "campaign_id": self.campaign.id, "agent_id": self.agent.id,
            "supervisor_id": self.supervisor.id,
            "due_at": fields.Datetime.now() - timedelta(minutes=1),
            "correlation_id": "x1-callback",
        })
        self.env["call.center.callback.task"]._cron_callback_reminders()
        self.assertEqual(callback.state, "escalated")

    def test_callback_notification_idempotency(self):
        lead = self.env["crm.lead"].create({
            "name": "Synthetic Notice", "business_unit_id": self.unit.id,
            "call_center_campaign_id": self.campaign.id,
        })
        callback = self.env["call.center.callback.task"].create({
            "business_unit_id": self.unit.id, "lead_id": lead.id,
            "campaign_id": self.campaign.id, "agent_id": self.agent.id,
            "supervisor_id": self.supervisor.id,
            "due_at": fields.Datetime.now() + timedelta(hours=24),
            "correlation_id": "x1-notice",
        })
        values = {
            "business_unit_id": self.unit.id, "callback_id": callback.id,
            "notification_type": "before_24h",
            "scheduled_window": callback.due_at - timedelta(hours=24),
            "idempotency_key": f"callback:{callback.id}:before_24h",
            "recipient_role": "agent",
        }
        self.env["call.center.callback.notification"].create(values)
        with self.assertRaises(Exception):
            self.env["call.center.callback.notification"].create(values)

    def test_import_idempotency(self):
        values = {
            "name": "Synthetic CSV", "source_type": "csv",
            "source_reference": "fixture.csv", "source_digest": "d" * 64,
            "campaign_id": self.campaign.id,
            "vicidial_list_reference": "STAGING_LIST_X1",
            "business_unit_id": self.unit.id, "correlation_id": "x1-import",
        }
        self.env["call.center.lead.import.batch"].create(values)
        with self.assertRaises(Exception):
            self.env["call.center.lead.import.batch"].create(values)

    def test_cross_unit_campaign_is_rejected(self):
        foreign_unit = self.env.ref("call_center_core.business_unit_transport")
        foreign_campaign = self.env["call.center.campaign"].create({
            "name": "Foreign Synthetic Campaign", "code": "X1-FOREIGN",
            "business_unit_id": foreign_unit.id, "campaign_type": "sales",
            "direction": "outbound", "timezone": "UTC",
        })
        with self.assertRaises(ValidationError):
            self.env["call.center.provisioning.request"].create({
                "request_uid": "x1-cross-unit",
                "business_unit_id": self.unit.id, "user_id": self.agent.id,
                "department_id": self.department.id, "team_id": self.team.id,
                "supervisor_id": self.supervisor.id,
                "campaign_ids": [(6, 0, foreign_campaign.ids)],
                "requested_roles": "agent", "state": "draft",
                "correlation_id": "x1-cross-unit",
                "idempotency_key_hash": "e" * 64,
                "expires_at": fields.Datetime.now() + timedelta(hours=1),
            })
