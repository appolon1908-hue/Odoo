import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestCallEventAPIContract(HttpCase):
    secret = "synthetic-http-contract-secret"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group = cls.env.ref("codestra_vicidial_crm.group_agent")
        cls.subject = str(uuid.uuid4())
        cls.user = cls.env["res.users"].create(
            {
                "name": "HTTP Contract Agent",
                "login": "http-contract-agent@example.test",
                "keycloak_subject": cls.subject,
                "codestra_tenant_id": "COD",
                "group_ids": [(6, 0, [group.id])],
            }
        )
        cls.campaign = cls.env["codestra.vicidial.campaign"].create(
            {
                "name": "HTTP Contract Campaign",
                "campaign_id": "HTTP_CONTRACT",
                "mode": "test",
            }
        )
        cls.env["codestra.vicidial.agent"].create(
            {
                "name": "HTTP Contract Agent",
                "vicidial_user": "HTTP6101",
                "tenant_id": "COD",
                "phone_login": "6101",
                "odoo_user_id": cls.user.id,
                "campaign_ids": [(6, 0, [cls.campaign.id])],
            }
        )
        params = cls.env["ir.config_parameter"].sudo()
        params.set_param("codestra.webhook_secret", cls.secret)
        params.set_param("codestra.call_control.tenant_ids", "COD")

    def payload(
        self,
        event_id=None,
        event_type="call.created",
        sequence=0,
        **values,
    ):
        event_id = event_id or f"http-event-{uuid.uuid4()}"
        call_id = values.pop("call_id", f"http-call-{uuid.uuid4()}")
        result = {
            "schema_version": "1.0",
            "event_id": event_id,
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "correlation_id": f"corr-{call_id}",
            "tenant_id": "COD",
            "business_unit_id": "COD",
            "campaign_id": "HTTP_CONTRACT",
            "call_id": call_id,
            "asterisk_uniqueid": f"uid-{call_id}",
            "linkedid": f"linked-{call_id}",
            "agent_id": "HTTP6101",
            "extension": "6101",
            "sequence": sequence,
            "keycloak_subject": self.subject,
            "direction": "inbound",
            "caller_number": "+18095550100",
        }
        result.update(values)
        return result

    def post(
        self,
        payload=None,
        *,
        body=None,
        secret=None,
        event_id=None,
        headers=True,
        tenant_header=None,
    ):
        raw = (
            body
            if body is not None
            else json.dumps(payload, separators=(",", ":")).encode()
        )
        request_headers = {"Content-Type": "application/json"}
        if headers:
            timestamp = str(int(time.time()))
            signature = hmac.new(
                (self.secret if secret is None else secret).encode(),
                timestamp.encode() + b"." + raw,
                hashlib.sha256,
            ).hexdigest()
            request_headers.update(
                {
                    "X-Codestra-Timestamp": timestamp,
                    "X-Codestra-Signature": signature,
                    "X-Codestra-Event-ID": (
                        event_id
                        or (payload and payload.get("event_id"))
                        or "raw-event"
                    ),
                }
            )
            if tenant_header is not None:
                request_headers["X-Codestra-Tenant-ID"] = tenant_header
        return self.url_open(
            "/codestra/api/v1/call-events",
            data=raw,
            headers=request_headers,
            timeout=20,
        )

    def get_event(
        self,
        event_id,
        *,
        secret=None,
        header_event_id=None,
        tenant_id="COD",
        headers=True,
    ):
        request_headers = {}
        if headers:
            timestamp = str(int(time.time()))
            signature = hmac.new(
                (self.secret if secret is None else secret).encode(),
                timestamp.encode() + b".",
                hashlib.sha256,
            ).hexdigest()
            request_headers.update(
                {
                    "X-Codestra-Timestamp": timestamp,
                    "X-Codestra-Signature": signature,
                    "X-Codestra-Event-ID": (
                        header_event_id
                        if header_event_id is not None
                        else event_id
                    ),
                }
            )
            if tenant_id is not None:
                request_headers["X-Codestra-Tenant-ID"] = tenant_id
        return self.url_open(
            f"/codestra/api/v1/call-events/{event_id}",
            headers=request_headers,
            timeout=20,
        )

    def test_valid_auth_and_duplicate_replay(self):
        payload = self.payload()
        accepted = self.post(payload)
        self.assertEqual(accepted.status_code, 202)
        duplicate = self.post(payload)
        self.assertEqual(duplicate.status_code, 200)
        self.assertTrue(duplicate.json()["duplicate"])

    def test_missing_and_invalid_auth(self):
        payload = self.payload()
        self.assertEqual(self.post(payload, headers=False).status_code, 403)
        self.assertEqual(
            self.post(payload, secret="wrong-secret").status_code,
            403,
        )

    def test_tenant_campaign_and_subject_scope(self):
        for changed in (
            {"tenant_id": "OTHER"},
            {"campaign_id": "OTHER"},
            {"keycloak_subject": str(uuid.uuid4())},
        ):
            with self.subTest(changed=changed):
                self.assertEqual(
                    self.post(self.payload(**changed)).status_code,
                    403,
                )

    def test_header_tenant_must_match_the_signed_call_body(self):
        payload = self.payload()
        self.assertEqual(
            self.post(payload, tenant_header="OTHER").status_code,
            403,
        )
        self.assertEqual(
            self.post(payload, tenant_header="COD").status_code,
            202,
        )

    def test_malformed_missing_correlation_and_bad_timestamp(self):
        self.assertEqual(
            self.post(body=b"not-json", event_id="raw-event").status_code,
            400,
        )
        missing = self.payload()
        missing.pop("correlation_id")
        self.assertEqual(self.post(missing).status_code, 400)
        self.assertEqual(
            self.post(self.payload(timestamp="yesterday")).status_code,
            400,
        )

    def test_oversized_request(self):
        payload = self.payload(extra="x" * 262144)
        self.assertEqual(self.post(payload).status_code, 400)

    def test_unknown_terminal_call(self):
        payload = self.payload(
            event_type="call.completed",
            sequence=4,
        )
        self.assertEqual(self.post(payload).status_code, 404)

    def test_out_of_order_and_conflicting_replay(self):
        call_id = f"ordered-{uuid.uuid4()}"
        created = self.payload(call_id=call_id, sequence=0)
        self.assertEqual(self.post(created).status_code, 202)
        ringing = self.payload(
            call_id=call_id,
            event_type="call.ringing",
            sequence=2,
        )
        self.assertEqual(self.post(ringing).status_code, 202)
        stale = self.payload(
            call_id=call_id,
            event_type="call.offered",
            sequence=1,
        )
        stale_response = self.post(stale)
        self.assertEqual(stale_response.status_code, 202)
        self.assertFalse(stale_response.json()["applied"])
        conflict = dict(ringing, caller_number="+18095550999")
        self.assertEqual(self.post(conflict).status_code, 409)

    def test_readback_returns_exact_applied_event_identity(self):
        payload = self.payload(sequence=1)
        self.assertEqual(
            self.post(payload, tenant_header="COD").status_code,
            202,
        )
        response = self.get_event(payload["event_id"])
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["event_id"], payload["event_id"])
        self.assertEqual(result["event_type"], payload["event_type"])
        self.assertEqual(result["call_id"], payload["call_id"])
        self.assertEqual(result["sequence"], payload["sequence"])
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")

    def test_readback_is_fail_closed_by_event_and_tenant_identity(self):
        payload = self.payload()
        self.assertEqual(
            self.post(payload, tenant_header="COD").status_code,
            202,
        )
        event_id = payload["event_id"]
        self.assertEqual(
            self.get_event(event_id, headers=False).status_code,
            403,
        )
        self.assertEqual(
            self.get_event(event_id, secret="wrong-secret").status_code,
            403,
        )
        self.assertEqual(
            self.get_event(
                event_id,
                header_event_id="another-event",
            ).status_code,
            403,
        )
        self.assertEqual(
            self.get_event(event_id, tenant_id=None).status_code,
            403,
        )
        self.assertEqual(
            self.get_event(event_id, tenant_id="OTHER").status_code,
            403,
        )

    def test_readback_404_proves_non_delivery(self):
        missing = f"missing-event-{uuid.uuid4()}"
        self.assertEqual(self.get_event(missing).status_code, 404)
