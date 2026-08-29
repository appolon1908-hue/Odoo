from unittest.mock import Mock, patch

from odoo.addons.codestra_vicidial_recording.controllers.recording_api import (
    RecordingAPI,
)
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user
from psycopg2.errors import UniqueViolation


class TestRecordingReference(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scope = cls.env["codestra.vicidial.recording.scope.group"].create(
            {"name": "Synthetic QA", "key": "synthetic-qa"}
        )
        cls.campaign = cls.env["codestra.vicidial.campaign"].create(
            {"name": "Synthetic", "campaign_id": "SYNTHETIC"}
        )
        cls.agent_user = new_test_user(
            cls.env,
            login="recording-agent",
            groups="codestra_vicidial_crm.group_agent",
            context={"no_reset_password": True},
        )
        cls.agent = cls.env["codestra.vicidial.agent"].create(
            {
                "name": "Synthetic Agent",
                "vicidial_user": "recording-agent",
                "odoo_user_id": cls.agent_user.id,
                "recording_scope_group_id": cls.scope.id,
            }
        )
        cls.call = cls.env["codestra.vicidial.call"].create(
            {
                "name": "Synthetic Call",
                "uniqueid": "recording-call-1",
                "campaign_id": cls.campaign.id,
                "agent_id": cls.agent.id,
                "duration_seconds": 1,
                "billable_seconds": 1,
            }
        )

    def values(self, **updates):
        values = {
            "recording_uid": "REC-" + "a" * 32,
            "vicidial_call_id": self.call.uniqueid,
            "call_id": self.call.id,
            "campaign_id": self.campaign.id,
            "agent_id": self.agent.id,
            "duration_seconds": 1,
            "format": "mp3",
            "file_size_bytes": 10,
            "sha256": "b" * 64,
            "object_version_id": "object-v1",
            "storage_status": "odoo_linked",
            "retention_class": "standard",
            "environment": "staging",
        }
        values.update(updates)
        return values

    def test_model_constraints_and_no_binary_audio(self):
        recording = self.env["codestra.vicidial.recording"].create(self.values())
        self.assertEqual(recording.call_id, self.call)
        self.assertNotIn("audio", recording._fields)
        self.assertNotIn("object_key", recording._fields)
        with self.cr.savepoint(), self.assertRaises(UniqueViolation):
            self.env["codestra.vicidial.recording"].create(
                self.values(object_version_id="object-v2")
            )
        with self.assertRaises(ValidationError):
            self.env["codestra.vicidial.recording"].create(
                self.values(
                    recording_uid="REC-" + "c" * 32,
                    object_version_id="object-v3",
                    sha256="bad",
                )
            )
        with self.cr.savepoint(), self.assertRaises(UniqueViolation):
            self.env["codestra.vicidial.recording"].create(
                self.values(
                    recording_uid="REC-" + "d" * 32,
                    object_version_id="object-v1",
                )
            )

    def test_canonical_acknowledgement_shape(self):
        recording = self.env["codestra.vicidial.recording"].create(self.values())
        self.assertEqual(
            set(RecordingAPI._ack(recording)),
            {
                "contract_version",
                "recording_uid",
                "odoo_record_id",
                "call_link_status",
                "lead_link_status",
                "campaign_link_status",
                "agent_link_status",
                "storage_status",
                "retention_class",
                "retention_until",
                "legal_hold",
                "updated_at",
            },
        )

    def test_authentication_nonce_reuse_rejected(self):
        nonce_model = self.env["codestra.vicidial.recording.api.nonce"]
        values = {
            "environment": "staging",
            "service_identity": "codestra-middleware",
            "nonce": "synthetic-nonce-0001",
            "request_timestamp": "1700000000",
        }
        nonce_model.create(values)
        with self.cr.savepoint(), self.assertRaises(UniqueViolation):
            nonce_model.create(values)

    def test_retention_audit_and_direct_delete_denied(self):
        recording = self.env["codestra.vicidial.recording"].create(self.values())
        recording.with_context(retention_reason="approved test").write(
            {"retention_class": "high_compliance"}
        )
        audit = self.env["codestra.vicidial.recording.retention.audit"].search(
            [("recording_uid", "=", recording.recording_uid)]
        )
        self.assertEqual(audit.previous_retention_class, "standard")
        self.assertEqual(audit.new_retention_class, "high_compliance")
        self.assertEqual(audit.middleware_acknowledgement_status, "pending")
        with self.assertRaises(AccessError):
            recording.unlink()
        with self.assertRaises(AccessError):
            audit.unlink()

    def test_agent_and_fail_closed_scope_denial(self):
        recording = self.env["codestra.vicidial.recording"].create(self.values())
        self.assertFalse(
            recording.with_user(self.agent_user).check_access_rights(
                "read", raise_exception=False
            )
        )
        supervisor = new_test_user(
            self.env,
            login="recording-supervisor",
            groups="codestra_vicidial_recording.group_recording_supervisor",
            context={"no_reset_password": True},
        )
        self.assertFalse(recording.with_user(supervisor).search([]))

    def test_supervisor_campaign_and_group_scope_and_playback_audit(self):
        supervisor = new_test_user(
            self.env,
            login="recording-scoped-supervisor",
            groups="codestra_vicidial_recording.group_recording_supervisor",
            context={"no_reset_password": True},
        )
        supervisor.write({"recording_scope_group_ids": [(6, 0, self.scope.ids)]})
        self.campaign.write({"supervisor_ids": [(4, supervisor.id)]})
        recording = self.env["codestra.vicidial.recording"].create(self.values())
        visible = recording.with_user(supervisor).search(
            [("recording_uid", "=", recording.recording_uid)]
        )
        self.assertEqual(visible, recording)
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("codestra.recording_middleware_url", "https://middleware")
        params.set_param("codestra.recording_middleware_service_token", "test-token")
        response = Mock()
        response.json.return_value = {
            "playback_url": "https://private.invalid/grant",
            "expires_in": 120,
        }
        response.raise_for_status.return_value = None
        with patch(
            "odoo.addons.codestra_vicidial_recording.models.recording.requests.post",
            return_value=response,
        ) as playback_request:
            action = recording.with_user(supervisor).action_play_recording()
        self.assertEqual(
            playback_request.call_args.kwargs["headers"]["X-Codestra-Environment"],
            "staging",
        )
        self.assertEqual(action["tag"], "codestra_recording_playback")
        audit = self.env["codestra.vicidial.recording.playback.audit"].search(
            [("recording_uid", "=", recording.recording_uid)]
        )
        self.assertEqual(audit.result, "granted")
        self.assertNotIn("playback_url", recording._fields)

    def test_qa_scope_and_limited_write(self):
        qa = new_test_user(
            self.env,
            login="recording-qa",
            groups="codestra_vicidial_recording.group_recording_qa_reviewer",
            context={"no_reset_password": True},
        )
        qa.write(
            {
                "recording_scope_group_ids": [(6, 0, self.scope.ids)],
                "recording_qa_campaign_ids": [(6, 0, self.campaign.ids)],
            }
        )
        recording = self.env["codestra.vicidial.recording"].create(self.values())
        recording.with_user(qa).write({"qa_classification": "reviewed"})
        with self.assertRaises(AccessError):
            recording.with_user(qa).write({"legal_hold": True})
