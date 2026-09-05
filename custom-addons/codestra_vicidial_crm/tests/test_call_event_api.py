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

    def payload(self, event_id=None, event_type="call.created", sequence=0, **values):
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

    def post(self, payload=None, *, body=None, secret=None, event_id=None, headers=True):
        raw = body if body is not None else json.dumps(payload, separators=(",", ":")).encode()
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
                    "X-Codestra-Event-ID": event_id or (payload and payload.get("event_id")) or "raw-event",
                }
            )
        return self.url_open(
            "/codestra/api/v1/call-events",
            data=raw,
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
        self.assertEqual(self.post(payload, secret="wrong-secret").status_code, 403)

    def test_tenant_campaign_and_subject_scope(self):
        for changed in (
            {"tenant_id": "OTHER"},
            {"campaign_id": "OTHER"},
            {"keycloak_subject": str(uuid.uuid4())},
        ):
            with self.subTest(changed=changed):
                self.assertEqual(self.post(self.payload(**changed)).status_code, 403)

    def test_malformed_missing_correlation_and_bad_timestamp(self):
        self.assertEqual(self.post(body=b"not-json", event_id="raw-event").status_code, 400)
        missing = self.payload()
        missing.pop("correlation_id")
        self.assertEqual(self.post(missing).status_code, 400)
        self.assertEqual(self.post(self.payload(timestamp="yesterday")).status_code, 400)

    def test_oversized_request(self):
        payload = self.payload(extra="x" * 262144)
        self.assertEqual(self.post(payload).status_code, 400)

    def test_unknown_terminal_call(self):
        payload = self.payload(event_type="call.completed", sequence=4)
        self.assertEqual(self.post(payload).status_code, 404)

    def test_out_of_order_and_conflicting_replay(self):
        call_id = f"ordered-{uuid.uuid4()}"
        created = self.payload(call_id=call_id, sequence=0)
        self.assertEqual(self.post(created).status_code, 202)
        ringing = self.payload(call_id=call_id, event_type="call.ringing", sequence=2)
        self.assertEqual(self.post(ringing).status_code, 202)
        stale = self.payload(call_id=call_id, event_type="call.offered", sequence=1)
        stale_response = self.post(stale)
        self.assertEqual(stale_response.status_code, 202)
        self.assertFalse(stale_response.json()["applied"])
        conflict = dict(ringing, caller_number="+18095550999")
        self.assertEqual(self.post(conflict).status_code, 409)

    def test_created_event_claims_timeout_placeholder_by_correlation(self):
        call_id = f"timeout-{uuid.uuid4()}"
        correlation_id = f"corr-{call_id}"
        placeholder = self.env["codestra.vicidial.call"].create(
            {
                "name": "Timeout placeholder",
                "agent_id": self.env["codestra.vicidial.agent"].search(
                    [("vicidial_user", "=", "HTTP6101")], limit=1
                ).id,
                "campaign_id": self.campaign.id,
                "tenant_id": "COD",
                "keycloak_subject": self.subject,
                "extension": "6101",
                "correlation_id": correlation_id,
                "idempotency_key": correlation_id,
                "state": "initiating",
                "status": "outcome_unknown",
            }
        )
        payload = self.payload(call_id=call_id, correlation_id=correlation_id)
        self.assertEqual(self.post(payload).status_code, 202)
        placeholder.invalidate_recordset()
        self.assertEqual(placeholder.call_id, call_id)
        self.assertEqual(
            self.env["codestra.vicidial.call"].search_count(
                [("correlation_id", "=", correlation_id)]
            ),
            1,
        )

    def test_answered_event_advances_initiating_placeholder(self):
        call_id = f"answered-{uuid.uuid4()}"
        correlation_id = f"corr-{call_id}"
        placeholder = self.env["codestra.vicidial.call"].create(
            {
                "name": "Answered timeout placeholder",
                "agent_id": self.env["codestra.vicidial.agent"].search(
                    [("vicidial_user", "=", "HTTP6101")], limit=1
                ).id,
                "campaign_id": self.campaign.id,
                "tenant_id": "COD",
                "keycloak_subject": self.subject,
                "extension": "6101",
                "correlation_id": correlation_id,
                "idempotency_key": correlation_id,
                "state": "initiating",
                "status": "outcome_unknown",
            }
        )
        payload = self.payload(
            call_id=call_id,
            correlation_id=correlation_id,
            event_type="call.answered",
            sequence=2,
        )
        self.assertEqual(self.post(payload).status_code, 202)
        placeholder.invalidate_recordset()
        self.assertEqual(placeholder.state, "answering")

        completed = self.payload(
            call_id=call_id,
            correlation_id=correlation_id,
            event_type="call.completed",
            sequence=3,
        )
        self.assertEqual(self.post(completed).status_code, 202)
        placeholder.invalidate_recordset()
        self.assertEqual(placeholder.state, "completed")

    def test_event_populates_asterisk_identity_on_accepted_reservation(self):
        call_id = f"accepted-{uuid.uuid4()}"
        correlation_id = f"corr-{call_id}"
        reservation = self.env["codestra.vicidial.call"].create(
            {
                "name": "Accepted originate reservation",
                "call_id": call_id,
                "external_call_id": call_id,
                "agent_id": self.env["codestra.vicidial.agent"].search(
                    [("vicidial_user", "=", "HTTP6101")], limit=1
                ).id,
                "campaign_id": self.campaign.id,
                "tenant_id": "COD",
                "keycloak_subject": self.subject,
                "extension": "6101",
                "correlation_id": correlation_id,
                "idempotency_key": correlation_id,
                "state": "initiating",
                "status": "attempting",
            }
        )
        payload = self.payload(call_id=call_id, correlation_id=correlation_id)
        self.assertEqual(self.post(payload).status_code, 202)
        reservation.invalidate_recordset()
        self.assertEqual(reservation.asterisk_uniqueid, payload["asterisk_uniqueid"])
        self.assertEqual(reservation.linkedid, payload["linkedid"])
        self.assertEqual(reservation.source_system, "asterisk")

    def test_terminal_event_can_claim_placeholder_with_asterisk_identity(self):
        call_id = f"terminal-{uuid.uuid4()}"
        correlation_id = f"corr-{call_id}"
        placeholder = self.env["codestra.vicidial.call"].create(
            {
                "name": "Terminal timeout placeholder",
                "agent_id": self.env["codestra.vicidial.agent"].search(
                    [("vicidial_user", "=", "HTTP6101")], limit=1
                ).id,
                "campaign_id": self.campaign.id,
                "tenant_id": "COD",
                "keycloak_subject": self.subject,
                "extension": "6101",
                "correlation_id": correlation_id,
                "idempotency_key": correlation_id,
                "state": "initiating",
                "status": "outcome_unknown",
            }
        )
        payload = self.payload(
            call_id=call_id,
            correlation_id=correlation_id,
            event_type="call.completed",
            sequence=4,
        )
        self.assertEqual(self.post(payload).status_code, 202)
        placeholder.invalidate_recordset()
        self.assertEqual(placeholder.state, "completed")
        self.assertEqual(placeholder.asterisk_uniqueid, payload["asterisk_uniqueid"])
        self.assertEqual(placeholder.linkedid, payload["linkedid"])
