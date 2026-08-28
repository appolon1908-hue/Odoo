from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessDenied, AccessError, ValidationError
from odoo.tests import HttpCase, tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestContactCenterIdentityLifecycle(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["cc.business.unit"]._adopt_legacy_records()
        cls.Campaign = cls.env["cc.campaign"].with_context(active_test=False)
        cls.Membership = cls.env["cc.campaign.membership"]
        cls.Outbox = cls.env["cc.identity.outbox"]
        cls.SessionScope = cls.env["cc.identity.session.scope"]
        cls.campaign_a = cls.Campaign.search(
            [("code", "=", "COD-WEB-OUT")], limit=1
        )
        cls.campaign_b = cls.Campaign.search(
            [("id", "!=", cls.campaign_a.id)], limit=1
        )
        cls.requester = cls._create_user(
            "Identity Requester",
            "identity-requester@example.invalid",
            ["codestra_cc_security.group_cc_global_administrator"],
        )
        cls.approver = cls._create_user(
            "Identity Approver",
            "identity-approver@example.invalid",
            ["codestra_cc_security.group_cc_global_administrator"],
        )
        cls.service = cls._create_user(
            "Identity Integration Service",
            "identity-service@example.invalid",
            [
                "base.group_user",
                "codestra_identity_provisioning.group_provisioning_service",
            ],
        )
        cls.agent = cls._create_user(
            "Identity Scoped Agent",
            "identity-agent@example.invalid",
            ["codestra_cc_security.group_cc_campaign_agent"],
        )
        cls.unassigned_agent = cls._create_user(
            "Identity Unassigned Agent",
            "identity-unassigned@example.invalid",
            ["codestra_cc_security.group_cc_campaign_agent"],
        )
        cls.employee = cls.env["hr.employee"].create(
            {
                "name": cls.agent.name,
                "user_id": cls.agent.id,
                "company_id": cls.env.company.id,
            }
        )

    @classmethod
    def _create_user(cls, name, login, group_xmlids):
        groups = cls.env["res.groups"].browse(
            [cls.env.ref(xmlid).id for xmlid in group_xmlids]
        )
        return cls.env["res.users"].create(
            {"name": name, "login": login, "group_ids": [(6, 0, groups.ids)]}
        )

    def _new_membership(self, campaign=None, ticket="IDENTITY-STAGING-1"):
        return self.Membership.with_user(self.requester).create(
            {
                "user_id": self.agent.id,
                "employee_id": self.employee.id,
                "campaign_id": (campaign or self.campaign_a).id,
                "role": "agent",
                "requested_by_id": self.requester.id,
                "source_ticket": ticket,
                "starts_at": fields.Datetime.now(),
            }
        )

    def _approve(self, membership, operation="provision"):
        membership.with_user(self.requester).action_submit_identity()
        return membership.with_user(self.approver).action_approve_identity(
            operation=operation
        )

    def _matched_results(self, operation):
        return {
            target: {"status": "matched", "evidence_hash": "a" * 64}
            for target in operation.required_targets
        }

    def _match(self, operation, reference="staging://identity/readback/1"):
        operation.with_user(self.service).action_record_readback(
            self._matched_results(operation), reference
        )

    def _activate(self, membership):
        operation = self._approve(membership)
        self._match(operation)
        membership.with_user(self.approver).action_activate()
        return operation

    def test_approval_creates_immutable_transactional_desired_state(self):
        membership = self._new_membership()
        operation = self._approve(membership)

        self.assertEqual(membership.state, "pending_sync")
        self.assertEqual(membership.last_sync_status, "pending")
        self.assertEqual(operation.event_type, "cc.membership.approved.v1")
        self.assertEqual(operation.state, "pending_dispatch")
        self.assertEqual(operation.campaign_id, membership.campaign_id)
        self.assertEqual(operation.payload_json["campaign_code"], self.campaign_a.code)
        self.assertFalse(
            operation.payload_json["controls"]["browser_campaign_selection_allowed"]
        )
        self.assertFalse(
            operation.payload_json["controls"]["production_provisioning_enabled"]
        )
        self.assertEqual(len(operation.payload_hash), 64)
        self.assertEqual(len(operation.idempotency_key), 64)
        with self.assertRaises(AccessError):
            operation.with_user(self.approver).write({"state": "dispatched"})
        with self.assertRaises(AccessError):
            operation.with_user(self.approver).unlink()

    def test_partial_or_untrusted_readback_never_activates_access(self):
        membership = self._new_membership(ticket="IDENTITY-PARTIAL")
        operation = self._approve(membership)
        with self.assertRaises(ValidationError):
            membership.with_user(self.approver).action_activate()
        with self.assertRaises(AccessError):
            operation.with_user(self.approver).action_record_readback(
                self._matched_results(operation), "staging://forbidden"
            )
        partial = self._matched_results(operation)
        partial.pop(next(iter(partial)))
        with self.assertRaises(ValidationError):
            operation.with_user(self.service).action_record_readback(
                partial, "staging://partial"
            )
        self.assertEqual(membership.state, "pending_sync")
        self.assertNotEqual(membership.last_sync_status, "matched")

    def test_complete_readback_is_required_before_activation(self):
        membership = self._new_membership(ticket="IDENTITY-MATCHED")
        operation = self._approve(membership)
        self._match(operation, "staging://identity/readback/matched")
        self.assertEqual(operation.state, "readback_matched")
        self.assertEqual(membership.last_sync_status, "matched")
        membership.with_user(self.approver).action_activate()
        self.assertEqual(membership.state, "active")
        self.assertEqual(
            self.agent.with_user(self.agent)._cc_resolve_operational_membership(),
            membership,
        )
        self.assertEqual(
            self.agent.cc_operational_landing_path, "/contact-center/agent"
        )

    def test_zero_membership_denies_contact_center_authorization(self):
        with self.assertRaises(AccessDenied):
            self.unassigned_agent.with_user(
                self.unassigned_agent
            )._cc_resolve_operational_membership()

    def test_session_scope_is_server_derived_hashed_and_stale_on_version_change(self):
        membership = self._new_membership(ticket="IDENTITY-SESSION")
        self._activate(membership)
        raw_session = "never-store-this-session-identifier"
        scope = self.SessionScope.with_user(self.agent)._pin_authenticated_session(
            raw_session, oidc_subject="oidc-subject-staging"
        )
        self.assertNotEqual(scope.session_key_hash, raw_session)
        self.assertEqual(len(scope.session_key_hash), 64)
        self.assertEqual(scope.membership_id, membership)
        self.assertEqual(scope.campaign_id, membership.campaign_id)
        self.assertEqual(
            scope.scope_version_snapshot, membership.campaign_id.scope_version
        )
        with self.assertRaises(AccessError):
            self.SessionScope.with_user(self.agent).create(
                {
                    "user_id": self.agent.id,
                    "membership_id": membership.id,
                    "campaign_id": self.campaign_a.id,
                    "session_key_hash": "b" * 64,
                    "scope_version_snapshot": self.campaign_a.scope_version,
                }
            )

        membership.with_user(self.approver)._bump_campaign_scope()
        denied = False
        try:
            scope.with_user(self.agent)._assert_authenticated_session(raw_session)
        except AccessDenied:
            denied = True
        self.assertTrue(denied)
        scope.invalidate_recordset(["state"])
        self.assertEqual(scope.state, "stale")

    def test_suspend_revokes_scopes_and_emits_deprovisioning_events(self):
        membership = self._new_membership(ticket="IDENTITY-SUSPEND")
        self._activate(membership)
        scope = self.SessionScope.with_user(self.agent)._pin_authenticated_session(
            "staging-suspend-session"
        )
        membership.with_user(self.approver).action_suspend()
        self.assertEqual(membership.state, "suspended")
        self.assertEqual(scope.state, "revoked")
        self.assertEqual(membership.last_sync_status, "pending")
        self.assertEqual(
            set(membership.identity_outbox_ids.mapped("event_type")),
            {
                "cc.membership.approved.v1",
                "cc.membership.suspended.v1",
                "cc.agent.session.revoked.v1",
            },
        )

    def test_reassignment_is_atomic_revoke_then_grant(self):
        source = self._new_membership(ticket="IDENTITY-REASSIGN-SOURCE")
        self._activate(source)
        scope = self.SessionScope.with_user(self.agent)._pin_authenticated_session(
            "staging-reassignment-session"
        )
        destination = self._new_membership(
            self.campaign_b, ticket="IDENTITY-REASSIGN-DESTINATION"
        )
        reassignment = self.env["cc.identity.reassignment"].with_user(
            self.requester
        ).create(
            {
                "source_membership_id": source.id,
                "destination_membership_id": destination.id,
                "effective_at": fields.Datetime.now() - timedelta(minutes=1),
                "source_ticket": "IDENTITY-REASSIGNMENT",
                "pause_evidence": "staging://pause/confirmed",
                "work_handoff_evidence": "staging://work/handoff/confirmed",
                "requested_by_id": self.requester.id,
            }
        )
        reassignment.with_user(self.requester).action_submit()
        reassignment.with_user(self.approver).action_approve()
        reassignment.with_user(self.approver).action_execute()

        self.assertEqual(source.state, "revoked")
        self.assertEqual(scope.state, "revoked")
        self.assertEqual(destination.state, "pending_sync")
        destination_operation = destination._latest_access_grant_operation()
        self.assertEqual(destination_operation.operation, "reassign_destination")
        self.assertEqual(reassignment.state, "pending_readback")
        with self.assertRaises(AccessDenied):
            self.agent.with_user(self.agent)._cc_resolve_operational_membership()

        self._match(
            destination_operation, "staging://identity/reassignment/readback"
        )
        reassignment.with_user(self.approver).action_complete()
        self.assertEqual(reassignment.state, "completed")
        self.assertEqual(destination.state, "active")
        self.assertEqual(
            self.agent.with_user(self.agent)._cc_resolve_operational_membership(),
            destination,
        )

    def test_direct_membership_sync_and_pending_state_bypass_is_rejected(self):
        with self.assertRaises(AccessError):
            self.Membership.with_user(self.requester).create(
                {
                    "user_id": self.agent.id,
                    "employee_id": self.employee.id,
                    "campaign_id": self.campaign_a.id,
                    "role": "agent",
                    "state": "pending_sync",
                    "requested_by_id": self.requester.id,
                    "source_ticket": "IDENTITY-BYPASS",
                    "last_sync_status": "matched",
                    "read_back_evidence": "invented",
                }
            )
        membership = self._new_membership(ticket="IDENTITY-DIRECT-WRITE")
        with self.assertRaises(AccessError):
            membership.with_user(self.approver).write(
                {
                    "last_sync_status": "matched",
                    "read_back_evidence": "invented",
                }
            )


@tagged("post_install", "-at_install")
class TestContactCenterIdentityHttp(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["cc.business.unit"]._adopt_legacy_records()
        campaign = cls.env["cc.campaign"].with_context(active_test=False).search(
            [("code", "=", "COD-WEB-OUT")], limit=1
        )
        requester = cls.env["res.users"].create(
            {
                "name": "Identity HTTP Requester",
                "login": "identity-http-requester@example.invalid",
                "group_ids": [
                    (
                        6,
                        0,
                        cls.env.ref(
                            "codestra_cc_security.group_cc_global_administrator"
                        ).ids,
                    )
                ],
            }
        )
        approver = cls.env["res.users"].create(
            {
                "name": "Identity HTTP Approver",
                "login": "identity-http-approver@example.invalid",
                "group_ids": [
                    (
                        6,
                        0,
                        cls.env.ref(
                            "codestra_cc_security.group_cc_global_administrator"
                        ).ids,
                    )
                ],
            }
        )
        service = cls.env["res.users"].create(
            {
                "name": "Identity HTTP Service",
                "login": "identity-http-service@example.invalid",
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            cls.env.ref("base.group_user").id,
                            cls.env.ref(
                                "codestra_identity_provisioning.group_provisioning_service"
                            ).id,
                        ],
                    )
                ],
            }
        )
        cls.agent = cls.env["res.users"].create(
            {
                "name": "Identity HTTP Agent",
                "login": "identity-http-agent@example.invalid",
                "group_ids": [
                    (
                        6,
                        0,
                        cls.env.ref(
                            "codestra_cc_security.group_cc_campaign_agent"
                        ).ids,
                    )
                ],
            }
        )
        employee = cls.env["hr.employee"].create(
            {
                "name": cls.agent.name,
                "user_id": cls.agent.id,
                "company_id": cls.env.company.id,
            }
        )
        membership = cls.env["cc.campaign.membership"].with_user(requester).create(
            {
                "user_id": cls.agent.id,
                "employee_id": employee.id,
                "campaign_id": campaign.id,
                "role": "agent",
                "requested_by_id": requester.id,
                "source_ticket": "IDENTITY-HTTP-STAGING",
                "starts_at": fields.Datetime.now(),
            }
        )
        membership.with_user(requester).action_submit_identity()
        operation = membership.with_user(approver).action_approve_identity()
        operation.with_user(service).action_record_readback(
            {
                target: {"status": "matched", "evidence_hash": "c" * 64}
                for target in operation.required_targets
            },
            "staging://identity/http/readback",
        )
        membership.with_user(approver).action_activate()

    def test_agent_landing_pins_server_session_and_ignores_browser_campaign(self):
        self.authenticate(self.agent.login, "test-password")
        response = self.url_open(
            "/contact-center/agent?campaign_id=999999", allow_redirects=False
        )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["Location"].endswith("/odoo"))
        self.env.invalidate_all()
        scope = self.env["cc.identity.session.scope"].search(
            [("user_id", "=", self.agent.id), ("state", "=", "active")]
        )
        self.assertEqual(len(scope), 1)
        self.assertNotEqual(scope.session_key_hash, self.session.sid)
        self.assertEqual(scope.campaign_id, self.agent.cc_allowed_campaign_ids)
