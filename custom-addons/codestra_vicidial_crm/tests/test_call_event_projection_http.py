import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestCallEventProjectionHttp(HttpCase):
    secret = "synthetic-call-event-secret-32-bytes-minimum"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        agent_group = cls.env.ref("codestra_vicidial_crm.group_agent")
        service_group = cls.env.ref(
            "codestra_vicidial_crm.group_call_event_projection_service"
        )
        cls.business_unit = cls.env["call.center.business.unit"].search(
            [("code", "=", "COD")], limit=1
        ) or cls.env["call.center.business.unit"].create(
            {"name": "Codestra", "code": "COD"}
        )
        cls.other_business_unit = cls.env["call.center.business.unit"].create(
            {
                "name": "Other Projection Unit",
                "code": "OTHER_" + uuid.uuid4().hex[:8],
            }
        )
        cls.subject = str(uuid.uuid4())
        cls.agent_user = cls.env["res.users"].create(
            {
                "name": "Projection Agent",
                "login": "projection-agent@example.test",
                "keycloak_subject": cls.subject,
                "codestra_tenant_id": "COD",
                "call_center_business_unit_ids": [(6, 0, [cls.business_unit.id])],
                "call_center_default_business_unit_id": cls.business_unit.id,
                "group_ids": [(6, 0, [agent_group.id])],
            }
        )
        cls.service_user = cls.env["res.users"].create(
            {
                "name": "Projection Service",
                "login": "projection-service@example.test",
                "group_ids": [(6, 0, [service_group.id])],
            }
        )
        cls.campaign = cls.env["codestra.vicidial.campaign"].search(
            [("campaign_id", "=", "TEST_SYN")], limit=1
        ) or cls.env["codestra.vicidial.campaign"].create(
            {"name": "Synthetic Projection", "campaign_id": "TEST_SYN", "mode": "test"}
        )
        cls.env["codestra.vicidial.agent"].create(
            {
                "name": "Projection Agent",
                "vicidial_user": "SYN6101",
                "tenant_id": "COD",
                "phone_login": "6101",
                "odoo_user_id": cls.agent_user.id,
                "campaign_ids": [(6, 0, [cls.campaign.id])],
            }
        )
        params = cls.env["ir.config_parameter"].sudo()
        params.set_param("codestra.call_control.tenant_ids", "COD")
        params.set_param("codestra.call_event.inbound_hmac_secret", cls.secret)
        params.set_param("codestra.call_event.service_user_id", cls.service_user.id)
        params.set_param("codestra.call_event_projection_enabled", "True")
        params.set_param("codestra.call_event_synthetic_only", "True")

    def payload(self):
        token = uuid.uuid4().hex
        call_id = "vici-call-" + token
        return {
            "schema_version": "1.0",
            "event_id": "vici-evt-" + uuid.uuid4().hex,
            "event_type": "call.created",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "correlation_id": call_id,
            "tenant_id": "COD",
            "business_unit_id": self.business_unit.code,
            "campaign_id": "TEST_SYN",
            "call_id": call_id,
            "asterisk_uniqueid": "ast-" + token,
            "linkedid": "linked-" + token,
            "agent_id": "SYN6101",
            "extension": "6101",
            "sequence": 1,
            "keycloak_subject": self.subject,
            "synthetic_test": True,
            "direction": "inbound",
            "caller_number": "+18095550100",
        }

    def headers(self, payload, body, method="POST", path="/codestra/middleware/v1/call-events", secret=None):
        timestamp = str(int(time.time()))
        event_id = payload["event_id"]
        canonical = b"\n".join(
            (
                timestamp.encode(), event_id.encode(), method.encode(), path.encode(),
                payload["tenant_id"].encode(), payload["correlation_id"].encode(),
                event_id.encode(), body,
            )
        )
        signature = hmac.new((secret or self.secret).encode(), canonical, hashlib.sha256).hexdigest()
        return {
            "Content-Type": "application/json",
            "Idempotency-Key": event_id,
            "X-Codestra-Timestamp": timestamp,
            "X-Codestra-Event-ID": event_id,
            "X-Codestra-Signature": "sha256=" + signature,
            "X-Tenant-ID": payload["tenant_id"],
            "X-Correlation-ID": payload["correlation_id"],
        }

    def post_payload(self, payload, *, secret=None):
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        return self.url_open(
            "/codestra/middleware/v1/call-events",
            data=body,
            headers=self.headers(payload, body, secret=secret),
            timeout=20,
        )

    def next_event(self, payload, event_type, sequence, **values):
        result = dict(payload)
        result.update(
            {
                "event_id": "vici-evt-" + uuid.uuid4().hex,
                "event_type": event_type,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "sequence": sequence,
            }
        )
        result.update(values)
        return result

    def test_accept_duplicate_and_status_readback(self):
        payload = self.payload()
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        accepted = self.url_open(
            "/codestra/middleware/v1/call-events",
            data=body,
            headers=self.headers(payload, body),
            timeout=20,
        )
        self.assertEqual(accepted.status_code, 202)
        duplicate = self.url_open(
            "/codestra/middleware/v1/call-events",
            data=body,
            headers=self.headers(payload, body),
            timeout=20,
        )
        self.assertEqual(duplicate.status_code, 200)
        path = f"/codestra/middleware/v1/call-events/{payload['event_id']}/status"
        status = self.url_open(
            path,
            headers=self.headers(payload, b"", method="GET", path=path),
            timeout=20,
        )
        self.assertEqual(status.status_code, 200)
        self.assertTrue(status.json()["recorded"])

    def test_invalid_signature_is_rejected(self):
        response = self.post_payload(self.payload(), secret="wrong-secret")
        self.assertEqual(response.status_code, 403)

    def test_business_unit_must_belong_to_assigned_agent(self):
        payload = self.payload()
        payload["business_unit_id"] = self.other_business_unit.code
        response = self.post_payload(payload)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            self.env["codestra.vicidial.call"].sudo().search_count(
                [("call_id", "=", payload["call_id"])]
            )
        )

    def test_existing_call_rejects_correlation_change(self):
        payload = self.payload()
        self.assertEqual(self.post_payload(payload).status_code, 202)
        changed = self.next_event(
            payload,
            "call.ringing",
            2,
            correlation_id="corr-changed-" + uuid.uuid4().hex,
        )
        response = self.post_payload(changed)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            self.env["codestra.vicidial.call.event"].sudo().search_count(
                [("idempotency_key", "=", changed["event_id"])]
            )
        )

    def test_sequence_gap_is_retryable_unrecorded_and_can_be_replayed(self):
        created = self.payload()
        self.assertEqual(self.post_payload(created).status_code, 202)
        gap = self.next_event(created, "call.ringing", 3)
        rejected = self.post_payload(gap)
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(
            rejected.json(),
            {
                "error": "sequence_gap",
                "retryable": True,
                "detail": "one or more earlier lifecycle events are not recorded",
                "event_id": gap["event_id"],
                "tenant_id": gap["tenant_id"],
                "call_id": gap["call_id"],
                "event_type": gap["event_type"],
                "sequence": 3,
                "recorded": False,
                "expected_sequence": 2,
                "current_sequence": 1,
            },
        )
        self.assertFalse(
            self.env["codestra.vicidial.call.event"].sudo().search_count(
                [("idempotency_key", "=", gap["event_id"])]
            )
        )
        offered = self.next_event(created, "call.offered", 2)
        self.assertEqual(self.post_payload(offered).status_code, 202)
        self.assertEqual(self.post_payload(gap).status_code, 202)
        call = self.env["codestra.vicidial.call"].sudo().search(
            [("call_id", "=", created["call_id"])], limit=1
        )
        self.assertEqual(call.sequence, 3)
        self.assertEqual(call.state, "ringing")

    def test_stale_sequence_is_terminal_and_not_recorded(self):
        created = self.payload()
        self.assertEqual(self.post_payload(created).status_code, 202)
        offered = self.next_event(created, "call.offered", 2)
        self.assertEqual(self.post_payload(offered).status_code, 202)
        stale = self.next_event(created, "call.ringing", 1)
        rejected = self.post_payload(stale)
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(rejected.json()["error"], "stale_sequence")
        self.assertFalse(rejected.json()["retryable"])
        self.assertFalse(rejected.json()["recorded"])
        self.assertFalse(
            self.env["codestra.vicidial.call.event"].sudo().search_count(
                [("idempotency_key", "=", stale["event_id"])]
            )
        )

    def test_invalid_transition_is_terminal_and_not_recorded(self):
        created = self.payload()
        self.assertEqual(self.post_payload(created).status_code, 202)
        completed = self.next_event(created, "call.completed", 2)
        rejected = self.post_payload(completed)
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(rejected.json()["error"], "lifecycle_conflict")
        self.assertFalse(rejected.json()["retryable"])
        self.assertFalse(rejected.json()["recorded"])
        self.assertFalse(
            self.env["codestra.vicidial.call.event"].sudo().search_count(
                [("idempotency_key", "=", completed["event_id"])]
            )
        )
