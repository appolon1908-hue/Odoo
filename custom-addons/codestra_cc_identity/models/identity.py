import hashlib
import json
import re
import uuid

from odoo import _, api, fields, models
from odoo.exceptions import AccessDenied, AccessError, ValidationError


OPERATIONAL_ROLES = {"agent", "senior_agent", "supervisor"}
OPERATIONAL_GROUPS = (
    "codestra_cc_security.group_cc_campaign_agent",
    "codestra_cc_security.group_cc_senior_agent",
    "codestra_cc_security.group_cc_campaign_supervisor",
)
IDENTITY_WRITE_CAPABILITY = object()
OUTBOX_WRITE_CAPABILITY = object()
SESSION_WRITE_CAPABILITY = object()
REASSIGNMENT_WRITE_CAPABILITY = object()
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value):
    encoded = value if isinstance(value, bytes) else str(value).encode()
    return hashlib.sha256(encoded).hexdigest()


def _datetime_value(value):
    return fields.Datetime.to_string(value) if value else False


class ResUsers(models.Model):
    _inherit = "res.users"

    cc_operational_landing_path = fields.Char(
        compute="_compute_cc_operational_landing_path",
        string="Contact Center Landing Path",
    )

    @api.depends(
        "cc_campaign_membership_ids.state",
        "cc_campaign_membership_ids.role",
        "cc_campaign_membership_ids.starts_at",
        "cc_campaign_membership_ids.ends_at",
    )
    def _compute_cc_operational_landing_path(self):
        now = fields.Datetime.now()
        for user in self:
            memberships = user.cc_campaign_membership_ids.filtered(
                lambda item: item.state == "active"
                and item.role in OPERATIONAL_ROLES
                and (not item.starts_at or item.starts_at <= now)
                and (not item.ends_at or item.ends_at > now)
            )
            if len(memberships) != 1:
                user.cc_operational_landing_path = False
            elif memberships.role == "supervisor":
                user.cc_operational_landing_path = "/contact-center/supervisor"
            else:
                user.cc_operational_landing_path = "/contact-center/agent"

    def _cc_requires_session_scope(self):
        self.ensure_one()
        if self.has_group("codestra_cc_security.group_cc_global_administrator"):
            return False
        return any(self.has_group(xmlid) for xmlid in OPERATIONAL_GROUPS)

    def _cc_resolve_operational_membership(self):
        self.ensure_one()
        now = fields.Datetime.now()
        memberships = self.env["cc.campaign.membership"].with_context(
            active_test=False
        ).search(
            [
                ("user_id", "=", self.id),
                ("state", "=", "active"),
                ("role", "in", sorted(OPERATIONAL_ROLES)),
                ("starts_at", "<=", now),
                "|",
                ("ends_at", "=", False),
                ("ends_at", ">", now),
            ]
        )
        if len(memberships) != 1:
            raise AccessDenied(
                _("Contact-center access requires exactly one active membership.")
            )
        membership = memberships[0]
        if (
            membership.last_sync_status != "matched"
            or not membership.read_back_evidence
        ):
            raise AccessDenied(_("The campaign identity is not reconciled."))
        return membership

    def action_cc_revoke_sessions_for_security_event(self, reason=None):
        if not self.env.user.has_group(
            "codestra_cc_security.group_cc_global_administrator"
        ):
            raise AccessError(
                _("Only a global contact-center administrator may revoke sessions.")
            )
        reason = (reason or "security_event")[:128]
        memberships = self.env["cc.campaign.membership"].search(
            [
                ("user_id", "in", self.ids),
                ("state", "in", ("active", "suspended")),
                ("role", "in", sorted(OPERATIONAL_ROLES)),
            ]
        )
        memberships._revoke_identity_sessions(reason)
        return True


