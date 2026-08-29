from copy import deepcopy
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.codestra_cc_vicidial.models.telephony_mapping import (
    CATALOG_COLUMNS,
    CATALOG_NORMALIZED_SHA256,
    _catalog_rows,
)


@tagged("post_install", "-at_install")
class TestCodestraCcVicidialBoundary(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Mapping = cls.env["cc.telephony.mapping"].with_context(active_test=False)
        cls.Readback = cls.env["cc.telephony.readback"]
        cls.Contract = cls.env["cc.telephony.middleware.contract"]
        cls.identity_managed = "cc.identity.outbox" in cls.env
        cls.mapping_a = cls.Mapping.search(
            [("canonical_campaign_code", "=", "COD-WEB-OUT")], limit=1
        )
        cls.mapping_b = cls.Mapping.search(
            [("campaign_id", "!=", cls.mapping_a.campaign_id.id)], limit=1
        )
        cls.requester = cls._create_user(
            "Telephony Access Requester",
            "telephony-access-requester@example.invalid",
            ["codestra_cc_security.group_cc_global_administrator"],
        )
        cls.approver = cls._create_user(
            "Telephony Access Approver",
            "telephony-access-approver@example.invalid",
            ["codestra_cc_security.group_cc_global_administrator"],
        )
        cls.supervisor_a = cls._create_user(
            "Telephony Supervisor A",
            "telephony-supervisor-a@example.invalid",
            ["codestra_cc_security.group_cc_campaign_supervisor"],
        )
        cls.supervisor_b = cls._create_user(
            "Telephony Supervisor B",
            "telephony-supervisor-b@example.invalid",
            ["codestra_cc_security.group_cc_campaign_supervisor"],
        )
        cls.service = cls._create_user(
            "Telephony Read-back Service",
            "telephony-readback-service@example.invalid",
            ["codestra_cc_vicidial.group_cc_telephony_readback_service"],
        )
        cls.identity_service = False
        if cls.identity_managed:
            cls.identity_service = cls._create_user(
                "Telephony Identity Service",
                "telephony-identity-service@example.invalid",
                ["codestra_identity_provisioning.group_provisioning_service"],
            )
        cls._activate_supervisor(
            cls.supervisor_a, cls.mapping_a.campaign_id, "TEL-SCOPE-A"
        )
        cls._activate_supervisor(
            cls.supervisor_b, cls.mapping_b.campaign_id, "TEL-SCOPE-B"
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
    def _activate_supervisor(cls, user, campaign, ticket):
        employee = cls.env["hr.employee"].create(
            {"name": user.name, "user_id": user.id, "company_id": cls.env.company.id}
        )
        values = {
                "user_id": user.id,
                "employee_id": employee.id,
                "campaign_id": campaign.id,
                "role": "supervisor",
                "state": "pending_sync",
                "is_primary_supervisor": True,
                "requested_by_id": cls.requester.id,
                "source_ticket": ticket,
                "starts_at": fields.Datetime.now(),
                "last_sync_status": "matched",
                "read_back_evidence": f"staging://vicidial/{ticket.lower()}",
        }
        if cls.identity_managed:
            values["state"] = "draft"
            values.pop("last_sync_status")
            values.pop("read_back_evidence")
        membership = cls.env["cc.campaign.membership"].with_user(cls.requester).create(values)
        if cls.identity_managed:
            membership.with_user(cls.requester).action_submit_identity()
            operation = membership.with_user(cls.approver).action_approve_identity()
            operation.with_user(cls.identity_service).action_record_readback(
                {
                    target: {"status": "matched", "evidence_hash": "f" * 64}
                    for target in operation.required_targets
                },
                f"staging://vicidial/{ticket.lower()}/identity-readback",
            )
        membership.with_user(cls.approver).action_activate()
        return membership

    def test_dependencies_are_installed(self):
        expected = {
            "codestra_cc_core",
            "codestra_cc_reliability",
            "codestra_vicidial_crm",
            "codestra_vicidial_connector",
            "codestra_telephony_bridge",
            "codestra_vicidial_recording",
        }
        modules = self.env["ir.module.module"].search([("name", "in", sorted(expected))])
        self.assertEqual(set(modules.mapped("name")), expected)
        self.assertEqual(set(modules.mapped("state")), {"installed"})

    def test_controlled_catalog_is_exact_partial_and_fail_closed(self):
        mappings = self.Mapping.search([])
        self.assertEqual(len(mappings), 93)
        self.assertEqual(len(set(mappings.mapped("mapping_uuid"))), 93)
        self.assertEqual(len(set(mappings.mapped("canonical_campaign_code"))), 93)
        self.assertEqual(len(set(mappings.mapped("vicidial_campaign_id"))), 93)
        self.assertTrue(all(len(native_id) <= 8 for native_id in mappings.mapped("vicidial_campaign_id")))
        self.assertEqual(set(mappings.mapped("catalog_status")), {"partial"})
        self.assertEqual(set(mappings.mapped("catalog_sha256")), {CATALOG_NORMALIZED_SHA256})
        self.assertEqual(set(mappings.mapped("migration_state")), {"blocked_partial_catalog"})
        self.assertEqual(set(mappings.mapped("legacy_classification")), {"drift"})
        self.assertEqual(
            len(mappings.filtered("technical_callback_compatibility")), 8
        )
        self.assertFalse(
            mappings.filtered("technical_callback_compatibility").filtered(
                "agent_login_allowed"
            )
        )
        for field_name in (
            "vicidial_user_group_id",
            "vicidial_inbound_group_id",
            "default_list_id",
            "vicidial_script_id",
            "disposition_set_key",
            "email_alias_key",
        ):
            self.assertFalse(mappings.filtered(field_name))
        self.assertFalse(mappings.filtered("desired_enabled"))
        self.assertFalse(mappings.filtered("provisioning_enabled"))
        self.assertFalse(mappings.filtered("agent_sync_enabled"))
        self.assertFalse(mappings.filtered("live_call_control_enabled"))
        self.assertTrue(all(len(value) == 64 for value in mappings.mapped("desired_state_hash")))

    def test_catalog_collision_is_rejected_before_adoption(self):
        rows = deepcopy(_catalog_rows())
        rows[1]["vicidial_campaign_id"] = rows[0]["vicidial_campaign_id"]
        with patch(
            "odoo.addons.codestra_cc_vicidial.models.telephony_mapping._catalog_rows",
            return_value=rows,
        ):
            with self.assertRaises(ValidationError):
                self.Mapping._load_controlled_catalog()

    def test_desired_state_contract_is_hash_bound_and_disabled(self):
        document = self.Contract.with_user(self.service).get_desired_state(
            self.mapping_a.mapping_uuid
        )
        self.assertEqual(document["mapping_uuid"], self.mapping_a.mapping_uuid)
        self.assertEqual(document["vicidial_campaign_id"], "CODWEBO")
        self.assertEqual(document["catalog_status"], "partial")
        self.assertEqual(document["migration_state"], "blocked_partial_catalog")
        self.assertFalse(document["desired_enabled"])
        self.assertFalse(document["provisioning_enabled"])
        self.assertFalse(document["agent_sync_enabled"])
        self.assertFalse(document["live_call_control_enabled"])
        self.assertEqual(
            document["desired_state_hash"], f"sha256:{self.mapping_a.desired_state_hash}"
        )

    def test_mapping_identity_and_evidence_cannot_be_forged(self):
        with self.assertRaises(AccessError):
            self.Mapping.create(
                {
                    "campaign_id": self.mapping_a.campaign_id.id,
                    "channel_id": self.mapping_a.channel_id.id,
                    "mapping_uuid": self.mapping_a.mapping_uuid,
                    "vicidial_campaign_id": "FORGED",
                    "catalog_sha256": "a" * 64,
                    "catalog_row_sha256": "b" * 64,
                    "legacy_classification": "drift",
                }
            )
        with self.assertRaises(AccessError):
            self.mapping_a.write({"vicidial_campaign_id": "FORGED"})
        with self.assertRaises(AccessError):
            self.mapping_a.with_context(_cc_telephony_mapping_write=True).write(
                {"vicidial_campaign_id": "FORGED"}
            )
        with self.assertRaises(AccessError):
            self.mapping_a.copy()
        with self.assertRaises(AccessError):
            self.mapping_a.unlink()
        with self.assertRaises(AccessError):
            self.Readback.create(
                {
                    "mapping_id": self.mapping_a.id,
                    "campaign_id": self.mapping_a.campaign_id.id,
                    "event_id": "forged-event",
                    "event_fingerprint": "a" * 64,
                    "source_system": "forged",
                    "observed_payload_hash": "b" * 64,
                    "evidence_reference": "staging://forged/evidence",
                    "result": "match",
                    "recorded_at": fields.Datetime.now(),
                }
            )
        with self.assertRaises(UserError):
            self.mapping_a.with_user(self.supervisor_a).export_data(
                ["canonical_campaign_code"]
            )

    def test_supervisor_search_name_group_and_direct_id_are_campaign_scoped(self):
        MappingA = self.Mapping.with_user(self.supervisor_a)
        self.assertEqual(MappingA.search([]), self.mapping_a)
        self.assertFalse(MappingA.search([("id", "=", self.mapping_b.id)]))
        self.assertFalse(
            MappingA.name_search(
                self.mapping_b.canonical_campaign_code, operator="=", limit=10
            )
        )
        grouped = MappingA._read_group([], ["legacy_classification"], ["__count"])
        self.assertEqual(sum(count for _state, count in grouped), 1)
        with self.assertRaises(AccessError):
            self.mapping_b.with_user(self.supervisor_a).read(
                ["canonical_campaign_code"]
            )

    def test_readback_is_exactly_once_append_only_and_never_enables(self):
        service_mapping = self.mapping_a.with_user(self.service)
        readback = service_mapping.action_record_readback(
            event_id="rb-cod-web-out-001",
            observed_vicidial_campaign_id="CODWEBO",
            observed_exists=True,
            observed_enabled=False,
            observed_payload_hash="a" * 64,
            evidence_reference="staging://vicidial/readback/cod-web-out-001",
        )
        self.assertEqual(readback.result, "match")
        repeated = service_mapping.action_record_readback(
            event_id="rb-cod-web-out-001",
            observed_vicidial_campaign_id="CODWEBO",
            observed_exists=True,
            observed_enabled=False,
            observed_payload_hash="a" * 64,
            evidence_reference="staging://vicidial/readback/cod-web-out-001",
        )
        self.assertEqual(repeated, readback)
        with self.assertRaises(ValidationError):
            service_mapping.action_record_readback(
                event_id="rb-cod-web-out-001",
                observed_vicidial_campaign_id="CODWEBO",
                observed_exists=True,
                observed_enabled=False,
                observed_payload_hash="b" * 64,
                evidence_reference="staging://vicidial/readback/cod-web-out-001",
            )
        drift = service_mapping.action_record_readback(
            event_id="rb-cod-web-out-002",
            observed_vicidial_campaign_id="CODWEBO",
            observed_exists=True,
            observed_enabled=True,
            observed_payload_hash="c" * 64,
            evidence_reference="staging://vicidial/readback/cod-web-out-002",
        )
        self.assertEqual(drift.result, "drift")
        self.assertEqual(self.mapping_a.reconciliation_status, "drift")
        self.assertFalse(self.mapping_a.desired_enabled)
        self.assertFalse(self.mapping_a.provisioning_enabled)
        self.assertFalse(self.mapping_a.live_call_control_enabled)
        with self.assertRaises(AccessError):
            readback.write({"result": "drift"})
        with self.assertRaises(AccessError):
            readback.unlink()

    def test_readback_rejects_unknown_fields_and_unsafe_evidence(self):
        with self.assertRaises(ValidationError):
            self.Contract.with_user(self.service).accept_readback(
                self.mapping_a.mapping_uuid,
                {
                    "event_id": "rb-unknown-field",
                    "observed_vicidial_campaign_id": "CODWEBO",
                    "observed_exists": True,
                    "observed_enabled": False,
                    "observed_payload_hash": "d" * 64,
                    "evidence_reference": "staging://vicidial/readback/unknown",
                    "unexpected_field": "prohibited",
                },
            )
        with self.assertRaises(ValidationError):
            self.mapping_a.with_user(self.service).action_record_readback(
                event_id="rb-unsafe-evidence",
                observed_vicidial_campaign_id="CODWEBO",
                observed_exists=True,
                observed_enabled=False,
                observed_payload_hash="e" * 64,
                evidence_reference="https://user:password@example.invalid/evidence?token=x",
            )

    def test_canonical_feature_flags_are_all_false(self):
        parameters = self.env["ir.config_parameter"].with_user(self.env.ref("base.user_root"))
        for key in (
            "CC_ENABLE_CAMPAIGN_PROVISIONING",
            "CC_ENABLE_AGENT_SYNC",
            "CC_ENABLE_VICIDIAL_WRITES",
            "CC_ENABLE_LIVE_CALL_CONTROL",
        ):
            self.assertEqual(parameters.get_param(key), "false")

    def test_catalog_schema_is_stable(self):
        rows = _catalog_rows()
        self.assertEqual(tuple(rows[0]), CATALOG_COLUMNS)
        self.assertEqual(len(rows), 93)
