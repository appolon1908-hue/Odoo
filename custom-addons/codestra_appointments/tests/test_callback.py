from datetime import timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user


class TestAppointmentChildSecurity(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = new_test_user(
            cls.env,
            login="appointment-child-agent@example.invalid",
            groups="codestra.group_agent",
        )
        cls.unit_a = cls.env["call.center.business.unit"].sudo().create({
            "name": "Appointment Security A", "code": "APSEC_A", "brand": "Codestra"
        })
        cls.unit_b = cls.env["call.center.business.unit"].sudo().create({
            "name": "Appointment Security B", "code": "APSEC_B", "brand": "Codestra"
        })
        cls.department_a = cls.env["call.center.department"].sudo().create({
            "name": "Appointment Department A", "code": "APSEC_A",
            "business_unit_id": cls.unit_a.id,
        })
        cls.department_b = cls.env["call.center.department"].sudo().create({
            "name": "Appointment Department B", "code": "APSEC_B",
            "business_unit_id": cls.unit_b.id,
        })
        cls.team_a = cls.env["call.center.team"].sudo().create({
            "name": "Appointment Team A", "code": "APSEC_A",
            "business_unit_id": cls.unit_a.id,
            "department_id": cls.department_a.id,
            "agent_ids": [Command.link(cls.agent.id)],
        })
        cls.team_b = cls.env["call.center.team"].sudo().create({
            "name": "Appointment Team B", "code": "APSEC_B",
            "business_unit_id": cls.unit_b.id,
            "department_id": cls.department_b.id,
        })
        cls.campaign_a = cls.env["call.center.campaign"].sudo().create({
            "name": "Appointment Campaign A", "code": "APSEC_A",
            "business_unit_id": cls.unit_a.id,
            "authorized_user_ids": [Command.link(cls.agent.id)],
        })
        cls.campaign_b = cls.env["call.center.campaign"].sudo().create({
            "name": "Appointment Campaign B", "code": "APSEC_B",
            "business_unit_id": cls.unit_b.id,
        })
        cls.agent.sudo().write({
            "call_center_business_unit_ids": [Command.set(cls.unit_a.ids)],
            "call_center_campaign_ids": [Command.set(cls.campaign_a.ids)],
        })
        type_a = cls.env["codestra.appointment.type"].sudo().create({
            "name": "Appointment Type A", "code": "APSEC_A",
            "business_unit_id": cls.unit_a.id,
        })
        type_b = cls.env["codestra.appointment.type"].sudo().create({
            "name": "Appointment Type B", "code": "APSEC_B",
            "business_unit_id": cls.unit_b.id,
        })
        start = fields.Datetime.now() + timedelta(hours=1)
        base = {
            "title": "Appointment Child Security",
            "agent_id": cls.env.user.id,
            "supervisor_id": cls.env.user.id,
            "scheduled_start": start,
            "scheduled_end": start + timedelta(minutes=30),
            "customer_timezone": "UTC", "agent_timezone": "UTC",
            "campaign_timezone": "UTC", "correlation_id": "APSEC",
        }
        cls.appointment_a = cls.env["codestra.call.appointment"].sudo().create({
            **base, "reference": "APSEC-A", "business_unit_id": cls.unit_a.id,
            "campaign_id": cls.campaign_a.id, "department_id": cls.department_a.id,
            "team_id": cls.team_a.id, "agent_id": cls.agent.id, "type_id": type_a.id,
        })
        cls.appointment_b = cls.env["codestra.call.appointment"].sudo().create({
            **base, "reference": "APSEC-B", "business_unit_id": cls.unit_b.id,
            "campaign_id": cls.campaign_b.id, "department_id": cls.department_b.id,
            "team_id": cls.team_b.id, "type_id": type_b.id,
        })

    def test_child_models_enforce_parent_orm_boundary(self):
        for model_name in (
            "codestra.appointment.preparation.checklist",
            "codestra.appointment.preparation.item",
            "codestra.appointment.acknowledgment",
        ):
            with self.subTest(model=model_name):
                model = self.env[model_name]
                allowed = model.sudo().create({
                    "appointment_id": self.appointment_a.id, "state": "ready",
                    "safe_detail": "authorized", "correlation_id": "APSEC-A",
                })
                denied = model.sudo().create({
                    "appointment_id": self.appointment_b.id, "state": "ready",
                    "safe_detail": "denied", "correlation_id": "APSEC-B",
                })
                scoped = model.with_user(self.agent)
                self.assertEqual(scoped.search([("id", "in", (allowed.id, denied.id))]), allowed)
                self.assertFalse(scoped.name_search("", [("id", "=", denied.id)]))
                grouped = scoped.read_group(
                    [("id", "=", denied.id)], ["id:count"], []
                )
                self.assertEqual(sum(row.get("__count", 0) for row in grouped), 0)
                with self.assertRaises(AccessError):
                    denied.with_user(self.agent).read(["state"])
                with self.assertRaises(UserError):
                    denied.with_user(self.agent).export_data(["state"])
                with self.assertRaises(AccessError):
                    denied.with_user(self.agent).write({"state": "changed"})
                with self.assertRaises(AccessError):
                    denied.with_user(self.agent).unlink()
                with self.assertRaises(AccessError):
                    scoped.create({
                        "appointment_id": self.appointment_b.id, "state": "ready",
                        "correlation_id": "APSEC-DENIED-CREATE",
                    })
                created = scoped.create({
                    "appointment_id": self.appointment_a.id, "state": "ready",
                    "correlation_id": "APSEC-ALLOWED-CREATE",
                })
                self.assertTrue(created)


class TestCallbackState(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env["call.center.business.unit"].sudo().with_context(active_test=False).search(
            [("code", "=", "COD")], limit=1
        )
        if not cls.unit:
            cls.unit = cls.env["call.center.business.unit"].sudo().create({
                "name": "COD Synthetic Tests", "code": "COD", "brand": "Codestra"
            })
        cls.campaign = cls.env["call.center.campaign"].sudo().with_context(active_test=False).search([
            ("code", "=", "TEST_SYN")
        ], limit=1)
        if not cls.campaign:
            cls.campaign = cls.env["call.center.campaign"].sudo().create({
                "name": "Callback Synthetic Tests",
                "code": "TEST_SYN",
                "business_unit_id": cls.unit.id,
            })
        elif cls.campaign.business_unit_id != cls.unit:
            # Production clones can already contain an inactive fixture under a
            # test tenant. Rebind it only inside this rolled-back test transaction.
            cls.env.cr.execute(
                "UPDATE call_center_campaign SET business_unit_id = %s WHERE id = %s",
                (cls.unit.id, cls.campaign.id),
            )
            cls.campaign.invalidate_recordset(["business_unit_id"])

    def _callback(self, **values):
        payload = {
            "business_unit_id": self.unit.id,
            "campaign_id": self.campaign.id,
            "assigned_agent_id": self.env.user.id,
            "phone_number": "+15555550199",
            "normalized_phone": "+15555550199",
            "scheduled_at": fields.Datetime.now() + timedelta(hours=1),
            "customer_timezone": "UTC",
            "reason": "TEST_SYN callback contract",
            "correlation_id": "TEST-SYN-CORRELATION",
            "idempotency_key": "TEST-SYN-IDEMPOTENCY-%s" % fields.Datetime.now(),
            "compliance_allowed": True,
            "compliance_evidence": {
                "consent": True,
                "within_calling_hours": True,
                "campaign_allowed": True,
            },
        }
        payload.update(values)
        return self.env["codestra.callback"].create(payload)

    def test_terminal_transition_rejected(self):
        callback = self._callback(state="completed")
        with self.assertRaises(ValidationError):
            callback.action_transition("due", "TEST-SYN-CORRELATION")

    def test_callback_can_precede_a_telephony_call(self):
        callback = self._callback()
        self.assertFalse(callback.call_id)
        self.assertFalse(callback.lead_id)
        self.assertEqual(callback.campaign_id, self.campaign)
        self.assertFalse(callback.vicidial_campaign_id)
        self.assertEqual(callback.owner_id, self.env.user)

    def test_calendar_reminder_and_scheduler_popout_actions(self):
        appointment_action = self.env.ref("codestra_appointments.appointment_action")
        reminder_action = self.env.ref("codestra_appointments.reminder_event_action")
        callback_action = self.env.ref("codestra_appointments.callback_action")
        self.assertEqual(appointment_action.res_model, "codestra.call.appointment")
        self.assertEqual(appointment_action.view_mode, "calendar,list,form")
        self.assertEqual(reminder_action.res_model, "codestra.appointment.reminder.event")
        self.assertEqual(callback_action.view_mode, "calendar,list,form")
        appointment_calendar = self.env.ref("codestra_appointments.appointment_calendar")
        callback_calendar = self.env.ref("codestra_appointments.callback_calendar")
        self.assertIn('date_start="scheduled_start"', appointment_calendar.arch_db)
        self.assertIn('date_start="scheduled_at"', callback_calendar.arch_db)

    def test_appointment_child_models_are_parent_scoped(self):
        rule_ids = (
            "appointment_checklist_agent_scope_rule",
            "appointment_item_agent_scope_rule",
            "appointment_ack_agent_scope_rule",
            "appointment_checklist_supervisor_scope_rule",
            "appointment_item_supervisor_scope_rule",
            "appointment_ack_supervisor_scope_rule",
            "appointment_escalation_supervisor_scope_rule",
            "appointment_telephony_supervisor_scope_rule",
            "appointment_audit_supervisor_scope_rule",
            "appointment_metric_supervisor_scope_rule",
        )
        for xmlid in rule_ids:
            rule = self.env.ref("codestra_appointments.%s" % xmlid)
            with self.subTest(rule=xmlid):
                self.assertTrue(rule.active)
                self.assertIn("appointment_id.business_unit_id", rule.domain_force)

    def test_legacy_callback_completion_enqueues_middleware_completion(self):
        legacy_campaign = self.env["codestra.vicidial.campaign"].search(
            [("campaign_id", "=", "TEST_SYN")], limit=1
        ) or self.env["codestra.vicidial.campaign"].create(
            {"name": "Synthetic Callback Campaign", "campaign_id": "TEST_SYN", "mode": "test"}
        )
        callback = self._callback(
            state="scheduled",
            status="scheduled",
            vicidial_campaign_id=legacy_campaign.id,
            middleware_callback_uuid="018f0000-0000-7000-8000-000000000099",
        )
        with patch.dict("os.environ", {"CODESTRA_CALLBACK_SYNC_ENABLED": "false"}):
            callback.action_complete()
            callback.action_complete()
        jobs = self.env["codestra.callback.sync.job"].search(
            [("callback_id", "=", callback.id)]
        )
        job = jobs.ensure_one()
        self.assertEqual(callback.state, "completed")
        self.assertEqual(job.operation, "completed")
        self.assertEqual(job.state, "pending")
        key = job.idempotency_key
        job.write({"attempt_count": 1})
        job._retry("TimeoutError")
        self.assertEqual(job.state, "pending")
        self.assertEqual(job.idempotency_key, key)
        self.assertEqual(len(self.env["codestra.callback.sync.job"].search(
            [("callback_id", "=", callback.id)]
        )), 1)

    def test_disabled_delivery_still_persists_durable_job(self):
        callback = self._callback()
        with patch.dict("os.environ", {"CODESTRA_CALLBACK_SYNC_ENABLED": "false"}):
            callback.action_schedule()
            processed = self.env["codestra.callback.sync.job"]._cron_process()
        job = self.env["codestra.callback.sync.job"].search([
            ("callback_id", "=", callback.id)
        ]).ensure_one()
        self.assertEqual(job.state, "pending")
        self.assertEqual(processed, 0)

    def test_schedule_enqueues_one_idempotent_create(self):
        callback = self._callback()
        jobs = self.env["codestra.callback.sync.job"]
        with patch.dict("os.environ", {"CODESTRA_CALLBACK_SYNC_ENABLED": "true"}):
            callback.action_schedule()
            first = jobs.search([("callback_id", "=", callback.id)])
            duplicate = jobs._enqueue(callback, "create", callback.correlation_id)
        self.assertEqual(len(first), 1)
        self.assertEqual(first, duplicate)
        self.assertEqual(first.operation, "create")

    def test_configuration_accepts_only_exact_private_keycloak_http(self):
        values = {
            "CODESTRA_CALLBACK_SYNC_ENABLED": "true",
            "CODESTRA_CALLBACK_API_BASE_URL": "https://api.codestra.co/api/v1",
            "CODESTRA_CALLBACK_TOKEN_URL": (
                "http://keycloak:8080/realms/codestra/protocol/openid-connect/token"
            ),
            "CODESTRA_CALLBACK_CLIENT_ID": "codestra-odoo-callback-service",
            "CODESTRA_CALLBACK_CLIENT_SECRET_FILE": "/run/secrets/callback",
            "CODESTRA_CALLBACK_CA_FILE": "/etc/ssl/certs/ca-certificates.crt",
            "CODESTRA_CALLBACK_ALLOWED_TENANT": "COD",
            "CODESTRA_CALLBACK_ALLOWED_CAMPAIGN": "TEST_SYN",
        }
        jobs = self.env["codestra.callback.sync.job"]
        with patch.dict("os.environ", values, clear=True):
            self.assertEqual(jobs._configuration()["token_url"], values["CODESTRA_CALLBACK_TOKEN_URL"])
        values["CODESTRA_CALLBACK_TOKEN_URL"] = "http://auth.example.test:8080/token"
        with patch.dict("os.environ", values, clear=True), self.assertRaises(ValidationError):
            jobs._configuration()
        values["CODESTRA_CALLBACK_TOKEN_URL"] = (
            "http://keycloak:8080/realms/codestra/protocol/openid-connect/token"
        )
        for unsafe in (
            "https://user:secret@api.codestra.co/api/v1",
            "https://api.codestra.co/api/v1?redirect=1",
        ):
            values["CODESTRA_CALLBACK_API_BASE_URL"] = unsafe
            with (
                self.subTest(unsafe=unsafe),
                patch.dict("os.environ", values, clear=True),
                self.assertRaises(ValidationError),
            ):
                jobs._configuration()

    def test_acknowledgement_persists_canonical_identity(self):
        callback = self._callback(state="scheduled", version=2)
        job = self.env["codestra.callback.sync.job"].create({
            "callback_id": callback.id,
            "operation": "create",
            "idempotency_key": "TEST-SYN-ACK",
            "correlation_id": callback.correlation_id,
            "callback_version": callback.version,
        })
        job._apply_result({"id": "018f0000-0000-7000-8000-000000000001",
                           "version": 1, "state": "SCHEDULED"})
        self.assertEqual(callback.middleware_callback_uuid,
                         "018f0000-0000-7000-8000-000000000001")
        self.assertEqual(callback.middleware_version, 1)
        self.assertEqual(callback.middleware_sync_state, "synced")
        self.assertEqual(job.state, "done")

    def test_reconcile_updates_state_once_without_feedback_job(self):
        callback = self._callback(
            state="scheduled", version=2,
            middleware_callback_uuid="018f0000-0000-7000-8000-000000000002",
            middleware_version=1,
        )
        job = self.env["codestra.callback.sync.job"].create({
            "callback_id": callback.id,
            "operation": "reconcile",
            "idempotency_key": "TEST-SYN-RECONCILE",
            "correlation_id": callback.correlation_id,
            "callback_version": callback.version,
        })
        job._apply_result({"id": callback.middleware_callback_uuid,
                           "version": 3, "state": "COMPLETED",
                           "completion_disposition": "SYNTHETIC_COMPLETE",
                           "completion_notes": "Completed without PSTN"})
        self.assertEqual(callback.state, "completed")
        self.assertEqual(callback.middleware_version, 3)
        self.assertEqual(callback.completion_disposition, "SYNTHETIC_COMPLETE")
        self.assertEqual(callback.completion_notes, "Completed without PSTN")
        history = callback.history_ids.filtered(
            lambda row: row.event_type == "callback.reconciled"
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(len(self.env["codestra.callback.sync.job"].search([
            ("callback_id", "=", callback.id)
        ])), 1)

    def test_payload_denies_non_synthetic_campaign(self):
        campaign = self.env["call.center.campaign"].sudo().with_context(active_test=False).search([
            ("business_unit_id", "=", self.unit.id),
            ("id", "!=", self.campaign.id),
        ], limit=1)
        callback = self._callback(campaign_id=campaign.id)
        with self.assertRaises(ValidationError):
            self.env["codestra.callback.sync.job"]._create_payload(callback)
