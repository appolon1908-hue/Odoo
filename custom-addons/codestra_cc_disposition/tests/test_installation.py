from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.codestra_cc_disposition.models.script_disposition import (
    DISPOSITION_CATALOG_CAPABILITY,
)


@tagged("post_install", "-at_install")
class TestGovernedScriptsAndDispositions(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["cc.business.unit"]._adopt_legacy_records()
        cls.Campaign = cls.env["cc.campaign"].with_context(active_test=False)
        cls.Script = cls.env["cc.script"]
        cls.Version = cls.env["cc.script.version"]
        cls.Set = cls.env["cc.disposition.set"]
        cls.Disposition = cls.env["cc.disposition"]
        cls.campaign_a = cls.Campaign.search(
            [("code", "=", "COD-WEB-OUT")], limit=1
        )
        cls.campaign_b = cls.Campaign.search(
            [("id", "!=", cls.campaign_a.id), ("channel_ids", "!=", False)], limit=1
        )
        cls.channel_a = cls.env["cc.campaign.channel"].with_context(
            active_test=False
        ).search([("campaign_id", "=", cls.campaign_a.id)], limit=1)
        cls.channel_b = cls.env["cc.campaign.channel"].with_context(
            active_test=False
        ).search([("campaign_id", "=", cls.campaign_b.id)], limit=1)
        cls.requester = cls._create_user(
            "Script Author",
            "cc-script-author@example.invalid",
            ["codestra_cc_security.group_cc_global_administrator"],
        )
        cls.approver = cls._create_user(
            "Script Approver",
            "cc-script-approver@example.invalid",
            ["codestra_cc_security.group_cc_global_administrator"],
        )
        cls.service = cls._create_user(
            "Script Identity Service",
            "cc-script-service@example.invalid",
            [
                "base.group_user",
                "codestra_identity_provisioning.group_provisioning_service",
            ],
        )
        cls.agent_a = cls._create_user(
            "Script Agent A",
            "cc-script-agent-a@example.invalid",
            ["codestra_cc_security.group_cc_campaign_agent"],
        )
        cls.agent_b = cls._create_user(
            "Script Agent B",
            "cc-script-agent-b@example.invalid",
            ["codestra_cc_security.group_cc_campaign_agent"],
        )
        cls.membership_a = cls._activate_membership(
            cls.agent_a, cls.campaign_a, "SCRIPT-MEMBER-A"
        )
        cls.membership_b = cls._activate_membership(
            cls.agent_b, cls.campaign_b, "SCRIPT-MEMBER-B"
        )
        cls.script_a, cls.version_a = cls._create_approved_script(
            cls.campaign_a, "Synthetic Campaign A Script", "SCRIPT-APPROVAL-A"
        )
        cls.script_b, cls.version_b = cls._create_approved_script(
            cls.campaign_b, "Synthetic Campaign B Script", "SCRIPT-APPROVAL-B"
        )
        cls.set_a = cls.Set.with_user(cls.requester).create(
            {
                "name": "Synthetic Campaign A Dispositions",
                "campaign_id": cls.campaign_a.id,
                "version": 1,
            }
        )
        cls.set_b = cls.Set.with_user(cls.requester).create(
            {
                "name": "Synthetic Campaign B Dispositions",
                "campaign_id": cls.campaign_b.id,
                "version": 1,
            }
        )

    @classmethod
    def _create_user(cls, name, login, group_xmlids):
        groups = cls.env["res.groups"].browse(
            [cls.env.ref(xmlid).id for xmlid in group_xmlids]
        )
        return cls.env["res.users"].create(
            {"name": name, "login": login, "group_ids": [(6, 0, groups.ids)]}
        )

    @classmethod
    def _activate_membership(cls, user, campaign, ticket, role="agent"):
        employee = cls.env["hr.employee"].create(
            {"name": user.name, "user_id": user.id, "company_id": cls.env.company.id}
        )
        membership = cls.env["cc.campaign.membership"].with_user(
            cls.requester
        ).create(
            {
                "user_id": user.id,
                "employee_id": employee.id,
                "campaign_id": campaign.id,
                "role": role,
                "requested_by_id": cls.requester.id,
                "source_ticket": ticket,
                "starts_at": fields.Datetime.now(),
            }
        )
        membership.with_user(cls.requester).action_submit_identity()
        operation = membership.with_user(cls.approver).action_approve_identity()
        operation.with_user(cls.service).action_record_readback(
            {
                target: {"status": "matched", "evidence_hash": "a" * 64}
                for target in operation.required_targets
            },
            f"staging://scripts/{ticket.lower()}",
        )
        membership.with_user(cls.approver).action_activate()
        return membership

    @classmethod
    def _script_content(cls, marker):
        return {
            "opening": f"<p>{marker} company and campaign identity</p>",
            "identity_verification": "<p>Verify the synthetic customer.</p>",
            "recording_disclosure": "<p>Provide the recording disclosure.</p>",
            "qualification_questions": "<p>Ask approved qualification questions.</p>",
            "product_explanation": "<p>Explain only the approved service.</p>",
            "objection_handling": "<p>Use approved handling guidance.</p>",
            "closing": "<p>Confirm the next step.</p>",
            "required_legal_statements": "<p>Read required legal statements.</p>",
            "opt_out_language": "<p>Honor the opt-out request immediately.</p>",
            "escalation_instructions": "<p>Escalate inside the campaign.</p>",
            "prohibited_statements": "<p>Internal prohibited wording.</p>",
            "supervisor_notes": "<p>Internal supervisor note.</p>",
        }

    @classmethod
    def _create_approved_script(cls, campaign, name, ticket):
        script = cls.Script.with_user(cls.requester).create(
            {"name": name, "campaign_id": campaign.id, "language_code": "en"}
        )
        version = script.with_user(cls.requester).action_create_version(
            cls._script_content(campaign.code)
        )
        version.with_user(cls.requester).action_submit_for_review()
        version.with_user(cls.approver).action_approve(ticket)
        return script, version

    def test_dependencies_and_canonical_models_are_installed(self):
        expected = {
            "codestra_cc_campaign",
            "codestra_cc_identity",
            "codestra_cc_vicidial",
            "call_center_campaign",
            "codestra_vicidial_crm",
        }
        modules = self.env["ir.module.module"].search([("name", "in", sorted(expected))])
        self.assertEqual(set(modules.mapped("name")), expected)
        self.assertEqual(set(modules.mapped("state")), {"installed"})
        for model_name in (
            "cc.script",
            "cc.script.version",
            "cc.script.acknowledgement",
            "cc.disposition.set",
            "cc.disposition",
        ):
            self.assertIn(model_name, self.env)

    def test_script_approval_is_separated_hashed_and_immutable(self):
        self.assertEqual(self.version_a.governance_state, "approved")
        self.assertEqual(self.version_a.state, "approved")
        self.assertEqual(self.version_a.approved_by_id, self.approver)
        self.assertEqual(self.version_a.approval_ticket, "SCRIPT-APPROVAL-A")
        self.assertEqual(len(self.version_a.content_hash), 64)
        self.assertEqual(self.script_a.active_version_id, self.version_a)
        with self.assertRaises(AccessError):
            self.version_a.with_user(self.approver).write(
                {"opening": "<p>Silent approved edit</p>"}
            )
        with self.assertRaises(AccessError):
            self.version_a.legacy_script_id.with_user(self.approver).write(
                {"closing": "<p>Legacy bypass</p>"}
            )
        with self.assertRaises(AccessError):
            self.version_a.copy()
        with self.assertRaises(AccessError):
            self.version_a.unlink()

        version_two = self.script_a.with_user(self.requester).action_create_version(
            self._script_content("VERSION-TWO")
        )
        version_two.with_user(self.requester).action_submit_for_review()
        with self.assertRaises(AccessError):
            version_two.with_user(self.requester).action_approve("SELF-APPROVAL")
        with self.assertRaises(ValidationError):
            version_two.with_user(self.approver).action_approve("SECOND-ACTIVE")

    def test_agent_render_is_current_campaign_safe_and_redacted(self):
        rendering = self.script_a.with_user(self.agent_a).action_render_active()
        self.assertEqual(rendering["campaign_code"], self.campaign_a.code)
        self.assertEqual(rendering["content_hash"], self.version_a.content_hash)
        self.assertIn("opening", rendering["sections"])
        self.assertNotIn("prohibited_statements", rendering["sections"])
        self.assertNotIn("supervisor_notes", rendering["sections"])
        with self.assertRaises(AccessError):
            self.script_b.with_user(self.agent_a).action_render_active()
        with self.assertRaises(AccessError):
            self.version_a.with_user(self.agent_a).read(["supervisor_notes"])
        with self.assertRaises(UserError):
            self.script_a.with_user(self.agent_a).export_data(["name"])

    def test_agent_script_query_surfaces_are_campaign_and_state_scoped(self):
        draft = self.script_a.with_user(self.requester).action_create_version()
        ScriptA = self.Script.with_user(self.agent_a)
        VersionA = self.Version.with_user(self.agent_a)
        self.assertEqual(ScriptA.search([]), self.script_a)
        self.assertFalse(ScriptA.search([("id", "=", self.script_b.id)]))
        self.assertFalse(ScriptA.name_search(self.script_b.name, operator="=", limit=10))
        grouped = ScriptA._read_group([], ["language_code"], ["__count"])
        self.assertEqual(sum(count for _language, count in grouped), 1)
        self.assertEqual(VersionA.search([]), self.version_a)
        self.assertFalse(VersionA.search([("id", "=", draft.id)]))
        self.assertFalse(VersionA.search([("id", "=", self.version_b.id)]))
        with self.assertRaises(AccessError):
            self.version_b.with_user(self.agent_a).read(["display_name"])
        with self.assertRaises(AccessError):
            self.Version.with_user(self.approver).with_context(
                _cc_script_version_capability=True
            ).create({"script_id": self.script_a.id, "version_number": 99})

    def test_acknowledgement_is_exactly_once_hash_bound_and_append_only(self):
        acknowledgement = self.version_a.with_user(self.agent_a).action_acknowledge(
            "script-ack-a-001"
        )
        repeated = self.version_a.with_user(self.agent_a).action_acknowledge(
            "script-ack-a-001"
        )
        self.assertEqual(repeated, acknowledgement)
        self.assertEqual(acknowledgement.membership_id, self.membership_a)
        self.assertEqual(acknowledgement.content_hash, self.version_a.content_hash)
        with self.assertRaises(ValidationError):
            self.version_a.with_user(self.agent_a).action_acknowledge(
                "script-ack-a-002"
            )
        with self.assertRaises(AccessError):
            acknowledgement.with_user(self.agent_a).write({"event_id": "forged"})
        with self.assertRaises(AccessError):
            acknowledgement.unlink()
        with self.assertRaises(AccessError):
            self.env["cc.script.acknowledgement"].with_user(self.agent_a).with_context(
                _cc_script_ack_capability=True
            ).create(
                {
                    "version_id": self.version_a.id,
                    "membership_id": self.membership_a.id,
                    "user_id": self.agent_a.id,
                    "event_id": "forged-script-ack",
                    "content_hash": self.version_a.content_hash,
                }
            )

    def test_missing_controlled_catalog_blocks_disposition_approval(self):
        self.assertEqual(self.set_a.catalog_status, "missing")
        self.assertEqual(self.set_a.catalog_row_count, 0)
        self.assertFalse(self.set_a.catalog_sha256)
        with self.assertRaises(UserError):
            self.set_a.with_user(self.requester).action_submit_for_review()
        with self.assertRaises(AccessError):
            self.set_a.with_user(self.requester).write(
                {"catalog_status": "validated", "catalog_row_count": 2677}
            )
        with self.assertRaises(AccessError):
            self.set_a.with_user(self.requester).with_context(
                _cc_disposition_catalog_capability=True
            )._record_catalog_validation(
                "a" * 64, 2677, "staging://dispositions/forged"
            )
        self.assertFalse(self.Set.with_user(self.agent_a).search([]))
        self.assertFalse(self.Disposition.with_user(self.agent_a).search([]))

    def test_disposition_catalog_rows_reject_invalid_native_and_cross_campaign_scope(self):
        legacy = self.env["codestra.disposition"].with_user(self.requester).create(
            {
                "code": "TOOLONG",
                "name": "Synthetic invalid native status",
                "category": "system",
                "business_unit_id": self.campaign_a.cc_business_unit_id.legacy_business_unit_id.id,
                "campaign_id": self.campaign_a.legacy_campaign_id.id,
                "vicidial_status_code": "TOOLONG",
                "canonical_status_id": self.env.ref(
                    "call_center_core.status_disposition_pending"
                ).id,
            }
        )
        values = {
            "legacy_disposition_id": legacy.id,
            "set_id": self.set_a.id,
            "channel_id": self.channel_a.id,
            "required_fields_json": [],
            "callback_behavior": "none",
            "suppression_behavior": "none",
            "reporting_category": "system",
            "event_name": "cc.disposition.synthetic.v1",
            "workflow_mapping_json": {},
            "catalog_row_sha256": "b" * 64,
        }
        with self.assertRaises(ValidationError):
            self.Disposition.with_user(self.requester).with_context(
                _cc_disposition_catalog_capability=DISPOSITION_CATALOG_CAPABILITY
            ).create(values)
        legacy.write({"vicidial_status_code": "VALID"})
        with self.assertRaises(ValidationError):
            self.Disposition.with_user(self.requester).with_context(
                _cc_disposition_catalog_capability=DISPOSITION_CATALOG_CAPABILITY
            ).create(dict(values, channel_id=self.channel_b.id))
        with self.assertRaises(AccessError):
            self.Disposition.with_user(self.requester).with_context(
                _cc_disposition_catalog_capability=True
            ).create(values)

    def test_disposition_set_query_surfaces_are_campaign_scoped_for_configuration(self):
        scoped_config = self._create_user(
            "Campaign A Script Configurator",
            "cc-script-config-a@example.invalid",
            ["codestra_cc_security.group_cc_campaign_configuration_manager"],
        )
        self._activate_membership(
            scoped_config,
            self.campaign_a,
            "SCRIPT-CONFIG-A",
            role="configuration_manager",
        )
        SetA = self.Set.with_user(scoped_config)
        self.assertEqual(SetA.search([]), self.set_a)
        self.assertFalse(SetA.search([("id", "=", self.set_b.id)]))
        self.assertFalse(SetA.name_search(self.set_b.name, operator="=", limit=10))
        grouped = SetA._read_group([], ["catalog_status"], ["__count"])
        self.assertEqual(sum(count for _state, count in grouped), 1)
        with self.assertRaises(AccessError):
            self.set_b.with_user(scoped_config).read(["name"])
        with self.assertRaises(AccessError):
            SetA.create(
                {
                    "name": "Forged Campaign B Set",
                    "campaign_id": self.campaign_b.id,
                    "version": 2,
                }
            )
