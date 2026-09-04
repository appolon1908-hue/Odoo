import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestVicidialCallEventReadback(HttpCase):
    secret = "synthetic-readback-contract-secret"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group = cls.env.ref("codestra_vicidial_crm.group_agent")
        cls.subject = str(uuid.uuid4())
        cls.user = cls.env["res.users"].create(
            {
                "name": "Readback Contract Agent",
                "login": f"readback-{uuid.uuid4()}@example.test",
                "keycloak_subject": cls.subject,
                "codestra_tenant_id": "RDB",
                "group_ids": [(6, 0, [group.id])],
            }
        )
        cls.campaign = cls.env["codestra.vicidial.campaign"].create(
            {
                "name": "Readback Contract Campaign",
                "campaign_id": "READBACK",
                "mode": "test",
            }
        )
        cls.env["codestra.vicidial.agent"].create(
            {
                "name": "Readback Contract Agent",
                "vicidial_user": "RDB6102",
                "tenant_id": "RDB",
                "phone_login": "6102",
                "odoo_user_id": cls.user.id,
                "campaign_ids": [(6, 0, [cls.campaign.id])],
            }
        )
        params = cls.env["ir.config_parameter"].sudo()
        params.set_param("codestra.webhook_secret", cls.secret)
        params.set_param("codestra.call_control.tenant_ids", "RDB")

    def payload(self):
        event_id = f"readback-event-{uuid.uuid4()}"
        call_id = f"readback-call-{uuid.uuid4()}"
        return {
            "schema_version": "1.0",
            "event_id": event_id,
            "event_type": "call.created",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "correlation_id": f"corr-{call_id}",
            "tenant_id": "RDB",
            "business_unit_id": "RDB",
            "campaign_id": "READBACK",
            "call_id": call_id,
            "asterisk_uniqueid": f"uid-{call_id}",
            "linkedid": f"linked-{call_id}",
            "agent_id": "RDB6102",
            "extension": "6102",
            "sequence": 1,
            "keycloak_subject": self.subject,
            "direction": "inbound",
            "caller_number": "+18095550102",
        }

    def post_event(self, payload):
        body = json.dumps(payload, separators=(",", ":")).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(
            self.secret.encode(),
            timestamp.encode() + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        return self.url_open(
            "/codestra/api/v1/call-events",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Codestra-Timestamp": timestamp,
                "X-Codestra-Signature": signature,
                "X-Codestra-Event-ID": payload["event_id"],
            },
            timeout=20,
        )

    def read_event(
        self,
        event_id,
        *,
        secret=None,
        header_event_id=None,
        tenant_id="RDB",
        include_headers=True,
    ):
        headers = {}
        if include_headers:
            timestamp = str(int(time.time()))
            signature = hmac.new(
                (secret if secret is not None else self.secret).encode(),
                timestamp.encode() + b".",
                hashlib.sha256,
            ).hexdigest()
            headers = {
                "X-Codestra-Timestamp": timestamp,
                "X-Codestra-Signature": signature,
                "X-Codestra-Event-ID": (
                    event_id
                    if header_event_id is None
                    else header_event_id
                ),
            }
            if tenant_id is not None:
                headers["X-Codestra-Tenant-ID"] = tenant_id
        return self.url_open(
            f"/codestra/api/v1/call-events/{event_id}",
            headers=headers,
            timeout=20,
        )

    def test_matching_event_returns_bounded_no_store_evidence(self):
        payload = self.payload()
        self.assertEqual(self.post_event(payload).status_code, 202)
        response = self.read_event(payload["event_id"])
        self.assertEqual(response.status_code, 200)
        value = response.json()
        event = self.env["codestra.vicidial.call.event"].search(
            [("idempotency_key", "=", payload["event_id"])],
            limit=1,
        )
        self.assertEqual(
            value,
            {
                "event_id": payload["event_id"],
                "event_type": payload["event_type"],
                "call_id": payload["call_id"],
                "sequence": payload["sequence"],
                "state": "new",
                "payload_hash": event.payload_hash,
            },
        )
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")

    def test_signature_event_and_tenant_checks_fail_closed(self):
        payload = self.payload()
        self.assertEqual(self.post_event(payload).status_code, 202)
        event_id = payload["event_id"]
        cases = (
            {"include_headers": False},
            {"secret": "wrong-secret"},
            {"header_event_id": "another-event"},
            {"tenant_id": None},
            {"tenant_id": "OTHER"},
        )
        for values in cases:
            with self.subTest(values=values):
                self.assertEqual(
                    self.read_event(event_id, **values).status_code,
                    403,
                )

    def test_missing_event_returns_404_proven_non_delivery(self):
        response = self.read_event(f"missing-{uuid.uuid4()}")
        self.assertEqual(response.status_code, 404)
