from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestCampaignWorkforceWorkflow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["cc.business.unit"]._adopt_legacy_records()
        cls.campaign_a = cls.env["cc.campaign"].search(
            [("code", "=", "COD-WEB-OUT")], limit=1
        )
        cls.campaign_b = cls.env["cc.campaign"].search(
            [("id", "!=", cls.campaign_a.id)], limit=1
        )
        cls.author = cls._create_user(
            "WFM Policy Author",
            "cc-wfm-author@example.invalid",
            ["codestra_cc_security.group_cc_campaign_configuration_manager"],
        )
        cls.approver = cls._create_user(
            "WFM Policy Approver",
            "cc-wfm-approver@example.invalid",
            ["codestra_cc_security.group_cc_global_administrator"],
        )
        cls.identity_service = cls._create_user(
            "WFM Identity Service",
            "cc-wfm-identity@example.invalid",
            ["base.group_user", "codestra_identity_provisioning.group_provisioning_service"],
        )
        cls.event_service = cls._create_user(
            "WFM Event Service",
            "cc-wfm-events@example.invalid",
            ["codestra_cc_wfm.group_cc_workforce_event_service"],
        )
        cls.agent_a = cls._create_user(
            "WFM Agent A",
            "cc-wfm-agent-a@example.invalid",
            ["codestra_cc_security.group_cc_campaign_agent"],
        )
        cls.agent_b = cls._create_user(
            "WFM Agent B",
            "cc-wfm-agent-b@example.invalid",
            ["codestra_cc_security.group_cc_campaign_agent"],
        )
        cls.supervisor_a = cls._create_user(
            "WFM Supervisor A",
            "cc-wfm-supervisor-a@example.invalid",
            ["codestra_cc_security.group_cc_campaign_supervisor"],
        )
        cls.wfm_a = cls._create_user(
            "WFM Analyst A",
            "cc-wfm-a@example.invalid",
            ["codestra_cc_security.group_cc_workforce_analyst"],
        )
        cls.wfm_b = cls._create_user(
            "WFM Analyst B",
            "cc-wfm-b@example.invalid",
            ["codestra_cc_security.group_cc_workforce_analyst"],
        )
        cls.agent_membership_a = cls._activate_membership(
            cls.agent_a, cls.campaign_a, "WFM-AGENT-A", "agent"
        )
        cls.agent_membership_b = cls._activate_membership(
            cls.agent_b, cls.campaign_b, "WFM-AGENT-B", "agent"
        )
        cls.supervisor_membership_a = cls._activate_membership(
            cls.supervisor_a,
            cls.campaign_a,
            "WFM-SUPERVISOR-A",
            "supervisor",
            is_primary_supervisor=True,
        )
        cls.wfm_membership_a = cls._activate_membership(
            cls.wfm_a, cls.campaign_a, "WFM-ANALYST-A", "workforce"
        )
        cls.wfm_membership_b = cls._activate_membership(
            cls.wfm_b, cls.campaign_b, "WFM-ANALYST-B", "workforce"
        )
        cls.policy_a = cls.env["cc.workforce.policy"].with_user(cls.author).create(
            {
                "campaign_id": cls.campaign_a.id,
                "name": "Synthetic Campaign WFM Policy",
                "version": 1,
                "source_reference": "TEST-WFM-POLICY-A",
            }
        )
        cls.policy_a.with_user(cls.author).action_submit()
        cls.policy_a.with_user(cls.approver).action_approve()
        cls.policy_a.with_user(cls.approver).action_activate()

    @classmethod
    def _create_user(cls, name, login, group_xmlids):
        groups = cls.env["res.groups"].browse(
            [cls.env.ref(xmlid).id for xmlid in group_xmlids]
        )
        return cls.env["res.users"].create(
            {"name": name, "login": login, "group_ids": [(6, 0, groups.ids)]}
        )

    @classmethod
    def _activate_membership(
        cls, user, campaign, ticket, role, is_primary_supervisor=False
    ):
        employee = cls.env["hr.employee"].create(
            {"name": user.name, "user_id": user.id, "company_id": cls.env.company.id}
        )
        membership = cls.env["cc.campaign.membership"].with_user(cls.approver).create(
            {
                "user_id": user.id,
                "employee_id": employee.id,
                "campaign_id": campaign.id,
                "role": role,
                "is_primary_supervisor": is_primary_supervisor,
                "requested_by_id": cls.approver.id,
                "source_ticket": ticket,
                "starts_at": fields.Datetime.now(),
            }
        )
        membership.with_user(cls.approver).action_submit_identity()
        operation = membership.with_user(cls.approver).action_approve_identity()
        operation.with_user(cls.identity_service).action_record_readback(
            {
                target: {"status": "matched", "evidence_hash": "a" * 64}
                for target in operation.required_targets
            },
            f"staging://wfm/{ticket.lower()}",
        )
        membership.with_user(cls.approver).action_activate()
        return membership

    def _schedule(self, *, start_offset=0, activity_type="shift", minutes=60):
        start = fields.Datetime.now() + timedelta(minutes=start_offset)
        return self.env["cc.workforce.schedule"].with_user(self.wfm_a).create_schedule(
            self.policy_a.with_user(self.wfm_a),
            self.agent_membership_a.with_user(self.wfm_a),
            start,
            start + timedelta(minutes=minutes),
            activity_type=activity_type,
            break_minutes=0,
            timezone="America/La_Paz",
        )

    def test_dependencies_and_legacy_shift_are_closed(self):
        expected = {"codestra_cc_security", "codestra_cc_calls", "codestra_cc_workforce"}
        modules = self.env["ir.module.module"].search([("name", "in", sorted(expected))])
        self.assertEqual(set(modules.mapped("name")), expected)
        self.assertEqual(set(modules.mapped("state")), {"installed"})
        legacy_acl = self.env.ref(
            "codestra_cc_workforce.access_codestra_cc_shift_wfm"
        )
        self.assertFalse(
            legacy_acl.perm_read
            or legacy_acl.perm_write
            or legacy_acl.perm_create
            or legacy_acl.perm_unlink
        )

    def test_policy_is_separately_approved_hashed_and_immutable(self):
        self.assertEqual(self.policy_a.state, "active")
        self.assertEqual(len(self.policy_a.policy_hash), 64)
        self.assertNotEqual(self.policy_a.author_id, self.policy_a.approver_id)
        self.assertEqual(self.policy_a.asa_target_seconds, 20.0)
        self.assertEqual(self.policy_a.adherence_target_percent, 90.0)
        with self.assertRaises(AccessError):
            self.policy_a.with_user(self.author).write({"asa_target_seconds": 99.0})

    def test_forecast_calculates_staffing_and_finalizes_immutable_evidence(self):
        start = fields.Datetime.now()
        forecast = self.env["cc.workforce.forecast"].with_user(
            self.wfm_a
        ).create_forecast(
            self.policy_a.with_user(self.wfm_a),
            start,
            start + timedelta(minutes=30),
            "voice",
            "WEB",
            30,
            300,
            20.0,
        )
        self.assertGreater(forecast.required_staff, 0)
        forecast.with_user(self.wfm_a).action_finalize()
        self.assertEqual(forecast.state, "finalized")
        self.assertEqual(len(forecast.forecast_hash), 64)
        with self.assertRaises(AccessError):
            forecast.with_user(self.wfm_a).write({"required_staff": 999})

    def test_schedule_publication_acknowledgement_and_campaign_isolation(self):
        schedule = self._schedule()
        schedule.with_user(self.wfm_a).action_publish()
        schedule.with_user(self.agent_a).action_acknowledge()
        self.assertEqual(schedule.state, "acknowledged")
        self.assertEqual(len(schedule.schedule_hash), 64)
        self.assertEqual(
            self.env["cc.workforce.schedule"].with_user(self.agent_a).search([]),
            schedule,
        )
        self.assertFalse(
            self.env["cc.workforce.schedule"].with_user(self.agent_b).search([])
        )
        schedule.with_user(self.supervisor_a).action_complete()
        self.assertEqual(schedule.state, "completed")

    def test_cross_campaign_schedule_assignment_is_rejected_before_create(self):
        start = fields.Datetime.now()
        with self.assertRaises(Exception) as caught:
            self.env["cc.workforce.schedule"].with_user(self.supervisor_a).create_schedule(
                self.policy_a.with_user(self.supervisor_a),
                self.agent_membership_b.with_user(self.supervisor_a),
                start,
                start + timedelta(hours=1),
            )
        self.assertIsInstance(caught.exception, (AccessError, ValidationError))

    def test_adherence_event_is_idempotent_and_opens_supervisor_exception(self):
        schedule = self._schedule()
        schedule.with_user(self.wfm_a).action_publish()
        occurred_start = schedule.start_at + timedelta(minutes=10)
        values = {
            "event_uuid": "wfm-adherence-event-001",
            "schedule_id": schedule.id,
            "agent_membership_id": self.agent_membership_a.id,
            "normalized_state": "ready",
            "occurred_start": occurred_start,
            "occurred_end": occurred_start + timedelta(minutes=10),
            "source_reference": "synthetic-vicidial-state-001",
            "source_payload_hash": "b" * 64,
        }
        event = self.env["cc.workforce.adherence.event"].with_user(
            self.event_service
        ).ingest_event(**values)
        replay = self.env["cc.workforce.adherence.event"].with_user(
            self.event_service
        ).ingest_event(**values)
        self.assertEqual(event, replay)
        self.assertEqual(event.classification, "late")
        exception = self.env["cc.workforce.exception"].search(
            [("adherence_event_id", "=", event.id)]
        )
        self.assertEqual(exception.state, "open")
        with self.assertRaises(ValidationError):
            self.env["cc.workforce.adherence.event"].with_user(
                self.event_service
            ).ingest_event(**{**values, "source_payload_hash": "c" * 64})

    def test_exception_timeline_requires_primary_supervisor_and_is_immutable(self):
        schedule = self._schedule(start_offset=120, activity_type="training")
        schedule.with_user(self.wfm_a).action_publish()
        event = self.env["cc.workforce.adherence.event"].with_user(
            self.event_service
        ).ingest_event(
            event_uuid="wfm-adherence-event-002",
            schedule_id=schedule.id,
            agent_membership_id=self.agent_membership_a.id,
            normalized_state="offline",
            occurred_start=schedule.start_at,
            occurred_end=schedule.start_at + timedelta(minutes=15),
            source_reference="synthetic-vicidial-state-002",
            source_payload_hash="d" * 64,
        )
        exception = event.exception_id
        exception.with_user(self.supervisor_a).action_acknowledge("ABSENCE-REVIEW")
        exception.with_user(self.supervisor_a).action_resolve("Synthetic absence reviewed")
        self.assertEqual(exception.state, "resolved")
        self.assertEqual(exception.event_ids.mapped("event_type"), [
            "opened",
            "acknowledged",
            "resolved",
        ])
        with self.assertRaises(AccessError):
            exception.event_ids[0].unlink()

    def test_realtime_snapshot_derives_metrics_alerts_and_rejects_replay_drift(self):
        metrics = {
            "offered": 100,
            "answered": 80,
            "abandoned": 20,
            "answer_wait_seconds": 2400,
            "ready_seconds": 1200,
            "talk_seconds": 3600,
            "hold_seconds": 300,
            "acw_seconds": 600,
            "scheduled_staff": 10,
            "actual_staff": 8,
            "callback_backlog": 12,
            "email_backlog": 5,
            "ticket_backlog": 7,
        }
        start = fields.Datetime.now()
        values = {
            "event_uuid": "wfm-realtime-snapshot-001",
            "policy_id": self.policy_a.id,
            "interval_start": start,
            "interval_end": start + timedelta(minutes=30),
            "metrics": metrics,
            "integration_health": "healthy",
            "source_payload_hash": "e" * 64,
        }
        snapshot = self.env["cc.workforce.realtime.snapshot"].with_user(
            self.event_service
        ).ingest_snapshot(**values)
        self.assertEqual(snapshot.asa_seconds, 30.0)
        self.assertEqual(snapshot.abandon_percent, 20.0)
        self.assertEqual(snapshot.staffing_variance, -2)
        self.assertEqual(snapshot.alert_tier, "critical")
        self.assertFalse(
            {"partner_id", "phone", "email", "recording_id"}.intersection(
                snapshot._fields
            )
        )
        replay = self.env["cc.workforce.realtime.snapshot"].with_user(
            self.event_service
        ).ingest_snapshot(**values)
        self.assertEqual(snapshot, replay)
        with self.assertRaises(ValidationError):
            self.env["cc.workforce.realtime.snapshot"].with_user(
                self.event_service
            ).ingest_snapshot(**{**values, "source_payload_hash": "f" * 64})
