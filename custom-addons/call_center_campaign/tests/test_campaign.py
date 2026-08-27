from ast import literal_eval

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCampaign(TransactionCase):
    def setUp(self):
        super().setUp()
        self.unit = self.env.ref("call_center_core.business_unit_transport")
        self.campaign = self.env["call.center.campaign"].create(
            {
                "name": "Transport Test",
                "code": "TRANSPORT-TEST",
                "business_unit_id": self.unit.id,
            }
        )

    def test_approved_script_is_current(self):
        draft = self.env["call.center.script"].create(
            {
                "name": "Draft",
                "campaign_id": self.campaign.id,
                "business_unit_id": self.unit.id,
                "language_code": "en",
                "version": "1",
            }
        )
        approved = self.env["call.center.script"].create(
            {
                "name": "Approved",
                "campaign_id": self.campaign.id,
                "business_unit_id": self.unit.id,
                "language_code": "en",
                "version": "2",
                "state": "approved",
            }
        )
        self.assertNotEqual(draft, approved)
        self.assertEqual(self.campaign.current_script_id, approved)

    def test_template_duplicate_returns_draft_campaign(self):
        self.campaign.is_template = True
        duplicate = self.campaign.action_duplicate_template()
        self.assertFalse(duplicate.is_template)
        self.assertEqual(duplicate.state, "draft")

    def test_eight_primary_business_units_and_teams_are_repeatable_data(self):
        units = self.env["call.center.business.unit"].search(
            [("code", "in", ["MOY", "COD", "SCP", "MBL", "RLP", "FTP", "TRX", "CAL"])]
        )
        self.assertEqual(len(units), 8)
        teams = self.env["crm.team"].search(
            [
                ("business_unit_id", "in", units.ids),
                ("is_primary_business_unit_team", "=", True),
            ]
        )
        self.assertEqual(len(teams), 8)
        self.assertTrue(all(teams.mapped("alias_name")))
        self.assertTrue(all(teams.mapped("default_pipeline_id")))

    def test_all_business_campaigns_are_inactive_drafts(self):
        prefixes = {"MOY", "COD", "SCP", "MBL", "RLP", "FTP", "TRX", "CAL"}
        campaign_xml_ids = self.env["ir.model.data"].search(
            [
                ("module", "=", "call_center_campaign"),
                ("model", "=", "call.center.campaign"),
            ]
        )
        campaigns = (
            self.env["call.center.campaign"]
            .with_context(active_test=False)
            .browse(campaign_xml_ids.mapped("res_id"))
            .exists()
            .filtered(lambda item: item.code.split("-", 1)[0] in prefixes)
        )
        self.assertEqual(len(campaigns), 103)
        self.assertFalse(any(campaigns.mapped("active")))
        self.assertEqual(set(campaigns.mapped("state")), {"draft"})

    def test_mapping_projection_is_exactly_101_and_inactive(self):
        mappings = self.env["call.center.campaign.mapping"].with_context(
            active_test=False
        ).search([("environment", "=", "staging")])
        self.assertEqual(len(mappings), 101)
        self.assertFalse(any(mappings.mapped("active")))
        self.assertFalse(any(mappings.mapped("production_eligible")))
        self.assertEqual(len(set(mappings.mapped("mapping_uuid"))), 101)
        self.assertEqual(len(set(mappings.mapped("canonical_campaign_code"))), 101)
        self.assertEqual(len(set(mappings.mapped("vicidial_campaign_id"))), 101)

    def test_mapping_cross_unit_and_cross_campaign_are_denied(self):
        mapping = self.env["call.center.campaign.mapping"].with_context(
            active_test=False
        ).search([], limit=1)
        other = self.env["call.center.business.unit"].search(
            [("id", "!=", mapping.business_unit_id.id)], limit=1
        )
        with self.assertRaises(ValidationError):
            mapping.business_unit_id = other
        other_campaign = self.env["call.center.campaign"].with_context(
            active_test=False
        ).search([("business_unit_id", "!=", mapping.business_unit_id.id)], limit=1)
        with self.assertRaises(ValidationError):
            mapping.campaign_id = other_campaign

    def test_mapping_identity_duplicates_are_denied(self):
        mapping = self.env["call.center.campaign.mapping"].with_context(
            active_test=False
        ).search([], limit=1)
        values = mapping.copy_data()[0]
        for field_name in ("mapping_uuid", "canonical_campaign_code", "vicidial_campaign_id"):
            candidate = dict(values)
            candidate["business_record_uuid"] = str(__import__("uuid").uuid4())
            if field_name != "mapping_uuid":
                candidate["mapping_uuid"] = str(__import__("uuid").uuid4())
            if field_name != "canonical_campaign_code":
                candidate["canonical_campaign_code"] += "-DUPLICATE-TEST"
            if field_name != "vicidial_campaign_id":
                candidate["vicidial_campaign_id"] = "ZZZZZZZ" + str(
                    {"mapping_uuid": 1, "canonical_campaign_code": 2, "vicidial_campaign_id": 3}[field_name]
                )
            with self.assertRaises(Exception):
                self.env["call.center.campaign.mapping"].create(candidate)

    def test_mapping_version_rollback_and_production_activation_are_denied(self):
        mapping = self.env["call.center.campaign.mapping"].with_context(
            active_test=False
        ).search([], limit=1)
        mapping.mapping_version = 2
        with self.assertRaises(ValidationError):
            mapping.mapping_version = 1
        with self.assertRaises(ValidationError):
            mapping.production_eligible = True
        with self.assertRaises(ValidationError):
            mapping.active = True

    def test_mapping_allows_only_inactive_canary_production_projection(self):
        mapping = self.env["call.center.campaign.mapping"].with_context(
            active_test=False
        ).search([], limit=1)
        mapping.write({
            "environment": "production", "production_eligible": True,
            "activation_mode": "CANARY_ONLY", "active": False,
            "desired_state": "inactive",
        })
        self.assertEqual(mapping.activation_mode, "CANARY_ONLY")
        with self.assertRaises(ValidationError):
            mapping.activation_mode = "FULL"

    def test_canary_team_cannot_receive_customer_traffic(self):
        department = self.env["call.center.department"].search([
            ("business_unit_id", "=", self.unit.id)
        ], limit=1)
        if not department:
            department = self.env["call.center.department"].create({
                "name": "Canary Test Department", "code": "CANARY-TEST-DEPT",
                "business_unit_id": self.unit.id,
            })
        with self.assertRaises(ValidationError):
            self.env["call.center.team"].create({
                "name": "Unsafe Canary", "code": "UNSAFE-CANARY",
                "business_unit_id": self.unit.id, "department_id": department.id,
                "canary_only": True, "customer_traffic_allowed": True,
            })

    def test_lead_rejects_cross_unit_campaign(self):
        other = self.env.ref("call_center_core.business_unit_digital")
        with self.assertRaises(ValidationError):
            self.env["crm.lead"].create(
                {
                    "name": "Synthetic scope mismatch",
                    "business_unit_id": self.unit.id,
                    "call_center_campaign_id": self.env[
                        "call.center.campaign"
                    ].create(
                        {
                            "name": "Other",
                            "code": "OTHER-SCOPE-TEST",
                            "business_unit_id": other.id,
                        }
                    ).id,
                }
            )

    def test_primary_crm_team_is_unique_per_unit(self):
        with self.assertRaises(ValidationError):
            self.env["crm.team"].create(
                {
                    "name": "Duplicate primary",
                    "business_unit_id": self.unit.id,
                    "is_primary_business_unit_team": True,
                }
            )

    def test_campaign_code_is_globally_unique(self):
        other = self.env.ref("call_center_core.business_unit_digital")
        with self.assertRaises(Exception):
            self.env["call.center.campaign"].create(
                {
                    "name": "Duplicate code in another unit",
                    "code": self.campaign.code,
                    "business_unit_id": other.id,
                }
            )

    def test_lead_requires_campaign(self):
        with self.assertRaises(ValidationError):
            self.env["crm.lead"].create(
                {
                    "name": "Missing campaign",
                    "business_unit_id": self.unit.id,
                    "is_codestra_call_center_lead": True,
                }
            )

    def test_codestra_lead_with_campaign_succeeds(self):
        lead = self.env["crm.lead"].create({
            "name": "Managed with campaign",
            "business_unit_id": self.unit.id,
            "is_codestra_call_center_lead": True,
            "call_center_campaign_id": self.campaign.id,
        })
        self.assertEqual(lead.call_center_campaign_id, self.campaign)

    def test_non_codestra_lead_without_campaign_succeeds(self):
        lead = self.env["crm.lead"].create({
            "name": "Standard CRM opportunity",
            "business_unit_id": self.unit.id,
            "is_codestra_call_center_lead": False,
        })
        self.assertFalse(lead.call_center_campaign_id)

    def test_promoting_standard_lead_without_campaign_fails(self):
        lead = self.env["crm.lead"].create({
            "name": "Standard lead",
            "business_unit_id": self.unit.id,
        })
        with self.assertRaises(ValidationError):
            lead.is_codestra_call_center_lead = True

    def test_campaign_removal_from_codestra_lead_fails(self):
        lead = self.env["crm.lead"].create({
            "name": "Managed lead",
            "business_unit_id": self.unit.id,
            "is_codestra_call_center_lead": True,
            "call_center_campaign_id": self.campaign.id,
        })
        with self.assertRaises(ValidationError):
            lead.call_center_campaign_id = False

    def test_import_style_create_without_mapping_fails_closed(self):
        with self.assertRaisesRegex(ValidationError, "no campaign mapping"):
            self.env["crm.lead"].create({
                "name": "Imported managed lead",
                "business_unit_id": self.unit.id,
                "is_codestra_call_center_lead": True,
            })

    def test_valid_mapping_assigns_campaign(self):
        lead = self.env["crm.lead"].create({
            "name": "Mapped managed lead",
            "business_unit_id": self.unit.id,
            "is_codestra_call_center_lead": True,
            "call_center_campaign_id": self.campaign.id,
        })
        self.assertEqual(lead.campaign_remediation_status, "valid")

    def test_ambiguous_record_is_marked_for_review_not_guessed(self):
        lead = self.env["crm.lead"].create({
            "name": "Historical ambiguous lead",
            "business_unit_id": self.unit.id,
            "campaign_remediation_status": "review",
        })
        self.assertFalse(lead.call_center_campaign_id)
        self.assertEqual(lead.campaign_remediation_status, "review")

    def test_campaign_delete_blocked_with_dependent_lead(self):
        self.env["crm.lead"].create({
            "name": "Dependent managed lead",
            "business_unit_id": self.unit.id,
            "is_codestra_call_center_lead": True,
            "call_center_campaign_id": self.campaign.id,
        })
        with self.assertRaises(Exception):
            self.campaign.unlink()

    def test_campaign_archive_preserves_existing_assignment(self):
        lead = self.env["crm.lead"].create({
            "name": "Archive-safe lead",
            "business_unit_id": self.unit.id,
            "is_codestra_call_center_lead": True,
            "call_center_campaign_id": self.campaign.id,
        })
        self.campaign.active = False
        self.assertEqual(lead.call_center_campaign_id, self.campaign)

    def test_duplicate_lead_preserves_campaign(self):
        lead = self.env["crm.lead"].create({
            "name": "Original managed lead",
            "business_unit_id": self.unit.id,
            "is_codestra_call_center_lead": True,
            "call_center_campaign_id": self.campaign.id,
        })
        duplicate = lead.copy({"name": "Duplicate managed lead"})
        self.assertEqual(duplicate.call_center_campaign_id, self.campaign)

    def test_integration_context_without_mapping_fails_closed(self):
        with self.assertRaises(ValidationError):
            self.env["crm.lead"].with_context(
                source_system="middleware", integration_write=True
            ).create({
                "name": "Middleware lead without mapping",
                "business_unit_id": self.unit.id,
                "is_codestra_call_center_lead": True,
            })

    def test_business_unit_change_cannot_invalidate_campaign(self):
        lead = self.env["crm.lead"].create({
            "name": "Scoped managed lead",
            "business_unit_id": self.unit.id,
            "is_codestra_call_center_lead": True,
            "call_center_campaign_id": self.campaign.id,
        })
        other = self.env.ref("call_center_core.business_unit_digital")
        with self.assertRaises(ValidationError):
            lead.business_unit_id = other

    def test_lead_rejects_cross_unit_operational_assignments(self):
        other = self.env.ref("call_center_core.business_unit_digital")
        department = self.env["call.center.department"].create(
            {
                "name": "Other Department",
                "code": "OTHER-DEPT-TEST",
                "business_unit_id": other.id,
            }
        )
        team = self.env["call.center.team"].create(
            {
                "name": "Other Team",
                "business_unit_id": other.id,
                "department_id": department.id,
            }
        )
        user = self.env["res.users"].create(
            {
                "name": "Other Scoped User",
                "login": "other-scope@example.invalid",
                "call_center_business_unit_ids": [(6, 0, other.ids)],
                "call_center_default_business_unit_id": other.id,
            }
        )
        base = {
            "name": "Synthetic operational mismatch",
            "business_unit_id": self.unit.id,
            "call_center_campaign_id": self.campaign.id,
        }
        for field_name, value in (
            ("call_center_department_id", department.id),
            ("call_center_operational_team_id", team.id),
            ("call_center_supervisor_id", user.id),
            ("call_center_manager_id", user.id),
            ("user_id", user.id),
        ):
            with self.subTest(field_name=field_name):
                with self.assertRaises(ValidationError):
                    self.env["crm.lead"].create(
                        {**base, field_name: value}
                    )

    def test_campaign_rejects_cross_unit_operational_team(self):
        other = self.env.ref("call_center_core.business_unit_digital")
        department = self.env["call.center.department"].create(
            {
                "name": "Other Campaign Department",
                "code": "OTHER-CAMPAIGN-DEPT-TEST",
                "business_unit_id": other.id,
            }
        )
        team = self.env["call.center.team"].create(
            {
                "name": "Other Campaign Team",
                "business_unit_id": other.id,
                "department_id": department.id,
            }
        )
        with self.assertRaises(ValidationError):
            self.campaign.team_ids = team

    def test_alias_defaults_are_business_unit_and_campaign_scoped(self):
        team = self.env.ref("call_center_campaign.crm_team_moy")
        values = team._alias_get_creation_values()
        self.assertEqual(values["alias_defaults"]["team_id"], team.id)
        self.assertEqual(
            values["alias_defaults"]["business_unit_id"], team.business_unit_id.id
        )
        self.assertEqual(
            values["alias_defaults"]["call_center_campaign_id"],
            team.default_campaign_id.id,
        )
        persisted = literal_eval(team.alias_defaults)
        self.assertEqual(persisted["business_unit_id"], team.business_unit_id.id)
        self.assertEqual(
            persisted["call_center_campaign_id"], team.default_campaign_id.id
        )
