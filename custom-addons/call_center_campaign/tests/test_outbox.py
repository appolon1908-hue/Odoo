import hashlib
import json
import importlib.util
from pathlib import Path
import uuid
from unittest.mock import MagicMock, patch

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged
from psycopg2 import IntegrityError


@tagged("post_install", "-at_install")
class TestCampaignTransactionalOutbox(TransactionCase):
    def setUp(self):
        super().setUp()
        self.unit = self.env.ref("call_center_core.business_unit_digital")
        self.values = {
            "name": "Synthetic Outbox Campaign",
            "code": f"COD-TEST-{uuid.uuid4().hex[:8].upper()}-OUT",
            "business_unit_id": self.unit.id,
            "direction": "outbound",
            "purpose_code": "TEST",
            "design_automation_enabled": True,
        }

    def _create_campaign(self, **changes):
        return self.env["call.center.campaign"].create(
            {**self.values, **changes}
        )

    def test_campaign_create_writes_one_canonical_event(self):
        campaign = self._create_campaign()
        events = self.env["codestra.runtime.integration.outbox"].sudo().search(
            [("campaign_id", "=", campaign.id)]
        )
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.event_type, "campaign.design.requested.v1")
        self.assertEqual(event.design_request_revision, 1)
        self.assertEqual(event.delivery_state, "pending")
        self.assertEqual(event.record_environment, "STAGING")
        self.assertEqual(event.payload_json["integration_uuid"], campaign.integration_uuid)
        canonical = json.dumps(
            event.payload_json, sort_keys=True, separators=(",", ":")
        ).encode()
        self.assertEqual(event.payload_hash, hashlib.sha256(canonical).hexdigest())
        self.assertEqual(
            event.payload_json["design_configuration"]["time_zone"],
            campaign.timezone,
        )
        self.assertEqual(
            event.payload_json["design_configuration"]["calling_hour_start"],
            campaign.calling_hour_start,
        )
        self.assertNotIn("phone", event.payload_json)
        self.assertNotIn("password", event.payload_json)

    def test_campaign_and_event_rollback_together(self):
        marker = self.values["code"]
        before = self.env["codestra.runtime.integration.outbox"].sudo().search_count([])
        with (
            self.assertRaisesRegex(RuntimeError, "synthetic rollback"),
            self.env.cr.savepoint(),
        ):
            self._create_campaign()
            raise RuntimeError("synthetic rollback")
        self.assertFalse(
            self.env["call.center.campaign"].search([("code", "=", marker)])
        )
        self.assertFalse(
            self.env["codestra.runtime.integration.outbox"].sudo().search_count([]) != before
        )

    def test_generic_business_event_uses_current_transaction(self):
        campaign = self._create_campaign()
        parameters = self.env["ir.config_parameter"].sudo()
        parameters.set_param("codestra.integration.environment", "TEST")
        parameters.set_param(
            "codestra.integration.organization_public_id", "ORG-TEST"
        )
        event_key = f"generic-{uuid.uuid4()}"
        before = self.env["codestra.runtime.integration.outbox"].sudo().search_count(
            [("deterministic_event_key", "like", f"%{event_key}")]
        )
        with (
            self.assertRaisesRegex(RuntimeError, "synthetic rollback"),
            self.env.cr.savepoint(),
        ):
            self.env["codestra.runtime.integration.outbox"].create_event(
                event_type="campaign.configuration.changed",
                aggregate=campaign,
                aggregate_version=2,
                payload={"synthetic": True},
                correlation_id=str(uuid.uuid4()),
                idempotency_key=event_key,
            )
            raise RuntimeError("synthetic rollback")
        self.assertEqual(
            self.env["codestra.runtime.integration.outbox"].sudo().search_count(
                [("deterministic_event_key", "like", f"%{event_key}")]
            ),
            before,
        )

    def test_generic_business_event_is_idempotent_and_immutable(self):
        campaign = self._create_campaign()
        parameters = self.env["ir.config_parameter"].sudo()
        parameters.set_param("codestra.integration.environment", "TEST")
        parameters.set_param(
            "codestra.integration.organization_public_id", "ORG-TEST"
        )
        values = {
            "event_type": "campaign.configuration.changed",
            "aggregate": campaign,
            "aggregate_version": 2,
            "payload": {"synthetic": True},
            "correlation_id": str(uuid.uuid4()),
            "idempotency_key": f"generic-{uuid.uuid4()}",
        }
        first = self.env["codestra.runtime.integration.outbox"].create_event(**values)
        duplicate = self.env["codestra.runtime.integration.outbox"].create_event(**values)
        self.assertEqual(first, duplicate)
        self.assertEqual(first.aggregate_record_id, campaign.id)
        self.assertEqual(first.organization_public_id, "ORG-TEST")
        self.assertEqual(first.record_environment, "TEST")
        self.assertEqual(first.idempotency_key, values["idempotency_key"])
        with self.assertRaisesRegex(
            ValidationError, "IMMUTABLE_EVENT_BINDING_CONFLICT"
        ):
            self.env["codestra.runtime.integration.outbox"].create_event(
                **{**values, "payload": {"synthetic": False}}
            )

    def test_retry_same_revision_is_idempotent(self):
        campaign = self._create_campaign()
        first = self.env["codestra.runtime.integration.outbox"].sudo().search(
            [("campaign_id", "=", campaign.id)]
        )
        replay = campaign._create_design_request_event(revision=1)
        self.assertEqual(replay, first)
        self.assertEqual(
            self.env["codestra.runtime.integration.outbox"].sudo().search_count(
                [("campaign_id", "=", campaign.id)]
            ),
            1,
        )

    def test_design_change_creates_revision_and_unrelated_change_does_not(self):
        campaign = self._create_campaign()
        campaign.write({"target_audience": "Synthetic, non-customer fixture"})
        self.assertEqual(campaign.design_request_revision, 1)
        campaign.write({"purpose_code": "REVISED"})
        self.assertEqual(campaign.design_request_revision, 2)
        events = self.env["codestra.runtime.integration.outbox"].sudo().search(
            [("campaign_id", "=", campaign.id)], order="design_request_revision"
        )
        self.assertEqual(events.mapped("design_request_revision"), [1, 2])
        self.assertNotEqual(events[0].payload_hash, events[1].payload_hash)

    def test_enabling_existing_campaign_creates_initial_event(self):
        campaign = self._create_campaign(design_automation_enabled=False)
        self.assertFalse(campaign.integration_uuid)
        campaign.write({"design_automation_enabled": True})
        event = self.env["codestra.runtime.integration.outbox"].sudo().search(
            [("campaign_id", "=", campaign.id)]
        )
        self.assertTrue(campaign.integration_uuid)
        self.assertEqual(len(event), 1)
        self.assertEqual(campaign.design_request_revision, 1)

    def test_invalid_scope_rolls_back_campaign_and_event(self):
        with self.assertRaises(ValidationError):
            self._create_campaign(purpose_code="")

    def test_outbox_payload_and_state_are_protected(self):
        campaign = self._create_campaign()
        event = self.env["codestra.runtime.integration.outbox"].sudo().search(
            [("campaign_id", "=", campaign.id)], limit=1
        )
        with self.assertRaises(AccessError):
            event.write({"payload_hash": "0" * 64})
        with self.assertRaises(AccessError):
            event.write({"delivery_state": "processing"})
        with self.assertRaises(ValidationError):
            event._worker_write({"delivery_state": "delivered"})
        event._worker_write({"delivery_state": "processing"})
        event._worker_write({"delivery_state": "failed", "retry_count": 1})
        event._worker_write({"delivery_state": "dead_letter"})
        with self.assertRaises(AccessError):
            event.unlink()

    def test_claim_uses_database_lock_and_claims_once(self):
        campaign = self._create_campaign()
        first = self.env["codestra.runtime.integration.outbox"]._claim_batch(limit=1)
        second = self.env["codestra.runtime.integration.outbox"]._claim_batch(limit=1)
        self.assertEqual(first.campaign_id, campaign)
        self.assertFalse(second)

    def test_stale_processing_claim_is_recovered(self):
        campaign = self._create_campaign()
        event = self.env["codestra.runtime.integration.outbox"]._claim_batch(limit=1)
        self.env.cr.execute(
            """
            UPDATE codestra_runtime_integration_outbox
               SET processing_started_at = now() - interval '6 minutes',
                   lease_expires_at = now() - interval '1 second'
             WHERE id = %s
            """,
            [event.id],
        )
        event.invalidate_recordset()
        recovered = self.env["codestra.runtime.integration.outbox"]._claim_batch(limit=1)
        self.assertEqual(recovered.campaign_id, campaign)
        self.assertEqual(recovered.event_uuid, event.event_uuid)

    def test_claim_issues_opaque_lease_and_rejects_stale_generation(self):
        campaign = self._create_campaign()
        event = self.env["codestra.runtime.integration.outbox"]._claim_batch(
            limit=1,
            consumer_id="test-worker",
            lease_ttl_seconds=30,
            record_environment="STAGING",
            business_unit_codes=[campaign.business_unit_id.code],
        )
        token = event._issued_lease_token()
        self.assertTrue(token)
        self.assertNotEqual(event.lease_token_hash, token)
        self.assertTrue(event._verify_lease("test-worker", token, 1))
        with self.assertRaisesRegex(ValidationError, "LEASE_GENERATION_MISMATCH"):
            event._verify_lease("test-worker", token, 0)

    def test_lease_renewal_and_release_require_exact_binding(self):
        campaign = self._create_campaign()
        event = self.env["codestra.runtime.integration.outbox"]._claim_batch(
            limit=1,
            consumer_id="test-worker",
            lease_ttl_seconds=30,
            record_environment="STAGING",
            business_unit_codes=[campaign.business_unit_id.code],
        )
        token = event._issued_lease_token()
        original_expiry = event.lease_expires_at
        event._renew_lease("test-worker", token, event.lease_generation, 60)
        self.assertGreater(event.lease_expires_at, original_expiry)
        event._release_lease("test-worker", token, event.lease_generation)
        self.assertEqual(event.delivery_state, "failed")
        self.assertFalse(event.lease_token_hash)

    def test_claim_scope_filters_before_locking(self):
        campaign = self._create_campaign()
        excluded = self.env["codestra.runtime.integration.outbox"]._claim_batch(
            limit=1,
            consumer_id="test-worker",
            record_environment="TEST",
            business_unit_codes=[campaign.business_unit_id.code],
        )
        self.assertFalse(excluded)
        event = self.env["codestra.runtime.integration.outbox"]._claim_batch(
            limit=1,
            consumer_id="test-worker",
            record_environment="STAGING",
            business_unit_codes=[campaign.business_unit_id.code],
        )
        self.assertEqual(event.campaign_id, campaign)

    def test_direct_outbox_create_and_campaign_state_mutation_are_denied(self):
        campaign = self._create_campaign()
        with self.assertRaises(AccessError):
            self.env["codestra.runtime.integration.outbox"].create({})
        with self.assertRaises(AccessError):
            self._create_campaign(provisioning_state="active")
        with self.assertRaises(AccessError):
            self._create_campaign(integration_uuid=str(uuid.uuid4()))
        with self.assertRaises(AccessError):
            campaign.write({"provisioning_state": "active"})
        with self.assertRaises(AccessError):
            campaign.with_context(codestra_outbox_status=True).write(
                {"provisioning_state": "active"}
            )
        with self.assertRaises(AccessError):
            campaign.with_context(codestra_design_producer=True).write(
                {"integration_uuid": str(uuid.uuid4())}
            )

    def test_outbox_record_rule_is_business_unit_scoped(self):
        rule = self.env.ref("call_center_campaign.rule_integration_outbox_unit")
        self.assertIn("campaign_id.business_unit_id", rule.domain_force)
        self.assertIn("call_center_business_unit_ids", rule.domain_force)

    def test_event_uuid_and_event_key_constraints(self):
        campaign = self._create_campaign()
        event = self.env["codestra.runtime.integration.outbox"].sudo().search(
            [("campaign_id", "=", campaign.id)], limit=1
        )
        duplicate = {
            field: event[field]
            for field in (
                "event_uuid",
                "deterministic_event_key",
                "event_type",
                "schema_version",
                "aggregate_type",
                "aggregate_uuid",
                "integration_uuid",
                "business_unit_code",
                "design_request_revision",
                "payload_json",
                "payload_hash",
                "correlation_id",
            )
        }
        duplicate["campaign_id"] = campaign.id
        with self.assertRaises(IntegrityError):
            self.env["codestra.runtime.integration.outbox"].sudo()._create_internal(duplicate)

    def test_successful_delivery_finalizes_confirmed_revision(self):
        campaign = self._create_campaign()
        event = self.env["codestra.runtime.integration.outbox"]._claim_batch(limit=1)
        result = {"manifest_hash": "a" * 64, "design_revision": 7}
        event._finalize_delivery_success(result)
        self.assertEqual(event.delivery_state, "delivered")
        self.assertEqual(campaign.middleware_design_revision, 7)
        self.assertEqual(campaign.design_request_state, "delivered")

    def test_older_delivery_does_not_overwrite_newer_revision_status(self):
        campaign = self._create_campaign()
        first = self.env["codestra.runtime.integration.outbox"]._claim_batch(limit=1)
        campaign.write({"purpose_code": "REVISED"})
        self.assertEqual(campaign.design_request_revision, 2)
        self.assertEqual(campaign.design_request_state, "pending")
        first._finalize_delivery_success(
            {"manifest_hash": "d" * 64, "design_revision": 1}
        )
        self.assertEqual(first.delivery_state, "delivered")
        self.assertEqual(campaign.design_request_state, "pending")
        self.assertFalse(campaign.middleware_design_revision)

    def test_timeout_backoff_and_dead_letter_limit(self):
        campaign = self._create_campaign()
        event = self.env["codestra.runtime.integration.outbox"]._claim_batch(limit=1)
        for attempt in range(1, 6):
            terminal = event._finalize_delivery_failure(TimeoutError())
            self.assertEqual(event.retry_count, attempt)
            if attempt < 5:
                self.assertFalse(terminal)
                self.assertEqual(event.delivery_state, "failed")
                event._worker_write({"delivery_state": "processing"})
        self.assertTrue(terminal)
        self.assertEqual(event.delivery_state, "dead_letter")
        self.assertEqual(campaign.design_request_state, "dead_letter")
        self.assertNotIn("timeout", (event.last_error_fingerprint or "").lower())

    def test_crash_after_middleware_success_reuses_same_idempotency_identity(self):
        campaign = self._create_campaign()
        event = self.env["codestra.runtime.integration.outbox"]._claim_batch(limit=1)
        original_identity = (event.event_uuid, event.correlation_id, event.payload_hash)
        middleware_result = {"manifest_hash": "b" * 64, "design_revision": 3}
        first_result = middleware_result
        # Synthetic crash: no local finalization occurs after the committed response.
        self.assertEqual(event.delivery_state, "processing")
        replay_result = middleware_result
        event._finalize_delivery_success(replay_result)
        self.assertEqual(first_result, replay_result)
        self.assertEqual(
            (event.event_uuid, event.correlation_id, event.payload_hash),
            original_identity,
        )
        self.assertEqual(campaign.middleware_design_revision, 3)

    def test_http_delivery_uses_tls_and_event_uuid_idempotency(self):
        campaign = self._create_campaign()
        event = self.env["codestra.runtime.integration.outbox"].sudo().search(
            [("campaign_id", "=", campaign.id)], limit=1
        )
        response = MagicMock()
        response.read.return_value = json.dumps(
            {"manifest_hash": "c" * 64, "design_revision": 1}
        ).encode()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        with (
            patch.dict("os.environ", {"CODESTRA_MIDDLEWARE_CAMPAIGN_TENANTS": json.dumps({event.business_unit_code: "campaign-design-test"})}),
            patch.object(
                type(event),
                "_middleware_configuration",
                return_value=(
                    "https://middleware.private.example/api/v1/campaign-designs/preview",
                    "synthetic-token",
                ),
            ),
            patch(
                "odoo.addons.call_center_campaign.models.outbox.request.urlopen",
                return_value=response,
            ) as urlopen,
        ):
            result = event._send_to_middleware()
        outbound = urlopen.call_args.args[0]
        self.assertEqual(outbound.headers["Idempotency-key"], event.event_uuid)
        self.assertEqual(outbound.headers["X-correlation-id"], event.correlation_id)
        self.assertEqual(outbound.headers["X-tenant-id"], "campaign-design-test")
        self.assertEqual(result["design_revision"], 1)

    def test_non_object_middleware_response_is_rejected(self):
        campaign = self._create_campaign()
        event = self.env["codestra.runtime.integration.outbox"].sudo().search(
            [("campaign_id", "=", campaign.id)], limit=1
        )
        response = MagicMock()
        response.read.return_value = b"[]"
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        with (
            patch.dict("os.environ", {"CODESTRA_MIDDLEWARE_CAMPAIGN_TENANTS": json.dumps({event.business_unit_code: "campaign-design-test"})}),
            patch.object(
                type(event),
                "_middleware_configuration",
                return_value=(
                    "https://middleware.private.example/api/v1/campaign-designs/preview",
                    "synthetic-token",
                ),
            ),
            patch(
                "odoo.addons.call_center_campaign.models.outbox.request.urlopen",
                return_value=response,
            ),
            self.assertRaisesRegex(ValidationError, "JSON object"),
        ):
            event._send_to_middleware()

    def test_malformed_middleware_revision_is_rejected(self):
        campaign = self._create_campaign()
        event = self.env["codestra.runtime.integration.outbox"].sudo().search(
            [("campaign_id", "=", campaign.id)], limit=1
        )
        response = MagicMock()
        response.read.return_value = json.dumps(
            {"manifest_hash": "e" * 64, "design_revision": {"value": 7}}
        ).encode()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        with (
            patch.dict("os.environ", {"CODESTRA_MIDDLEWARE_CAMPAIGN_TENANTS": json.dumps({event.business_unit_code: "campaign-design-test"})}),
            patch.object(
                type(event),
                "_middleware_configuration",
                return_value=(
                    "https://middleware.private.example/api/v1/campaign-designs/preview",
                    "synthetic-token",
                ),
            ),
            patch(
                "odoo.addons.call_center_campaign.models.outbox.request.urlopen",
                return_value=response,
            ),
            self.assertRaisesRegex(ValidationError, "committed design revision"),
        ):
            event._send_to_middleware()

    def test_middleware_endpoint_rejects_credentials_and_query_parameters(self):
        outbox = self.env["codestra.runtime.integration.outbox"]
        for unsafe in (
            "https://user:secret@middleware.example/api/v1/campaign-designs/preview",
            "https://middleware.example/api/v1/campaign-designs/preview?redirect=1",
        ):
            with (
                self.subTest(unsafe=unsafe),
                patch.dict(
                    "os.environ",
                    {
                        "CODESTRA_MIDDLEWARE_CAMPAIGN_DESIGN_URL": unsafe,
                        "CODESTRA_MIDDLEWARE_TOKEN_FILE": "/run/secrets/middleware",
                    },
                    clear=True,
                ),
                self.assertRaisesRegex(ValidationError, "exact HTTPS"),
            ):
                outbox._middleware_configuration()


    def test_campaign_tenant_binding_is_explicit_and_cannot_be_wildcard(self):
        campaign = self._create_campaign()
        event = self.env["codestra.runtime.integration.outbox"].sudo().search(
            [("campaign_id", "=", campaign.id)], limit=1)
        for mapping in ("{}", "[]", "not-json",
                        json.dumps({event.business_unit_code: "*"}),
                        json.dumps({event.business_unit_code: " tenant "})):
            with self.subTest(mapping=mapping), patch.dict(
                "os.environ", {"CODESTRA_MIDDLEWARE_CAMPAIGN_TENANTS": mapping}
            ), self.assertRaises(ValidationError):
                event._campaign_tenant_id()


    def test_configuration_blockers_preserve_retry_budget_through_cron(self):
        campaign = self._create_campaign()
        Outbox = self.env["codestra.runtime.integration.outbox"]
        event = Outbox.search([("campaign_id", "=", campaign.id)], limit=1)
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps({"manifest_hash": "a" * 64, "design_revision": 1}).encode()
        # Keep the TransactionCase fixture in its rollback-only transaction;
        # claims, transport classification and finalization use real ORM code.
        with (
            patch.object(self.env.cr, "commit"),
            patch.object(self.env.cr, "rollback"),
            patch.object(type(Outbox), "_middleware_configuration", return_value=(
                "https://middleware.example.test/api/v1/campaign-designs/preview", "synthetic-token"
            )),
            patch("odoo.addons.call_center_campaign.models.outbox.request.urlopen", return_value=response) as send,
        ):
            for mapping in ("{}", "not-json", "[]", "{}", "{}", "{}", "{}"):
                event._worker_write({"next_attempt_at": False})
                with patch.dict("os.environ", {"CODESTRA_MIDDLEWARE_CAMPAIGN_TENANTS": mapping}):
                    Outbox._cron_deliver_campaign_design_events()
                self.assertEqual(event.delivery_state, "failed")
                self.assertEqual(event.retry_count, 0)
                self.assertEqual(event.last_error_code, "CONFIGURATION_BLOCKED")
                self.assertFalse(event.lease_token_hash)
                self.assertTrue(event.next_attempt_at)
                self.assertEqual(campaign.design_request_state, "pending")
            send.assert_not_called()
            event._worker_write({"next_attempt_at": False})
            with patch.dict("os.environ", {"CODESTRA_MIDDLEWARE_CAMPAIGN_TENANTS": json.dumps({
                event.business_unit_code: "synthetic-tenant"
            })}):
                Outbox._cron_deliver_campaign_design_events()
            send.assert_called_once()
            self.assertEqual(event.delivery_state, "delivered")
            self.assertEqual(event.retry_count, 0)
            self.assertFalse(event.last_error_code)

    def test_configuration_failures_are_classified_before_delivery(self):
        from odoo.addons.call_center_campaign.models.outbox import CampaignDeliveryConfigurationError
        Outbox = self.env["codestra.runtime.integration.outbox"]
        with patch.dict("os.environ", {
            "CODESTRA_MIDDLEWARE_CAMPAIGN_DESIGN_URL": "https://middleware.example.test/api/v1/campaign-designs/preview",
            "CODESTRA_MIDDLEWARE_TOKEN_FILE": "/run/secrets/synthetic-missing",
        }), patch("builtins.open", side_effect=FileNotFoundError("sensitive-path")):
            with self.assertRaises(CampaignDeliveryConfigurationError) as raised:
                Outbox._middleware_configuration()
            self.assertNotIn("sensitive-path", str(raised.exception))
        with patch.dict("os.environ", {"CODESTRA_MIDDLEWARE_CAMPAIGN_DESIGN_URL": "http://bad.test/preview"}):
            with self.assertRaises(CampaignDeliveryConfigurationError):
                Outbox._middleware_configuration()

    def _legacy_preview_campaign(self):
        Outbox = self.env["codestra.runtime.integration.outbox"]
        original_create = type(Outbox)._create_internal

        def old_producer(records, values):
            values = dict(values)
            payload = dict(values["payload_json"])
            payload.pop("design_request_revision", None)
            values["payload_json"] = payload
            values["payload_hash"] = hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            return original_create(records, values)

        with patch.object(type(Outbox), "_create_internal", old_producer):
            campaign = self._create_campaign(code=f"COD-TEST-{uuid.uuid4().hex[:8].upper()}-OUT")
        return campaign, Outbox.search([("campaign_id", "=", campaign.id)], limit=1)

    def _run_preview_upgrade(self):
        path = Path(__file__).resolve().parents[1] / "migrations/19.0.5.3.4/post-migration.py"
        spec = importlib.util.spec_from_file_location("campaign_preview_upgrade_test", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        migration.migrate(self.env.cr, "19.0.5.3.2")
        self.env.invalidate_all()

    def test_upgrade_replaces_queued_legacy_previews_without_mutating_history(self):
        for state in ("pending", "failed", "dead_letter"):
            with self.subTest(state=state):
                campaign, old = self._legacy_preview_campaign()
                if state != "pending":
                    old._worker_write({"delivery_state": "processing"})
                    old._worker_write({"delivery_state": "failed", "retry_count": 4})
                if state == "dead_letter":
                    old._worker_write({"delivery_state": "dead_letter"})
                identity = (old.event_uuid, old.idempotency_key, old.payload_json, old.payload_hash)
                self._run_preview_upgrade()
                self.assertEqual(old.delivery_state, "superseded")
                self.assertEqual((old.event_uuid, old.idempotency_key, old.payload_json, old.payload_hash), identity)
                self.assertEqual(campaign.design_request_revision, 2)
                current = self.env["codestra.runtime.integration.outbox"].search([
                    ("campaign_id", "=", campaign.id), ("design_request_revision", "=", 2),
                ])
                self.assertEqual(current.delivery_state, "pending")
                self.assertEqual(current.payload_json["design_request_revision"], 2)
                self.assertNotEqual(current.event_uuid, old.event_uuid)
                self.assertNotEqual(current.idempotency_key, old.idempotency_key)
                self.assertNotEqual(current.payload_hash, old.payload_hash)
                revisions = self.env["call.center.campaign.design.revision"].search([
                    ("campaign_id", "=", campaign.id),
                ])
                if revisions:
                    self.assertEqual(revisions.filtered(lambda r: r.revision == 1).state, "superseded")
                    self.assertEqual(revisions.filtered(lambda r: r.revision == 2).request_payload_hash, current.payload_hash)
                self._run_preview_upgrade()
                self.assertEqual(campaign.design_request_revision, 2)
                self.assertEqual(self.env["codestra.runtime.integration.outbox"].search_count([
                    ("campaign_id", "=", campaign.id),
                ]), 2)

    def test_upgrade_leaves_delivered_and_newer_valid_previews_unchanged(self):
        campaign, old = self._legacy_preview_campaign()
        old._worker_write({"delivery_state": "processing"})
        old._finalize_delivery_success({"manifest_hash": "a" * 64, "design_revision": 1})
        self._run_preview_upgrade()
        self.assertEqual(old.delivery_state, "delivered")
        self.assertEqual(campaign.design_request_revision, 1)
        campaign, old = self._legacy_preview_campaign()
        newer = campaign._create_design_request_event()
        identity = (newer.event_uuid, newer.payload_hash, newer.delivery_state)
        self._run_preview_upgrade()
        self.assertEqual(old.delivery_state, "superseded")
        self.assertEqual(campaign.design_request_revision, 2)
        self.assertEqual((newer.event_uuid, newer.payload_hash, newer.delivery_state), identity)

    def test_upgrade_refuses_processing_legacy_requests_and_rolls_back(self):
        campaign, old = self._legacy_preview_campaign()
        old._worker_write({"delivery_state": "processing"})
        with self.assertRaisesRegex(ValidationError, "Reconcile processing"), self.env.cr.savepoint():
            self._run_preview_upgrade()
        self.assertEqual(old.delivery_state, "processing")
        self.assertEqual(campaign.design_request_revision, 1)

    def test_upgrade_replacement_failure_rolls_back_supersession(self):
        campaign, old = self._legacy_preview_campaign()
        with (
            self.assertRaisesRegex(ValidationError, "synthetic upgrade failure"),
            self.env.cr.savepoint(),
            patch.object(type(campaign), "_create_design_request_event", side_effect=ValidationError("synthetic upgrade failure")),
        ):
            self._run_preview_upgrade()
        self.assertEqual(old.delivery_state, "pending")
        self.assertEqual(campaign.design_request_revision, 1)
