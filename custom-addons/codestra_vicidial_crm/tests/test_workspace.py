import uuid

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase


class TestProfessionalCallWorkspace(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent_group = cls.env.ref("codestra_vicidial_crm.group_agent")
        cls.qa_group = cls.env.ref("codestra_vicidial_crm.group_qa")
        cls.internal_group = cls.env.ref("base.group_user")
        cls.agent_user = cls.env["res.users"].create(
            {
                "name": "Workspace Agent",
                "login": "workspace-agent@example.test",
                "keycloak_subject": str(uuid.uuid4()),
                "codestra_tenant_id": "COD",
                "group_ids": [(6, 0, [cls.internal_group.id, cls.agent_group.id])],
            }
        )
        cls.other_tenant_user = cls.env["res.users"].create(
            {
                "name": "Other Tenant Agent",
                "login": "other-tenant-agent@example.test",
                "keycloak_subject": str(uuid.uuid4()),
                "codestra_tenant_id": "OTHER",
                "group_ids": [(6, 0, [cls.internal_group.id, cls.agent_group.id])],
            }
        )
        cls.qa_user = cls.env["res.users"].create(
            {
                "name": "Workspace QA",
                "login": "workspace-qa@example.test",
                "keycloak_subject": str(uuid.uuid4()),
                "codestra_tenant_id": "COD",
                "group_ids": [(6, 0, [cls.internal_group.id, cls.qa_group.id])],
            }
        )
        cls.supervisor_group = cls.env.ref("codestra_vicidial_crm.group_supervisor")
        cls.supervisor_user = cls.env["res.users"].create(
            {
                "name": "Workspace Supervisor",
                "login": "workspace-supervisor@example.test",
                "keycloak_subject": str(uuid.uuid4()),
                "codestra_tenant_id": "COD",
                "group_ids": [(6, 0, [cls.internal_group.id, cls.supervisor_group.id])],
            }
        )
        cls.unassigned_supervisor = cls.env["res.users"].create(
            {
                "name": "Unassigned Supervisor",
                "login": "unassigned-supervisor@example.test",
                "keycloak_subject": str(uuid.uuid4()),
                "codestra_tenant_id": "COD",
                "group_ids": [(6, 0, [cls.internal_group.id, cls.supervisor_group.id])],
            }
        )
        cls.campaign = cls.env["codestra.vicidial.campaign"].search(
            [("campaign_id", "=", "TEST_SYN")], limit=1
        ) or cls.env["codestra.vicidial.campaign"].create(
            {
                "name": "Workspace Test",
                "campaign_id": "TEST_SYN",
                "mode": "test",
            }
        )
        cls.campaign.write({"supervisor_ids": [(4, cls.supervisor_user.id)]})
        cls.agent = cls.env["codestra.vicidial.agent"].create(
            {
                "name": "Workspace Agent",
                "vicidial_user": "WORK6101",
                "tenant_id": "COD",
                "phone_login": "6101",
                "odoo_user_id": cls.agent_user.id,
                "campaign_ids": [(6, 0, [cls.campaign.id])],
            }
        )
        cls.call = cls.env["codestra.vicidial.call"].create(
            {
                "name": "Workspace call",
                "call_id": "workspace-call",
                "uniqueid": "workspace-uid",
                "asterisk_uniqueid": "workspace-uid",
                "linkedid": "workspace-linked",
                "correlation_id": "workspace-correlation",
                "idempotency_key": "workspace-idem",
                "tenant_id": "COD",
                "business_unit_id": "COD",
                "campaign_id": cls.campaign.id,
                "campaign_code": "TEST_SYN",
                "agent_id": cls.agent.id,
                "extension": "6101",
                "vicidial_user": "WORK6101",
                "keycloak_subject": cls.agent_user.keycloak_subject,
                "direction": "inbound",
                "state": "completed",
                "sequence": 4,
            }
        )

    def test_note_autosave_revision_history_and_no_delete(self):
        Note = self.env["codestra.call.note"].with_user(self.agent_user)
        note = Note.create(
            {
                "call_id": self.call.id,
                "body": "First",
                "client_revision": "client-1",
            }
        )
        self.assertEqual(note.revision, 1)
        self.assertEqual(len(note.history_ids), 1)
        note.write({"body": "Second", "client_revision": "client-2"})
        self.assertEqual(note.revision, 2)
        self.assertEqual(len(note.history_ids), 2)
        with self.assertRaises(AccessError):
            note.unlink()

    def test_cross_tenant_note_read_is_denied(self):
        note = (
            self.env["codestra.call.note"]
            .with_user(self.agent_user)
            .create(
                {
                    "call_id": self.call.id,
                    "body": "Tenant secret",
                    "client_revision": "tenant-1",
                }
            )
        )
        self.assertFalse(
            self.env["codestra.call.note"].with_user(self.other_tenant_user).search([("id", "=", note.id)])
        )

    def test_sub_disposition_is_campaign_scoped(self):
        disposition = self.env["codestra.vicidial.disposition"].create(
            {
                "name": "Interested",
                "code": "WORK_INTERESTED",
            }
        )
        child = self.env["codestra.call.sub.disposition"].create(
            {
                "name": "Appointment",
                "code": "APPOINTMENT",
                "parent_id": disposition.id,
                "campaign_ids": [(6, 0, [self.campaign.id])],
                "requires_task": True,
            }
        )
        self.assertIn(self.campaign, child.campaign_ids)
        with self.assertRaises(Exception):
            self.env["codestra.call.sub.disposition"].create(
                {
                    "name": "Duplicate",
                    "code": "APPOINTMENT",
                    "parent_id": disposition.id,
                }
            )

    def test_qa_score_range_and_computed_percentage(self):
        values = {
            name: 5
            for name in (
                "greeting",
                "verification",
                "product_knowledge",
                "compliance",
                "call_control",
                "empathy",
                "closing",
            )
        }
        review = (
            self.env["codestra.call.qa.review"]
            .with_user(self.qa_user)
            .create(
                {
                    "call_id": self.call.id,
                    **values,
                }
            )
        )
        self.assertEqual(review.score, 100)
        with self.assertRaises(ValidationError):
            review.write({"compliance": 6})

    def test_connected_event_populates_authoritative_timestamp(self):
        call = self.call.copy(
            {
                "name": "Connected timestamp",
                "call_id": "workspace-connected",
                "uniqueid": "workspace-connected-uid",
                "asterisk_uniqueid": "workspace-connected-uid",
                "idempotency_key": "workspace-connected-idem",
                "state": "ringing",
                "sequence": 1,
                "keycloak_subject": self.agent_user.keycloak_subject,
            }
        )
        timestamp = fields.Datetime.now()
        result = call.apply_authoritative_event(
            {
                "event_id": "workspace-connected-event",
                "event_type": "call.connected",
                "state": "connected",
                "sequence": 2,
                "timestamp": timestamp,
            }
        )
        self.assertTrue(result["applied"])
        self.assertEqual(call.connected_at, timestamp)
        self.assertEqual(call.answered_at, timestamp)

    def test_supervisor_scope_includes_campaign_evidence_only(self):
        note = (
            self.env["codestra.call.note"]
            .with_user(self.agent_user)
            .create(
                {
                    "call_id": self.call.id,
                    "body": "Scoped note",
                    "client_revision": "scope-note",
                }
            )
        )
        event = self.env["codestra.vicidial.call.event"].create(
            {
                "call_id": self.call.id,
                "event_type": "call.completed",
                "occurred_at": fields.Datetime.now(),
                "idempotency_key": "workspace-scope-event",
                "correlation_id": self.call.correlation_id,
                "sequence": 4,
            }
        )
        self.assertTrue(
            self.env["codestra.vicidial.call"].with_user(self.supervisor_user).search([("id", "=", self.call.id)])
        )
        self.assertTrue(self.env["codestra.call.note"].with_user(self.supervisor_user).search([("id", "=", note.id)]))
        self.assertTrue(
            self.env["codestra.vicidial.call.event"].with_user(self.supervisor_user).search([("id", "=", event.id)])
        )
        self.assertFalse(
            self.env["codestra.vicidial.call"].with_user(self.unassigned_supervisor).search([("id", "=", self.call.id)])
        )
        self.assertFalse(
            self.env["codestra.call.note"].with_user(self.unassigned_supervisor).search([("id", "=", note.id)])
        )

    def test_submitted_qa_is_immutable_and_coaching_ack_is_agent_only(self):
        scores = {
            name: 4
            for name in (
                "greeting",
                "verification",
                "product_knowledge",
                "compliance",
                "call_control",
                "empathy",
                "closing",
            )
        }
        review = (
            self.env["codestra.call.qa.review"]
            .with_user(self.qa_user)
            .create(
                {
                    "call_id": self.call.id,
                    "state": "submitted",
                    **scores,
                }
            )
        )
        with self.assertRaises(AccessError):
            review.with_user(self.qa_user).write({"comment": "Changed after submit"})
        with self.assertRaises(AccessError):
            review.with_user(self.qa_user).unlink()
        coaching = (
            self.env["codestra.call.coaching"]
            .with_user(self.qa_user)
            .create(
                {
                    "name": "Synthetic coaching",
                    "review_id": review.id,
                    "assigned_agent_id": self.agent_user.id,
                    "due_date": fields.Date.today(),
                }
            )
        )
        with self.assertRaises(AccessError):
            coaching.with_user(self.qa_user).action_acknowledge()
        coaching.with_user(self.agent_user).action_acknowledge()
        self.assertEqual(coaching.state, "acknowledged")
        self.assertTrue(coaching.acknowledged_at)

    def test_callback_lifecycle_is_explicit_and_terminal(self):
        lead = self.env["crm.lead"].create({"name": "Callback lead", "phone": "+18095550100"})
        callback = self.env["codestra.callback"].create(
            {
                "name": "Synthetic callback",
                "lead_id": lead.id,
                "owner_id": self.agent_user.id,
                "call_id": self.call.id,
                "tenant_id": "COD",
                "vicidial_campaign_id": self.campaign.id,
                "phone": "+18095550100",
                "scheduled_at": fields.Datetime.add(fields.Datetime.now(), days=1),
                "timezone": "America/Santo_Domingo",
                "reason": "Follow-up",
                "priority": "2",
            }
        )
        rescheduled = fields.Datetime.add(fields.Datetime.now(), days=2)
        callback.action_reschedule(rescheduled)
        self.assertEqual(callback.scheduled_at, rescheduled)
        callback.action_complete()
        self.assertEqual(callback.status, "completed")
        with self.assertRaises(ValidationError):
            callback.action_cancel()

    def test_agent_state_projection_and_wrap_up_start_are_authoritative(self):
        call = self.call.copy(
            {
                "name": "Wrap-up state",
                "call_id": "workspace-wrap-up",
                "uniqueid": "workspace-wrap-up-uid",
                "asterisk_uniqueid": "workspace-wrap-up-uid",
                "idempotency_key": "workspace-wrap-up-idem",
                "state": "connected",
                "sequence": 3,
                "keycloak_subject": self.agent_user.keycloak_subject,
            }
        )
        self.assertEqual(call._workspace_agent_status(), "on_call")
        ended_at = fields.Datetime.now()
        result = call.apply_authoritative_event(
            {
                "event_id": "workspace-wrap-up-ended",
                "event_type": "call.completed",
                "state": "completed",
                "sequence": 4,
                "timestamp": ended_at,
            }
        )
        self.assertTrue(result["applied"])
        self.assertEqual(call.wrap_up_started_at, ended_at)
        self.assertEqual(call._workspace_agent_status(), "wrap_up")
        call.write({"wrap_up_completed_at": fields.Datetime.add(ended_at, seconds=20), "wrap_up_seconds": 20})
        self.agent.status = "lunch"
        self.assertEqual(call._workspace_agent_status(), "lunch")
        self.assertGreaterEqual(self.campaign.wrap_up_timeout_seconds, 0)