class CcCampaignMembership(models.Model):
    _inherit = "cc.campaign.membership"

    identity_uuid = fields.Char(
        required=True,
        default=lambda self: str(uuid.uuid4()),
        copy=False,
        readonly=True,
        index=True,
    )
    desired_state_version = fields.Integer(
        required=True, default=0, copy=False, readonly=True
    )
    identity_outbox_ids = fields.One2many(
        "cc.identity.outbox", "membership_id", readonly=True
    )
    identity_session_scope_ids = fields.One2many(
        "cc.identity.session.scope", "membership_id", readonly=True
    )
    provisioning_request_ids = fields.One2many(
        "codestra.provisioning.request", "cc_membership_id", readonly=True
    )

    _identity_uuid_unique = models.Constraint(
        "unique(identity_uuid)", "Membership identity UUIDs must be unique."
    )
    _desired_state_version_nonnegative = models.Constraint(
        "check(desired_state_version >= 0)",
        "Desired-state versions cannot be negative.",
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_identity_write_capability") is not IDENTITY_WRITE_CAPABILITY:
            for values in values_list:
                if values.get("state", "draft") not in {"draft", "pending_approval"}:
                    raise AccessError(
                        _("Identity-managed memberships must begin in draft approval state.")
                    )
                if values.get("last_sync_status", "not_started") != "not_started":
                    raise AccessError(
                        _("Synchronization state is controlled by identity read-back.")
                    )
                if values.get("read_back_evidence"):
                    raise AccessError(
                        _("Read-back evidence is controlled by identity reconciliation.")
                    )
        return super().create(values_list)

    def write(self, values):
        protected = {
            "identity_uuid",
            "desired_state_version",
            "last_sync_status",
            "read_back_evidence",
        }
        if (
            protected.intersection(values)
            and self.env.context.get("_cc_identity_write_capability")
            is not IDENTITY_WRITE_CAPABILITY
        ):
            raise AccessError(
                _("Identity synchronization fields require the governed workflow.")
            )
        return super().write(values)

    def action_submit_identity(self):
        self._require_global_administrator()
        for membership in self:
            if membership.state != "draft":
                raise ValidationError(_("Only draft memberships can be submitted."))
            if not membership.source_ticket:
                raise ValidationError(_("A source ticket is required before submission."))
            membership.with_context(cc_membership_transition=True).write(
                {"state": "pending_approval"}
            )
        return True

    def action_approve_identity(self, operation="provision"):
        self._require_global_administrator()
        if operation not in {"provision", "reassign_destination"}:
            raise ValidationError(_("Unsupported access-grant operation."))
        now = fields.Datetime.now()
        operations = self.env["cc.identity.outbox"]
        for membership in self:
            if membership.state != "pending_approval":
                raise ValidationError(
                    _("Only pending membership requests can be approved.")
                )
            if membership.requested_by_id == self.env.user:
                raise AccessError(
                    _("The membership requester cannot approve the same request.")
                )
            membership.with_context(
                cc_membership_transition=True,
                _cc_identity_write_capability=IDENTITY_WRITE_CAPABILITY,
            ).write(
                {
                    "state": "pending_sync",
                    "approved_by_id": self.env.user.id,
                    "approved_at": now,
                    "starts_at": membership.starts_at or now,
                    "last_sync_status": "pending",
                    "read_back_evidence": False,
                }
            )
            operations |= membership._queue_identity_operation(operation)
        return operations

    def _next_desired_state_version(self):
        self.ensure_one()
        version = self.desired_state_version + 1
        self.with_context(
            _cc_identity_write_capability=IDENTITY_WRITE_CAPABILITY
        ).write({"desired_state_version": version})
        return version

    def _desired_identity_payload(self, operation, version):
        self.ensure_one()
        return {
            "schema_version": "1.0",
            "operation": operation,
            "membership_uuid": self.identity_uuid,
            "desired_state_version": version,
            "business_unit_code": self.business_unit_id.code,
            "campaign_code": self.campaign_id.code,
            "campaign_workspace_uuid": self.campaign_id.workspace_uuid,
            "campaign_scope_version": self.campaign_id.scope_version,
            "role": self.role,
            "membership_state": self.state,
            "starts_at": _datetime_value(self.starts_at),
            "ends_at": _datetime_value(self.ends_at),
            "identities": {
                "odoo_user_id": self.user_id.id,
                "odoo_employee_id": self.employee_id.id,
                "keycloak_subject": self.keycloak_subject or False,
                "vicidial_user": self.vicidial_user or False,
                "vicidial_user_group": self.vicidial_user_group or False,
                "campaign_email_identity": self.campaign_email_identity or False,
                "distribution_groups": sorted(self.distribution_groups or []),
            },
            "controls": {
                "browser_campaign_selection_allowed": False,
                "change_agent_campaign": False,
                "production_provisioning_enabled": False,
                "direct_vicidial_database_write_allowed": False,
            },
        }

    def _operation_contract(self, operation):
        contracts = {
            "provision": (
                "cc.membership.approved.v1",
                ["odoo", "keycloak", "email", "middleware", "vicidial"],
            ),
            "suspend": (
                "cc.membership.suspended.v1",
                ["odoo", "keycloak", "middleware", "vicidial"],
            ),
            "revoke": (
                "cc.membership.revoked.v1",
                ["odoo", "keycloak", "email", "middleware", "vicidial"],
            ),
            "expire": (
                "cc.membership.revoked.v1",
                ["odoo", "keycloak", "email", "middleware", "vicidial"],
            ),
            "reassign_destination": (
                "cc.membership.approved.v1",
                ["odoo", "keycloak", "email", "middleware", "vicidial"],
            ),
            "session_revoke": (
                "cc.agent.session.revoked.v1",
                ["odoo", "keycloak", "middleware", "vicidial"],
            ),
        }
        try:
            return contracts[operation]
        except KeyError as error:
            raise ValidationError(_("Unsupported identity operation.")) from error

    def _queue_identity_operation(self, operation, increment_version=True):
        self.ensure_one()
        event_type, targets = self._operation_contract(operation)
        version = (
            self._next_desired_state_version()
            if increment_version
            else self.desired_state_version
        )
        if version < 1:
            version = self._next_desired_state_version()
        payload = self._desired_identity_payload(operation, version)
        payload_json = _canonical_json(payload)
        idempotency_key = _sha256(
            "%s|%s|%s" % (self.identity_uuid, operation, version)
        )
        existing = self.env["cc.identity.outbox"].search(
            [("idempotency_key", "=", idempotency_key)], limit=1
        )
        if existing:
            if existing.payload_hash != _sha256(payload_json):
                raise ValidationError(_("Immutable identity outbox binding conflict."))
            return existing
        return self.env["cc.identity.outbox"].with_context(
            _cc_identity_outbox_capability=OUTBOX_WRITE_CAPABILITY
        ).create(
            {
                "membership_id": self.id,
                "campaign_id": self.campaign_id.id,
                "operation": operation,
                "event_type": event_type,
                "desired_state_version": version,
                "payload_json": payload,
                "payload_hash": _sha256(payload_json),
                "idempotency_key": idempotency_key,
                "required_targets": targets,
                "approved_by_id": self.approved_by_id.id or self.env.user.id,
            }
        )

    def _latest_access_grant_operation(self):
        self.ensure_one()
        return self.identity_outbox_ids.filtered(
            lambda item: item.operation in {"provision", "reassign_destination"}
        ).sorted(lambda item: (item.desired_state_version, item.id), reverse=True)[:1]

    def action_activate(self):
        self._require_global_administrator()
        for membership in self:
            if membership.requested_by_id == self.env.user:
                raise AccessError(
                    _("The membership requester cannot approve the same request.")
                )
            if membership.state != "pending_sync":
                raise ValidationError(
                    _("Identity-managed activation requires pending synchronization.")
                )
            operation = membership._latest_access_grant_operation()
            if (
                not operation
                or operation.state != "readback_matched"
                or operation.desired_state_version != membership.desired_state_version
                or membership.last_sync_status != "matched"
            ):
                raise ValidationError(
                    _("Activation requires complete matched identity read-back.")
                )
        return super().action_activate()

    def _revoke_identity_sessions(self, reason):
        for membership in self:
            active_scopes = membership.identity_session_scope_ids.filtered(
                lambda item: item.state == "active"
            )
            active_scopes._invalidate("revoked", reason)
            devices = self.env["res.device"].search(
                [("user_id", "=", membership.user_id.id)]
            )
            if devices:
                devices._revoke()
            membership._queue_identity_operation(
                "session_revoke", increment_version=False
            )
        return True

    def action_suspend(self):
        result = super().action_suspend()
        for membership in self:
            membership.with_context(
                _cc_identity_write_capability=IDENTITY_WRITE_CAPABILITY
            ).write({"last_sync_status": "pending", "read_back_evidence": False})
            membership._queue_identity_operation("suspend")
            membership._revoke_identity_sessions("membership_suspended")
        return result

    def action_revoke(self):
        candidates = self.filtered(lambda item: item.state not in {"revoked", "expired"})
        result = super().action_revoke()
        for membership in candidates:
            membership.with_context(
                _cc_identity_write_capability=IDENTITY_WRITE_CAPABILITY
            ).write({"last_sync_status": "pending", "read_back_evidence": False})
            membership._queue_identity_operation("revoke")
            membership._revoke_identity_sessions("membership_revoked")
        return result

    def action_expire_identity(self):
        self._require_global_administrator()
        now = fields.Datetime.now()
        for membership in self:
            if membership.state not in {"active", "suspended"}:
                raise ValidationError(
                    _("Only active or suspended memberships can expire.")
                )
            if not membership.ends_at or membership.ends_at > now:
                raise ValidationError(_("The membership has not reached its expiry."))
            membership.with_context(
                cc_membership_transition=True,
                _cc_identity_write_capability=IDENTITY_WRITE_CAPABILITY,
            ).write(
                {
                    "state": "expired",
                    "last_sync_status": "pending",
                    "read_back_evidence": False,
                }
            )
            membership._bump_campaign_scope()
            membership._sync_primary_supervisor()
            membership._queue_identity_operation("expire")
            membership._revoke_identity_sessions("membership_expired")
        self._invalidate_authorization_scope()
        return True


class CcIdentityOutbox(models.Model):
    _name = "cc.identity.outbox"
    _description = "Immutable Campaign Identity Desired-State Outbox"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "create_date desc, id desc"

    name = fields.Char(
        required=True,
        default=lambda self: str(uuid.uuid4()),
        copy=False,
        readonly=True,
        index=True,
    )
    membership_id = fields.Many2one(
        "cc.campaign.membership",
        required=True,
        ondelete="restrict",
        index=True,
        readonly=True,
    )
    user_id = fields.Many2one(
        related="membership_id.user_id", store=True, readonly=True, index=True
    )
    operation = fields.Selection(
        [
            ("provision", "Provision"),
            ("suspend", "Suspend"),
            ("revoke", "Revoke"),
            ("expire", "Expire"),
            ("reassign_destination", "Reassign Destination"),
            ("session_revoke", "Session Revoke"),
        ],
        required=True,
        readonly=True,
        index=True,
    )
    event_type = fields.Char(required=True, readonly=True, index=True)
    state = fields.Selection(
        [
            ("pending_dispatch", "Pending Dispatch"),
            ("dispatched", "Dispatched"),
            ("readback_matched", "Read-Back Matched"),
            ("mismatch", "Read-Back Mismatch"),
            ("failed", "Failed"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="pending_dispatch",
        readonly=True,
        index=True,
    )
    desired_state_version = fields.Integer(required=True, readonly=True)
    payload_json = fields.Json(required=True, readonly=True)
    payload_hash = fields.Char(required=True, size=64, readonly=True, index=True)
    idempotency_key = fields.Char(required=True, size=64, readonly=True, index=True)
    correlation_id = fields.Char(
        required=True,
        default=lambda self: str(uuid.uuid4()),
        readonly=True,
        index=True,
    )
    required_targets = fields.Json(required=True, readonly=True)
    approved_by_id = fields.Many2one(
        "res.users", required=True, ondelete="restrict", readonly=True
    )
    dispatched_at = fields.Datetime(readonly=True)
    read_back_at = fields.Datetime(readonly=True)
    read_back_json = fields.Json(readonly=True)
    read_back_hash = fields.Char(size=64, readonly=True)
    evidence_reference = fields.Char(readonly=True)
    last_error_code = fields.Char(readonly=True)

    _name_unique = models.Constraint(
        "unique(name)", "Identity outbox UUIDs must be unique."
    )
    _idempotency_unique = models.Constraint(
        "unique(idempotency_key)", "Identity outbox idempotency keys must be unique."
    )
    _membership_version_operation_unique = models.Constraint(
        "unique(membership_id, desired_state_version, operation)",
        "A membership operation may be emitted only once per desired-state version.",
    )
    _desired_state_version_positive = models.Constraint(
        "check(desired_state_version > 0)",
        "Identity desired-state versions must be positive.",
    )

    @api.model_create_multi
    def create(self, values_list):
        if (
            self.env.context.get("_cc_identity_outbox_capability")
            is not OUTBOX_WRITE_CAPABILITY
        ):
            raise AccessError(_("Identity outbox records require the governed producer."))
        return super().create(values_list)

    def write(self, values):
        if (
            self.env.context.get("_cc_identity_outbox_capability")
            is not OUTBOX_WRITE_CAPABILITY
        ):
            raise AccessError(_("Identity outbox records are immutable evidence."))
        return super().write(values)

    def unlink(self):
        raise AccessError(_("Identity outbox history cannot be deleted."))

    @api.constrains(
        "membership_id",
        "campaign_id",
        "desired_state_version",
        "payload_json",
        "payload_hash",
        "idempotency_key",
        "required_targets",
    )
    def _check_outbox_contract(self):
        for record in self:
            if record.membership_id.campaign_id != record.campaign_id:
                raise ValidationError(_("Identity outbox campaign binding is invalid."))
            if record.payload_hash != _sha256(_canonical_json(record.payload_json)):
                raise ValidationError(_("Identity outbox payload hash is invalid."))
            if not SHA256_PATTERN.fullmatch(record.idempotency_key or ""):
                raise ValidationError(_("Identity outbox idempotency key is invalid."))
            targets = record.required_targets or []
            if not isinstance(targets, list) or not targets or len(targets) != len(set(targets)):
                raise ValidationError(_("Identity read-back targets must be unique."))

    def _require_integration_service(self):
        if not self.env.su and not self.env.user.has_group(
            "codestra_identity_provisioning.group_provisioning_service"
        ):
            raise AccessError(_("Provisioning integration-service permission is required."))

    def _protected_write(self, values):
        return self.with_context(
            _cc_identity_outbox_capability=OUTBOX_WRITE_CAPABILITY
        ).write(values)

    def action_mark_dispatched(self):
        self._require_integration_service()
        for record in self:
            if record.state != "pending_dispatch":
                raise ValidationError(_("Only pending identity events can be dispatched."))
            record._protected_write(
                {"state": "dispatched", "dispatched_at": fields.Datetime.now()}
            )
        return True

    def action_record_readback(self, target_results, evidence_reference):
        self._require_integration_service()
        if not evidence_reference or len(evidence_reference) > 255:
            raise ValidationError(_("A bounded read-back evidence reference is required."))
        for record in self:
            if record.state not in {
                "pending_dispatch",
                "dispatched",
                "mismatch",
                "failed",
            }:
                raise ValidationError(_("This identity event no longer accepts read-back."))
            if not isinstance(target_results, dict):
                raise ValidationError(_("Target read-back must be an object."))
            required = set(record.required_targets or [])
            if set(target_results) != required:
                raise ValidationError(
                    _("Read-back must contain exactly every required target.")
                )
            normalized = {}
            for target in sorted(required):
                result = target_results[target]
                if not isinstance(result, dict):
                    raise ValidationError(_("Each target requires structured read-back."))
                status = result.get("status")
                evidence_hash = str(result.get("evidence_hash") or "").lower()
                if status not in {"matched", "mismatch", "failed"}:
                    raise ValidationError(_("Target read-back status is invalid."))
                if not SHA256_PATTERN.fullmatch(evidence_hash):
                    raise ValidationError(_("Target evidence must be a SHA-256 hash."))
                normalized[target] = {
                    "status": status,
                    "evidence_hash": evidence_hash,
                }
            statuses = {item["status"] for item in normalized.values()}
            state = (
                "readback_matched"
                if statuses == {"matched"}
                else "failed"
                if "failed" in statuses
                else "mismatch"
            )
            readback_hash = _sha256(_canonical_json(normalized))
            record._protected_write(
                {
                    "state": state,
                    "read_back_at": fields.Datetime.now(),
                    "read_back_json": normalized,
                    "read_back_hash": readback_hash,
                    "evidence_reference": evidence_reference,
                    "last_error_code": False if state == "readback_matched" else state,
                }
            )
            membership = record.membership_id
            membership.with_user(record.approved_by_id).with_context(
                _cc_identity_write_capability=IDENTITY_WRITE_CAPABILITY
            ).write(
                {
                    "last_sync_status": (
                        "matched"
                        if state == "readback_matched"
                        else "failed"
                        if state == "failed"
                        else "mismatch"
                    ),
                    "read_back_evidence": (
                        "%s#%s" % (evidence_reference, readback_hash)
                    ),
                }
            )
        return True


class CcIdentitySessionScope(models.Model):
    _name = "cc.identity.session.scope"
    _description = "Server-Pinned Contact Center Session Scope"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "started_at desc, id desc"

    user_id = fields.Many2one(
        "res.users", required=True, ondelete="restrict", index=True, readonly=True
    )
    membership_id = fields.Many2one(
        "cc.campaign.membership",
        required=True,
        ondelete="restrict",
        index=True,
        readonly=True,
    )
    session_key_hash = fields.Char(
        required=True, size=64, readonly=True, index=True
    )
    oidc_subject_hash = fields.Char(size=64, readonly=True)
    scope_version_snapshot = fields.Integer(required=True, readonly=True)
    state = fields.Selection(
        [
            ("active", "Active"),
            ("revoked", "Revoked"),
            ("stale", "Stale"),
            ("expired", "Expired"),
        ],
        required=True,
        default="active",
        readonly=True,
        index=True,
    )
    started_at = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True
    )
    expires_at = fields.Datetime(readonly=True)
    revoked_at = fields.Datetime(readonly=True)
    revocation_reason = fields.Char(readonly=True)

    _session_key_unique = models.Constraint(
        "unique(session_key_hash)", "A server session may be pinned only once."
    )
    _scope_version_positive = models.Constraint(
        "check(scope_version_snapshot > 0)",
        "Pinned session scope versions must be positive.",
    )

    @api.model_create_multi
    def create(self, values_list):
        if (
            self.env.context.get("_cc_identity_session_capability")
            is not SESSION_WRITE_CAPABILITY
        ):
            raise AccessError(_("Session scope is pinned only by server authentication."))
        return super().create(values_list)

    def write(self, values):
        if (
            self.env.context.get("_cc_identity_session_capability")
            is not SESSION_WRITE_CAPABILITY
        ):
            raise AccessError(_("Session scope is server-managed and immutable."))
        return super().write(values)

    def unlink(self):
        raise AccessError(_("Session scope history cannot be deleted."))

    @api.constrains(
        "user_id",
        "membership_id",
        "campaign_id",
        "session_key_hash",
        "oidc_subject_hash",
    )
    def _check_session_binding(self):
        for scope in self:
            if scope.membership_id.user_id != scope.user_id:
                raise ValidationError(_("Session user and membership user differ."))
            if scope.membership_id.campaign_id != scope.campaign_id:
                raise ValidationError(_("Session campaign and membership campaign differ."))
            if not SHA256_PATTERN.fullmatch(scope.session_key_hash or ""):
                raise ValidationError(_("Session identifiers must be stored as SHA-256 hashes."))
            if scope.oidc_subject_hash and not SHA256_PATTERN.fullmatch(
                scope.oidc_subject_hash
            ):
                raise ValidationError(_("OIDC subjects must be stored as SHA-256 hashes."))

    @api.model
    def _pin_authenticated_session(
        self, session_identifier, oidc_subject=None, expires_at=None
    ):
        if not session_identifier:
            raise AccessDenied(_("A server session identifier is required."))
        membership = self.env.user._cc_resolve_operational_membership()
        session_hash = _sha256(session_identifier)
        existing = self.search([("session_key_hash", "=", session_hash)], limit=1)
        if existing:
            if (
                existing.user_id != self.env.user
                or existing.membership_id != membership
                or existing.state != "active"
            ):
                raise AccessDenied(_("The server session cannot be rebound."))
            existing._assert_authenticated_session(session_identifier)
            return existing
        return self.with_context(
            _cc_identity_session_capability=SESSION_WRITE_CAPABILITY
        ).create(
            {
                "user_id": self.env.user.id,
                "membership_id": membership.id,
                "campaign_id": membership.campaign_id.id,
                "session_key_hash": session_hash,
                "oidc_subject_hash": (
                    _sha256(oidc_subject or membership.keycloak_subject)
                    if oidc_subject or membership.keycloak_subject
                    else False
                ),
                "scope_version_snapshot": membership.campaign_id.scope_version,
                "expires_at": expires_at,
            }
        )

    def _invalidate(self, target_state, reason):
        if target_state not in {"revoked", "stale", "expired"}:
            raise ValidationError(_("Invalid session terminal state."))
        for scope in self.filtered(lambda item: item.state == "active"):
            scope.with_context(
                _cc_identity_session_capability=SESSION_WRITE_CAPABILITY
            ).write(
                {
                    "state": target_state,
                    "revoked_at": fields.Datetime.now(),
                    "revocation_reason": (reason or target_state)[:128],
                }
            )
        return True

    def _assert_authenticated_session(self, session_identifier):
        self.ensure_one()
        if self.session_key_hash != _sha256(session_identifier):
            raise AccessDenied(_("The server session binding does not match."))
        now = fields.Datetime.now()
        if self.state != "active":
            raise AccessDenied(_("The contact-center session is not active."))
        if self.expires_at and self.expires_at <= now:
            self._invalidate("expired", "session_expired")
            raise AccessDenied(_("The contact-center session has expired."))
        try:
            membership = self.env.user._cc_resolve_operational_membership()
        except AccessDenied:
            self._invalidate("stale", "membership_not_authorized")
            raise
        if (
            membership != self.membership_id
            or membership.campaign_id != self.campaign_id
            or membership.campaign_id.scope_version != self.scope_version_snapshot
        ):
            self._invalidate("stale", "campaign_scope_changed")
            raise AccessDenied(_("The campaign scope changed; reauthentication is required."))
        return membership

    @api.model
    def _assert_or_pin_authenticated_session(self, session_identifier):
        session_hash = _sha256(session_identifier)
        scope = self.search(
            [
                ("session_key_hash", "=", session_hash),
                ("user_id", "=", self.env.user.id),
            ],
            limit=1,
        )
        if not scope:
            return self._pin_authenticated_session(session_identifier)
        scope._assert_authenticated_session(session_identifier)
        return scope


class CodestraProvisioningRequest(models.Model):
    _inherit = "codestra.provisioning.request"

    cc_membership_id = fields.Many2one(
        "cc.campaign.membership",
        string="Canonical Campaign Membership",
        ondelete="restrict",
        index=True,
        copy=False,
    )

    def write(self, values):
        if "cc_membership_id" in values:
            for request in self:
                if request.cc_membership_id.id != values["cc_membership_id"]:
                    raise AccessError(_("The canonical membership link is immutable."))
        return super().write(values)

    @api.constrains("cc_membership_id", "employee_id", "business_unit_id", "campaign_ids")
    def _check_cc_membership_scope(self):
        for request in self.filtered("cc_membership_id"):
            membership = request.cc_membership_id
            if request.employee_id != membership.employee_id:
                raise ValidationError(_("Provisioning employee and membership differ."))
            if (
                request.business_unit_id
                != membership.business_unit_id.legacy_business_unit_id
            ):
                raise ValidationError(_("Provisioning business unit and membership differ."))
            if (
                request.campaign_ids
                and membership.campaign_id.legacy_campaign_id not in request.campaign_ids
            ):
                raise ValidationError(_("Provisioning campaign and membership differ."))


class CcIdentityReassignment(models.Model):
    _name = "cc.identity.reassignment"
    _description = "Governed Revoke-Then-Grant Campaign Reassignment"
    _order = "create_date desc, id desc"

    source_membership_id = fields.Many2one(
        "cc.campaign.membership", required=True, ondelete="restrict", index=True
    )
    destination_membership_id = fields.Many2one(
        "cc.campaign.membership", required=True, ondelete="restrict", index=True
    )
    source_campaign_id = fields.Many2one(
        related="source_membership_id.campaign_id",
        string="Source Campaign",
        store=True,
        readonly=True,
    )
    destination_campaign_id = fields.Many2one(
        related="destination_membership_id.campaign_id",
        string="Destination Campaign",
        store=True,
        readonly=True,
    )
    user_id = fields.Many2one(
        related="source_membership_id.user_id", store=True, readonly=True
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("pending_approval", "Pending Approval"),
            ("approved", "Approved"),
            ("pending_readback", "Pending Read-Back"),
            ("completed", "Completed"),
            ("blocked", "Blocked"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="draft",
        copy=False,
        index=True,
    )
    effective_at = fields.Datetime(required=True, copy=False)
    source_ticket = fields.Char(required=True, copy=False, index=True)
    pause_evidence = fields.Char(copy=False)
    work_handoff_evidence = fields.Char(copy=False)
    requested_by_id = fields.Many2one(
        "res.users",
        required=True,
        default=lambda self: self.env.user,
        ondelete="restrict",
        copy=False,
    )
    approved_by_id = fields.Many2one(
        "res.users", ondelete="restrict", copy=False, readonly=True
    )
    approved_at = fields.Datetime(copy=False, readonly=True)
    completed_at = fields.Datetime(copy=False, readonly=True)

    _one_open_source_reassignment = models.UniqueIndex(
        "(source_membership_id) WHERE state IN "
        "('draft', 'pending_approval', 'approved', 'pending_readback')",
        "A source membership may have only one open reassignment.",
    )

    @api.model_create_multi
    def create(self, values_list):
        if not self.env.user.has_group(
            "codestra_cc_security.group_cc_global_administrator"
        ):
            raise AccessError(
                _("Only a global contact-center administrator may prepare reassignment.")
            )
        return super().create(values_list)

    def write(self, values):
        immutable = {
            "source_membership_id",
            "destination_membership_id",
            "requested_by_id",
            "source_ticket",
            "effective_at",
        }
        if immutable.intersection(values):
            raise AccessError(_("Approved reassignment identity is immutable."))
        if (
            "state" in values
            and self.env.context.get("_cc_reassignment_write_capability")
            is not REASSIGNMENT_WRITE_CAPABILITY
        ):
            raise AccessError(_("Reassignment state requires the governed workflow."))
        return super().write(values)

    def unlink(self):
        raise AccessError(_("Reassignment evidence cannot be deleted."))

    @api.constrains(
        "source_membership_id",
        "destination_membership_id",
        "effective_at",
        "requested_by_id",
    )
    def _check_reassignment_binding(self):
        for record in self:
            source = record.source_membership_id
            destination = record.destination_membership_id
            if source == destination or source.campaign_id == destination.campaign_id:
                raise ValidationError(_("Reassignment requires a different campaign."))
            if source.user_id != destination.user_id:
                raise ValidationError(_("Reassignment cannot change the assigned user."))
            if source.employee_id != destination.employee_id:
                raise ValidationError(_("Reassignment cannot change the employee."))
            if destination.requested_by_id != record.requested_by_id:
                raise ValidationError(
                    _("Destination membership and reassignment requester must match.")
                )

    def _require_global_administrator(self):
        if not self.env.user.has_group(
            "codestra_cc_security.group_cc_global_administrator"
        ):
            raise AccessError(
                _("Only a global contact-center administrator may reassign access.")
            )

    def _transition(self, state, extra=None):
        values = {"state": state, **(extra or {})}
        return self.with_context(
            _cc_reassignment_write_capability=REASSIGNMENT_WRITE_CAPABILITY
        ).write(values)

    def action_submit(self):
        self._require_global_administrator()
        for record in self:
            if record.state != "draft":
                raise ValidationError(_("Only draft reassignments can be submitted."))
            if record.source_membership_id.state != "active":
                raise ValidationError(_("The source membership must be active."))
            if record.destination_membership_id.state != "draft":
                raise ValidationError(_("The destination membership must remain draft."))
            record._transition("pending_approval")
        return True

    def action_approve(self):
        self._require_global_administrator()
        for record in self:
            if record.state != "pending_approval":
                raise ValidationError(_("Only pending reassignments can be approved."))
            if record.requested_by_id == self.env.user:
                raise AccessError(
                    _("The reassignment requester cannot approve the same change.")
                )
            record._transition(
                "approved",
                {
                    "approved_by_id": self.env.user.id,
                    "approved_at": fields.Datetime.now(),
                },
            )
        return True

    def action_execute(self):
        self._require_global_administrator()
        now = fields.Datetime.now()
        for record in self:
            if record.state != "approved":
                raise ValidationError(_("Only approved reassignments can execute."))
            if record.effective_at > now:
                raise ValidationError(_("The reassignment effective time has not arrived."))
            if not record.pause_evidence or not record.work_handoff_evidence:
                raise ValidationError(
                    _("Pause and old-work handoff evidence are required.")
                )
            source = record.source_membership_id
            destination = record.destination_membership_id
            source.action_suspend()
            source.action_revoke()
            destination.action_submit_identity()
            destination.action_approve_identity(operation="reassign_destination")
            record._transition("pending_readback")
        return True

    def action_complete(self):
        self._require_global_administrator()
        for record in self:
            if record.state != "pending_readback":
                raise ValidationError(
                    _("Only read-back-pending reassignments can complete.")
                )
            destination = record.destination_membership_id
            operation = destination._latest_access_grant_operation()
            if not operation or operation.state != "readback_matched":
                raise ValidationError(
                    _("Destination identity read-back has not matched.")
                )
            destination.action_activate()
            record._transition(
                "completed", {"completed_at": fields.Datetime.now()}
            )
        return True
