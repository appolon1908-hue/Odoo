import hashlib
import json
import uuid

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAutomaticCampaignProvisioning(TransactionCase):
    def setUp(self):
        super().setUp()
        self.unit = self.env.ref("call_center_core.business_unit_digital")
        self.purpose = f"AP{uuid.uuid4().hex[:8].upper()}"
        self.design_input = {
            "default_language": "en",
            "recording_policy": "disabled",
            "default_lead_source_policy": "manual",
            "agent_roles": ["SDR"],
            "transfer_roles": ["CLOSERS"],
            "callback_policy": "manual",
            "appointment_policy": "manual",
            "disposition_family": "STANDARD",
            "script_template": "STANDARD_V1",
            "n8n_automation_template": "INACTIVE_DEFAULT",
            "reporting_category": "GENERAL",
            "activation_policy": "manual_authorized",
        }

    def _create_campaign(self, **changes):
        values = {
            "name": "Synthetic Automatic Provisioning Campaign",
            "code": f"{self.unit.code}-{self.purpose}-OUT",
            "business_unit_id": self.unit.id,
            "direction": "outbound",
            "purpose_code": self.purpose,
            "supervisor_ids": [(6, 0, [self.env.user.id])],
            "design_input_json": self.design_input,
        }
        values.update(changes)
        return self.env["call.center.campaign"].create(values)

    def _event(self, campaign, event_type="campaign.design.requested.v1"):
        return (
            self.env["codestra.runtime.integration.outbox"]
            .sudo()
            .search(
                [
                    ("campaign_id", "=", campaign.id),
                    ("event_type", "=", event_type),
                ],
                order="design_request_revision desc",
                limit=1,
            )
        )

    def _manifest(self, campaign, revision=1):
        environment_code = {
            "test": "TEST",
            "staging": "STAGING",
            "production": "PROD",
        }[campaign.provisioning_environment]
        return {
            "schema_version": "campaign-provisioning.v1",
            "environment": campaign.provisioning_environment,
            "integration_uuid": campaign.integration_uuid,
            "design_revision": revision,
            "business_unit": campaign.business_unit_id.code,
            "odoo": {
                "campaign_id": campaign.id,
                "campaign_code": campaign.code,
                "crm_team_code": f"{campaign.business_unit_id.code}_PRIMARY",
                "owner_user_id": campaign.create_uid.id,
                "supervisor_user_id": campaign.supervisor_ids[:1].id,
            },
            "vicidial": {
                "campaign_id": campaign.code,
                "active": False,
                "default_list_id": 21001,
                "lists": [
                    {
                        "list_id": 21001,
                        "code": f"{campaign.business_unit_id.code}_{campaign.purpose_code}_PRIMARY_001",
                        "active": False,
                    }
                ],
                "user_groups": [
                    f"{campaign.business_unit_id.code}_{campaign.purpose_code}_SDR",
                    f"{campaign.business_unit_id.code}_{campaign.purpose_code}_SUPERVISORS",
                ],
                "inbound_groups": [
                    f"{campaign.business_unit_id.code}_{campaign.purpose_code}_SUPPORT"
                ],
                "scripts": [
                    f"{campaign.business_unit_id.code}_{campaign.purpose_code}_SDR_V1"
                ],
                "disposition_set": f"{campaign.business_unit_id.code}_{campaign.purpose_code}_OUT_V1",
            },
            "n8n": {
                "scope": (
                    f"{environment_code}-{campaign.business_unit_id.code}-"
                    f"{campaign.purpose_code}-V{revision}"
                ),
                "workflows_active": False,
            },
            "policies": {
                "calling_hours": "campaign-record",
                "time_zone": campaign.timezone,
                "consent_policy": "campaign-record",
                "dnc_policy": "campaign-record",
                "recording_policy": self.design_input["recording_policy"],
                "transfer_policy": "same-campaign-only",
            },
            "feature_flags": {
                "lead_publication": False,
                "agent_sync": False,
                "live_call_control": False,
                "production_dialing": False,
            },
        }

    def _deliver_preview(self, campaign, manifest=None):
        event = self._event(campaign)
        event._worker_write({"delivery_state": "processing"})
        manifest = manifest or self._manifest(
            campaign, revision=event.design_request_revision
        )
        digest = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        event._finalize_delivery_success(
            {
                "manifest_hash": digest,
                "design_revision": event.design_request_revision,
                "manifest": manifest,
                "validation_errors": [],
            }
        )
        return event

    def test_normal_creation_automatically_requests_one_design(self):
        campaign = self._create_campaign()
        self.assertTrue(campaign.design_automation_enabled)
        self.assertTrue(campaign.automatic_design_managed)
        self.assertTrue(campaign.integration_uuid)
        event = self._event(campaign)
        self.assertEqual(event.event_type, "campaign.design.requested.v1")
        self.assertEqual(event.design_request_revision, 1)
        self.assertEqual(event.delivery_state, "pending")
        self.assertFalse(event.payload_json["feature_flags"]["production_dialing"])
        self.assertEqual(len(campaign.design_revision_ids), 1)
        self.assertEqual(campaign.automatic_design_state, "requested")

    def test_explicit_true_cannot_bypass_managed_design(self):
        campaign = self._create_campaign(design_automation_enabled=True)
        self.assertTrue(campaign.automatic_design_managed)
        self.assertEqual(len(campaign.design_revision_ids), 1)

    def test_explicit_migration_opt_out_remains_available(self):
        campaign = self._create_campaign(design_automation_enabled=False)
        self.assertFalse(campaign.design_automation_enabled)
        self.assertFalse(campaign.automatic_design_managed)
        self.assertFalse(self._event(campaign))

    def test_automatic_management_cannot_be_disabled_by_normal_write(self):
        campaign = self._create_campaign()
        with self.assertRaises(AccessError):
            campaign.write({"design_automation_enabled": False})

    def test_managed_campaign_cannot_activate_directly(self):
        campaign = self._create_campaign()
        with self.assertRaises(ValidationError):
            campaign.write({"state": "active"})

    def test_secret_shaped_design_input_never_reaches_the_outbox(self):
        values = dict(self.design_input)
        values["provider_" + "token"] = "placeholder"
        with self.assertRaises(ValidationError):
            self._create_campaign(design_input_json=values)

    def test_complete_disabled_preview_is_persisted_and_approvable(self):
        campaign = self._create_campaign()
        self._deliver_preview(campaign)
        campaign.invalidate_recordset()
        revision = campaign.current_design_revision_id
        self.assertEqual(revision.state, "ready")
        self.assertTrue(revision.manifest_json)
        self.assertEqual(campaign.design_request_state, "delivered")
        campaign.design_approval_reason = "Synthetic reviewed approval"
        campaign.action_approve_design()
        campaign.invalidate_recordset()
        revision.invalidate_recordset()
        self.assertEqual(campaign.state, "approved")
        self.assertEqual(revision.state, "approved")
        approval = self._event(campaign, "campaign.approved.v1")
        self.assertTrue(approval)
        self.assertEqual(approval.delivery_state, "pending")
        self.assertFalse(approval.payload_json["feature_flags"]["production_dialing"])
        self.assertEqual(campaign.last_approval_event_uuid, approval.event_uuid)
        campaign.action_approve_design()
        self.assertEqual(
            self.env["codestra.runtime.integration.outbox"].sudo().search_count(
                [
                    ("campaign_id", "=", campaign.id),
                    ("event_type", "=", "campaign.approved.v1"),
                ]
            ),
            1,
        )

    def test_hash_only_result_cannot_be_approved(self):
        campaign = self._create_campaign()
        event = self._event(campaign)
        event._worker_write({"delivery_state": "processing"})
        event._finalize_delivery_success(
            {"manifest_hash": "a" * 64, "design_revision": 1}
        )
        campaign.invalidate_recordset()
        self.assertEqual(campaign.automatic_design_state, "hash_only")
        campaign.design_approval_reason = "Must still be rejected"
        with self.assertRaises(ValidationError):
            campaign.action_approve_design()

    def test_live_or_secret_bearing_manifest_is_rejected(self):
        campaign = self._create_campaign()
        event = self._event(campaign)
        revision = campaign.current_design_revision_id
        manifest = self._manifest(campaign)
        manifest["vicidial"]["active"] = True
        digest = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        with self.assertRaises(ValidationError):
            revision._record_preview(
                {
                    "manifest_hash": digest,
                    "design_revision": 1,
                    "manifest": manifest,
                }
            )
        manifest = self._manifest(campaign)
        manifest["provider_" + "token"] = "placeholder"
        digest = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        with self.assertRaises(ValidationError):
            revision._record_preview(
                {
                    "manifest_hash": digest,
                    "design_revision": event.design_request_revision,
                    "manifest": manifest,
                }
            )


    def test_local_required_inputs_cannot_be_cleared_by_middleware(self):
        campaign = self._create_campaign(design_input_json={})
        event = self._event(campaign)
        manifest = self._manifest(campaign, revision=event.design_request_revision)
        digest = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        revision = campaign.current_design_revision_id
        revision._record_preview(
            {
                "manifest_hash": digest,
                "design_revision": event.design_request_revision,
                "manifest": manifest,
                "validation_errors": [],
            }
        )
        revision.invalidate_recordset()
        self.assertEqual(revision.state, "rejected")
        self.assertTrue(revision.validation_errors_json)
        campaign.design_approval_reason = "Must remain blocked"
        with self.assertRaises(ValidationError):
            campaign.action_approve_design()

    def test_wrong_business_unit_list_range_is_rejected(self):
        campaign = self._create_campaign()
        revision = campaign.current_design_revision_id
        manifest = self._manifest(campaign)
        manifest["vicidial"]["default_list_id"] = 31001
        manifest["vicidial"]["lists"][0]["list_id"] = 31001
        digest = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        with self.assertRaises(ValidationError):
            revision._record_preview(
                {
                    "manifest_hash": digest,
                    "design_revision": 1,
                    "manifest": manifest,
                }
            )

    def test_design_change_creates_new_revision_and_preserves_prior(self):
        campaign = self._create_campaign()
        self._deliver_preview(campaign)
        first = campaign.current_design_revision_id
        changed = dict(self.design_input)
        changed["reporting_category"] = "RENEWAL"
        campaign.write({"design_input_json": changed})
        campaign.invalidate_recordset()
        first.invalidate_recordset()
        self.assertEqual(campaign.design_request_revision, 2)
        self.assertEqual(first.state, "superseded")
        self.assertEqual(campaign.current_design_revision_id.state, "requested")
        self.assertEqual(len(campaign.design_revision_ids), 2)

    def test_approval_event_is_not_claimed_by_preview_worker_filter(self):
        campaign = self._create_campaign()
        self._deliver_preview(campaign)
        campaign.design_approval_reason = "Synthetic reviewed approval"
        campaign.action_approve_design()
        approval = self._event(campaign, "campaign.approved.v1")
        claimed = (
            self.env["codestra.runtime.integration.outbox"]
            .with_context(
                _codestra_cron_event_type_allowlist=["campaign.design.requested.v1"]
            )
            ._claim_batch(limit=20)
        )
        self.assertNotIn(approval, claimed)
        self.assertEqual(approval.delivery_state, "pending")
