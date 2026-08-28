from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestCampaignReportingWorkflow(TransactionCase):
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
            "Reporting Policy Author",
            "cc-report-author@example.invalid",
            ["codestra_cc_security.group_cc_campaign_configuration_manager"],
        )
        cls.approver = cls._create_user(
            "Reporting Policy Approver",
            "cc-report-approver@example.invalid",
            ["codestra_cc_security.group_cc_global_administrator"],
        )
        cls.identity_service = cls._create_user(
            "Reporting Identity Service",
            "cc-report-identity@example.invalid",
            ["base.group_user", "codestra_identity_provisioning.group_provisioning_service"],
        )
        cls.event_service = cls._create_user(
            "Reporting Event Service",
            "cc-report-events@example.invalid",
            ["codestra_cc_wfm.group_cc_workforce_event_service"],
        )
        cls.agent_a = cls._create_user(
            "Reporting Agent A",
            "cc-report-agent-a@example.invalid",
            ["codestra_cc_security.group_cc_campaign_agent"],
        )
        cls.agent_b = cls._create_user(
            "Reporting Agent B",
            "cc-report-agent-b@example.invalid",
            ["codestra_cc_security.group_cc_campaign_agent"],
        )
        cls.supervisor_a = cls._create_user(
            "Reporting Supervisor A",
            "cc-report-supervisor-a@example.invalid",
            ["codestra_cc_security.group_cc_campaign_supervisor"],
        )
        cls.wfm_a = cls._create_user(
            "Reporting WFM A",
            "cc-report-wfm-a@example.invalid",
            ["codestra_cc_security.group_cc_workforce_analyst"],
        )
        cls.agent_membership_a = cls._activate_membership(
            cls.agent_a, cls.campaign_a, "REPORT-AGENT-A", "agent"
        )
        cls.agent_membership_b = cls._activate_membership(
            cls.agent_b, cls.campaign_b, "REPORT-AGENT-B", "agent"
        )
        cls.supervisor_membership_a = cls._activate_membership(
            cls.supervisor_a,
            cls.campaign_a,
            "REPORT-SUPERVISOR-A",
            "supervisor",
            is_primary_supervisor=True,
        )
        cls.wfm_membership_a = cls._activate_membership(
            cls.wfm_a, cls.campaign_a, "REPORT-WFM-A", "workforce"
        )
        cls.policy = cls.env["cc.reporting.policy"].with_user(cls.author).create(
            {
                "campaign_id": cls.campaign_a.id,
                "name": "Synthetic Reporting Policy",
                "version": 1,
                "source_reference": "TEST-REPORTING-POLICY-A",
            }
        )
        cls.asa_definition = cls.env["cc.kpi.definition"].with_user(cls.author).create(
            {
                "campaign_id": cls.campaign_a.id,
                "policy_id": cls.policy.id,
                "family": "inbound",
                "metric_code": "asa",
                "display_name": "Average Speed of Answer",
                "unit": "seconds",
                "direction": "lower",
                "target_value": 20.0,
                "warning_upper": 20.0,
                "critical_upper": 30.0,
                "authoritative_source": "normalized_call_events",
            }
        )
        cls.adherence_definition = cls.env["cc.kpi.definition"].with_user(
            cls.author
        ).create(
            {
                "campaign_id": cls.campaign_a.id,
                "policy_id": cls.policy.id,
                "family": "agent",
                "metric_code": "adherence",
                "display_name": "Schedule Adherence",
                "unit": "percent",
                "direction": "higher",
                "target_value": 90.0,
                "warning_lower": 90.0,
                "critical_lower": 80.0,
                "authoritative_source": "normalized_adherence_events",
            }
        )
        cls.policy.with_user(cls.author).action_submit()
        cls.policy.with_user(cls.approver).action_approve()
        cls.policy.with_user(cls.approver).action_activate()

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
            f"staging://reporting/{ticket.lower()}",
        )
        membership.with_user(cls.approver).action_activate()
        return membership

    def _ingest(self, event_uuid, definition, value, agent=None, aggregate=False):
        return self.env["cc.kpi.snapshot"].with_user(
            self.event_service
        ).ingest_snapshot(
            event_uuid=event_uuid,
            policy_id=self.policy.id,
            definition_id=definition.id,
            period_reference="2026-08-28T12:00:00-04:00/30m",
            value=value,
            data_cutoff_at=fields.Datetime.now(),
            source_payload_hash="9" * 64,
            reconciliation_state="matched",
            agent_membership_id=agent.id if agent else None,
            aggregate_only=aggregate,
        )

    def test_dependencies_policy_definitions_and_safe_defaults(self):
        expected = {"codestra_cc_wfm", "codestra_cc_quality", "codestra_cc_analytics"}
        modules = self.env["ir.module.module"].search([("name", "in", sorted(expected))])
        self.assertEqual(set(modules.mapped("name")), expected)
        self.assertEqual(set(modules.mapped("state")), {"installed"})
        self.assertEqual(self.policy.state, "active")
        self.assertTrue(self.policy.pii_masking_required)
        self.assertFalse(self.policy.supervisor_bulk_export_allowed)
        self.assertEqual(len(self.policy.policy_hash), 64)
        self.assertNotEqual(self.policy.author_id, self.policy.approver_id)

    def test_controlled_metric_catalog_rejects_unknown_code(self):
        with self.assertRaises(ValidationError):
            self.env["cc.kpi.definition"].with_user(self.author).create(
                {
                    "campaign_id": self.campaign_a.id,
                    "policy_id": self.policy.id,
                    "family": "inbound",
                    "metric_code": "invented_metric",
                    "display_name": "Invented",
                    "unit": "count",
                    "direction": "informational",
                    "authoritative_source": "none",
                }
            )

    def test_kpi_thresholds_exact_replay_and_altered_replay(self):
        snapshot = self._ingest("report-snapshot-asa-001", self.asa_definition, 35.0)
        self.assertEqual(snapshot.result_state, "critical")
        replay = self._ingest("report-snapshot-asa-001", self.asa_definition, 35.0)
        self.assertEqual(snapshot, replay)
        with self.assertRaises(ValidationError):
            self._ingest("report-snapshot-asa-001", self.asa_definition, 10.0)

    def test_agent_only_sees_own_agent_snapshot_and_supervisor_sees_campaign(self):
        own = self._ingest(
            "report-snapshot-agent-001",
            self.adherence_definition,
            95.0,
            agent=self.agent_membership_a,
        )
        aggregate = self._ingest(
            "report-snapshot-aggregate-001", self.asa_definition, 18.0, aggregate=True
        )
        self.assertEqual(
            self.env["cc.kpi.snapshot"].with_user(self.agent_a).search([]), own
        )
        self.assertFalse(self.env["cc.kpi.snapshot"].with_user(self.agent_b).search([]))
        self.assertEqual(
            set(self.env["cc.kpi.snapshot"].with_user(self.supervisor_a).search([]).ids),
            {own.id, aggregate.id},
        )
        self.assertEqual(
            set(self.env["cc.kpi.snapshot"].with_user(self.wfm_a).search([]).ids),
            {own.id, aggregate.id},
        )

    def test_raw_export_is_blocked_and_controlled_manifest_is_audited(self):
        snapshot = self._ingest(
            "report-snapshot-export-001", self.asa_definition, 18.0, aggregate=True
        )
        with self.assertRaises(UserError):
            snapshot.export_data(["metric_code", "value"])
        with self.assertRaises(AccessError):
            snapshot.with_user(self.supervisor_a).request_controlled_export(
                "Supervisor bulk export must remain disabled"
            )
        manifest = snapshot.with_user(self.approver).request_controlled_export(
            "Synthetic executive evidence request"
        )
        self.assertEqual(manifest["status"], "manifest_only")
        self.assertEqual(manifest["row_count"], 1)
        event = self.env["cc.reporting.export.event"].search(
            [("event_uuid", "=", manifest["event_uuid"])]
        )
        self.assertEqual(len(event.reason_hash), 64)
        self.assertEqual(event.checksum_sha256, manifest["checksum"])
        with self.assertRaises(AccessError):
            event.unlink()
