import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone

from odoo.exceptions import AccessError
from odoo.tests import HttpCase, tagged
from odoo.tests.common import TransactionCase

from ..controllers.call_event_readback import CallEventReadbackAPI


class TestCallEventReadbackModel(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        suffix = uuid.uuid4().hex[:8]
        cls.campaign = cls.env["codestra.vicidial.campaign"].create(
            {
                "name": "Readback campaign " + suffix,
                "campaign_id": "RB" + suffix.upper(),
                "mode": "test",
            }
        )
        cls.agent = cls.env["codestra.vicidial.agent"].create(
            {
                "name": "Readback agent " + suffix,
                "vicidial_user": "RB" + suffix,
                "tenant_id": "COD",
                "phone_login": "71" + suffix[:2],
                "campaign_ids": [(6, 0, [cls.campaign.id])],
            }
        )
        cls.call = cls.env["codestra.vicidial.call"].create(
            {
                "name": "Readback call " + suffix,
                "call_id": "call-" + suffix,
                "correlation_id": "corr-" + suffix,
                "asterisk_uniqueid": "uid-" + suffix,
                "uniqueid": "uid-" + suffix,
                "linkedid": "linked-" + suffix,
                "tenant_id": "COD",
                "business_unit_id": "COD",
                "keycloak_subject": str(uuid.uuid4()),
                "campaign_id": cls.campaign.id,
                "campaign_code": cls.campaign.campaign_id,
                "agent_id": cls.agent.id,
                "vicidial_user": cls.agent.vicidial_user,
                "extension": cls.agent.phone_login,
                "direction": "inbound",
                "state": "ringing",
                "sequence": 1,
                "idempotency_key": "call-key-" + suffix,
            }
        )
        cls.event = cls.env["codestra.vicidial.call.event"].create(
            {
                "event_type": "call.ringing",
                "occurred_at": datetime.now(timezone.utc),
                "call_id": cls.call.id,
                "agent_id": cls.agent.id,
                "campaign_id": cls.campaign.id,
                "payload_json": "{}",
                "payload_hash": "a" * 64,
                "idempotency_key": "event-" + suffix,
                "processing_state": "processed",
                "processed_at": datetime.now(timezone.utc),
                "correlation_id": cls.call.correlation_id,
                "sequence": 1,
            }
        )

    def test_readback_returns_bounded_evidence(self):
        evidence = self.env[
            "codestra.vicidial.call.event"
        ].codestra_readback(self.event.idempotency_key, "COD")
        self.assertEqual(evidence["event_id"], self.event.idempotency_key)
        self.assertEqual(evidence["call_id"], self.call.call_id)
        self.assertEqual(evidence["payload_hash"], "a" * 64)
        self.assertEqual(evidence["sequence"], 1)
        self.assertNotIn("payload_json", evidence)
        self.assertNotIn("caller_number", evidence)

    def test_readback_is_tenant_bound(self):
        with self.assertRaises(AccessError):
            self.env["codestra.vicidial.call.event"].codestra_readback(
                self.event.idempotency_key,
                "OTHER",
            )
        self.assertFalse(
            self.env["codestra.vicidial.call.event"].codestra_readback(
                "missing-event",
                "COD",
            )
        )

    def test_v2_signature_binds_path_event_and_tenant(self):
        secret = "s" * 32
        timestamp = "1788537600"
        event_id = "event-readback-1"
        tenant_id = "COD"
        path = "/codestra/api/v1/call-events/" + event_id
        canonical = "\n".join(
            (
                "v2",
                "GET",
                path,
                timestamp,
                event_id,
                tenant_id,
                hashlib.sha256(b"").hexdigest(),
            )
        ).encode()
        expected = "sha256=" + hmac.new(
            secret.encode(), canonical, hashlib.sha256
        ).hexdigest()
        self.assertEqual(
            CallEventReadbackAPI.signature(
                secret,
                timestamp,
                path,
                event_id,
                tenant_id,
            ),
            expected,
        )
        self.assertNotEqual(
            expected,
            CallEventReadbackAPI.signature(
                secret,
                timestamp,
                path + "-other",
                event_id,
                tenant_id,
            ),
        )


@tagged("post_install", "-at_install")
class TestCallEventReadbackHTTP(HttpCase):
    secret = "synthetic-call-event-readback-secret-2026"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        suffix = uuid.uuid4().hex[:8]
        group = cls.env.ref("codestra_vicidial_crm.group_agent")
        cls.subject = str(uuid.uuid4())
        cls.user = cls.env["res.users"].create(
            {
                "name": "Readback HTTP Agent",
                "login": "readback-http-" + suffix + "@example.test",
                "keycloak_subject": cls.subject,
                "codestra_tenant_id": "COD",
                "group_ids": [(6, 0, [group.id])],
            }
        )
        cls.campaign = cls.env["codestra.vicidial.campaign"].create(
            {
                "name": "Readback HTTP Campaign",
                "campaign_id": "RH" + suffix.upper(),
                "mode": "test",
            }
        )
        cls.agent = cls.env["codestra.vicidial.agent"].create(
            {
                "name": "Readback HTTP Agent",
                "vicidial_user": "RH" + suffix,
                "tenant_id": "COD",
                "phone_login": "72" + suffix[:2],
                "odoo_user_id": cls.user.id,
                "campaign_ids": [(6, 0, [cls.campaign.id])],
            }
        )
        params = cls.env["ir.config_parameter"].sudo()
        params.set_param("codestra.webhook_secret", cls.secret)
        params.set_param("codestra.call_control.tenant_ids", "COD")

    def _post_event(self, event_id):
        call_id = "readback-http-call-" + uuid.uuid4().hex
        payload = {
            "schema_version": "1.0",
            "event_id": event_id,
            "event_type": "call.created",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "correlation_id": "corr-" + call_id,
            "tenant_id": "COD",
            "business_unit_id": "COD",
            "campaign_id": self.campaign.campaign_id,
            "call_id": call_id,
            "asterisk_uniqueid": "uid-" + call_id,
            "linkedid": "linked-" + call_id,
            "agent_id": self.agent.vicidial_user,
            "extension": self.agent.phone_login,
            "sequence": 0,
            "keycloak_subject": self.subject,
            "direction": "inbound",
            "caller_number": "+18095550100",
        }
        raw = json.dumps(payload, separators=(",", ":")).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(
            self.secret.encode(),
            timestamp.encode() + b"." + raw,
            hashlib.sha256,
        ).hexdigest()
        response = self.url_open(
            "/codestra/api/v1/call-events",
            data=raw,
            headers={
                "Content-Type": "application/json",
                "X-Codestra-Timestamp": timestamp,
                "X-Codestra-Signature": signature,
                "X-Codestra-Event-ID": event_id,
            },
            timeout=20,
        )
        self.assertEqual(response.status_code, 202)
        return payload

    def _get_event(self, event_id, tenant_id="COD", secret=None):
        path = "/codestra/api/v1/call-events/" + event_id
        timestamp = str(int(time.time()))
        signature = CallEventReadbackAPI.signature(
            self.secret if secret is None else secret,
            timestamp,
            path,
            event_id,
            tenant_id,
        )
        return self.url_open(
            path,
            headers={
                "X-Codestra-Timestamp": timestamp,
                "X-Codestra-Signature": signature,
                "X-Codestra-Signature-Version": "v2",
                "X-Codestra-Event-ID": event_id,
                "X-Codestra-Tenant-ID": tenant_id,
            },
            timeout=20,
        )

    def test_readback_after_accepted_event(self):
        event_id = "readback-http-event-" + uuid.uuid4().hex
        payload = self._post_event(event_id)
        response = self._get_event(event_id)
        self.assertEqual(response.status_code, 200)
        evidence = response.json()
        self.assertEqual(evidence["event_id"], event_id)
        self.assertEqual(evidence["tenant_id"], "COD")
        self.assertEqual(evidence["call_id"], payload["call_id"])
        self.assertEqual(len(evidence["payload_hash"]), 64)
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")

    def test_readback_rejects_wrong_tenant_and_signature(self):
        event_id = "readback-http-event-" + uuid.uuid4().hex
        self._post_event(event_id)
        self.assertEqual(self._get_event(event_id, tenant_id="OTHER").status_code, 403)
        self.assertEqual(self._get_event(event_id, secret="x" * 32).status_code, 403)

    def test_readback_missing_event(self):
        event_id = "readback-missing-" + uuid.uuid4().hex
        self.assertEqual(self._get_event(event_id).status_code, 404)
