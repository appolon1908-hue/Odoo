import hashlib
import json
import uuid
from urllib.parse import urlparse

import requests
from odoo import fields, http
from odoo.exceptions import AccessError, ValidationError
from odoo.http import request


class CallControlAPI(http.Controller):
    @staticmethod
    def _agent():
        agent = request.env["codestra.vicidial.agent"].search(
            [("odoo_user_id", "=", request.env.user.id), ("active", "=", True)], limit=1
        )
        if not agent:
            raise AccessError("Agent is not mapped to an active telephony identity.")
        if not request.env.user.codestra_tenant_id or agent.tenant_id != request.env.user.codestra_tenant_id:
            raise AccessError("Agent tenant binding is invalid.")
        return agent

    @staticmethod
    def _feature(name):
        return request.env["codestra.feature.flags"].flag_enabled(name)

    @classmethod
    def _owned_call(cls, call_id):
        cls._agent()
        call = request.env["codestra.vicidial.call"].search([("call_id", "=", call_id)], limit=1)
        if not call:
            raise ValidationError("Call is unavailable.")
        call._check_call_owner()
        return call

    @staticmethod
    def _audit(call, action, after=None):
        request.env["codestra.integration.audit"].sudo().create(
            {
                "actor_user_id": request.env.user.id,
                "action": action,
                "model_name": call._name,
                "record_res_id": call.id,
                "correlation_id": call.correlation_id,
                "after_json": json.dumps(after or {}, sort_keys=True),
                "success": True,
            }
        )

    @staticmethod
    def _key(params):
        key = (params or {}).get("idempotency_key")
        if not isinstance(key, str) or not (16 <= len(key) <= 255):
            raise ValidationError("A valid Idempotency-Key is required.")
        return key

    @http.route("/codestra/call-control/v1/current", type="jsonrpc", auth="user", methods=["POST"])
    def current(self):
        agent = self._agent()
        call = request.env["codestra.vicidial.call"].search(
            [
                ("agent_id", "=", agent.id),
                ("state", "not in", ["completed", "failed", "missed", "rejected", "cancelled", "transferred"]),
            ],
            order="write_date desc",
            limit=1,
        )
        if not call:
            return None
        payload = call.agent_payload()
        payload["call_control_enabled"] = self._feature("call_control_enabled")
        payload["transfer_control_enabled"] = self._feature("transfer_control_enabled")
        return payload

    @http.route("/codestra/call-control/v1/match", type="jsonrpc", auth="user", methods=["POST"])
    def match(self, number, campaign_code=None):
        self._agent()
        return request.env["codestra.vicidial.call"].match_customer(number, campaign_code)

    @http.route("/codestra/call-control/v1/outbound", type="jsonrpc", auth="user", methods=["POST"])
    def outbound(self, lead_id, campaign_id, idempotency_key):
        agent = self._agent()
        if not self._feature("call_control_enabled") or not self._feature("vicidial_write_enabled"):
            raise AccessError("Outbound call control is disabled.")
        key = self._key({"idempotency_key": idempotency_key})
        if campaign_id != "TEST_SYN":
            raise AccessError("Only TEST_SYN is allowed in the controlled environment.")
        lead = request.env["crm.lead"].browse(int(lead_id)).exists()
        campaign = request.env["codestra.vicidial.campaign"].search(
            [("campaign_id", "=", campaign_id), ("mode", "=", "test")], limit=1
        )
        if not lead or not campaign or campaign not in agent.campaign_ids:
            raise AccessError("Lead or campaign is outside the agent authorization scope.")
        number = lead.phone
        normalized = request.env["codestra.vicidial.call"].normalize_number(number)
        prior = request.env["codestra.call.control.command"].search([("idempotency_key", "=", key)], limit=1)
        if prior:
            return {"duplicate": True, "call": prior.call_id.agent_payload()}
        public_id = str(uuid.uuid4())
        correlation = "call-" + public_id
        call = request.env["codestra.vicidial.call"].create(
            {
                "name": f"TEST_SYN outbound {lead.display_name}",
                "call_id": public_id,
                "correlation_id": correlation,
                "idempotency_key": "call:" + key,
                "direction": "outbound",
                "agent_id": agent.id,
                "campaign_id": campaign.id,
                "campaign_code": campaign_id,
                "vicidial_user": agent.vicidial_user,
                "tenant_id": agent.tenant_id,
                "keycloak_subject": request.env.user.keycloak_subject,
                "extension": agent.phone_login,
                "lead_id": lead.id,
                "crm_lead_id": lead.id,
                "customer_id": lead.partner_id.id,
                "destination": normalized,
                "original_number": number,
                "normalized_number": normalized,
                "state": "initiating",
                "start_at": fields.Datetime.now(),
                "sequence": 1,
                "source_system": "odoo",
            }
        )
        self._command(call, "outbound", key, {"lead_id": lead.id, "campaign_id": campaign_id})
        return {"duplicate": False, "call": call.agent_payload()}

    @http.route(
        "/codestra/call-control/v1/calls/<string:call_id>/<string:action>",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
    )
    def action(self, call_id, action, idempotency_key, **params):
        if action not in {"answer", "decline", "hangup", "hold", "resume", "transfer"}:
            raise ValidationError("Unsupported call-control action.")
        if not self._feature("call_control_enabled") or not self._feature("vicidial_write_enabled"):
            raise AccessError("Live call control is disabled.")
        if action == "transfer" and not self._feature("transfer_control_enabled"):
            raise AccessError("Transfer control is disabled.")
        call = self._owned_call(call_id)
        allowed = {
            "answer": {"ringing", "offered"},
            "decline": {"ringing", "offered"},
            "hangup": {"answering", "connected", "held", "transferring"},
            "hold": {"connected"},
            "resume": {"held"},
            "transfer": {"connected", "held"},
        }
        if call.state not in allowed[action]:
            raise ValidationError("Action is not permitted in the current call state.")
        if action == "transfer":
            target = str(params.get("target") or "")
            approved = {str(value.phone_login) for value in call.campaign_id.allowed_agent_ids if value.phone_login}
            if target not in approved or target == call.extension:
                raise AccessError("Transfer target is not approved for this campaign.")
        command = self._command(call, action, self._key({"idempotency_key": idempotency_key}), params)
        return {"duplicate": command[1], "command_id": command[0].id, "state": "queued"}

    @http.route("/codestra/call-control/v1/calls/<string:call_id>/notes", type="jsonrpc", auth="user", methods=["POST"])
    def notes(
        self, call_id, notes, idempotency_key, note_id=None, client_revision=None, note_type="agent", visibility="agent"
    ):
        call = self._owned_call(call_id)
        if len(notes or "") > 10000:
            raise ValidationError("Notes are too long.")
        key = self._key({"idempotency_key": idempotency_key})
        _command, duplicate = self._command(
            call,
            "notes",
            key,
            {
                "note_id": note_id,
                "client_revision": client_revision or key,
            },
        )
        if not duplicate:
            Note = request.env["codestra.call.note"]
            if note_id:
                note = Note.browse(int(note_id)).exists()
                if not note or note.call_id != call or note.author_id != request.env.user:
                    raise AccessError("The note is unavailable.")
                note.write({"body": notes or "", "client_revision": client_revision or key})
            else:
                if note_type == "supervisor" and not request.env.user.has_group(
                    "codestra_vicidial_crm.group_supervisor"
                ):
                    raise AccessError("Supervisor notes require supervisor access.")
                note = Note.create(
                    {
                        "call_id": call.id,
                        "contact_id": call.customer_id.id,
                        "lead_id": (call.crm_lead_id or call.lead_id).id,
                        "body": notes or "",
                        "client_revision": client_revision or key,
                        "note_type": note_type,
                        "visibility": visibility,
                    }
                )
            call.sudo().write({"notes": notes or ""})
            self._audit(
                call,
                "call.notes.autosaved",
                {
                    "note_id": note.id,
                    "revision": note.revision,
                    "notes_present": bool(notes),
                },
            )
        else:
            note = request.env["codestra.call.note"].search(
                [
                    ("call_id", "=", call.id),
                    ("author_id", "=", request.env.user.id),
                    ("client_revision", "=", client_revision or key),
                ],
                limit=1,
            )
        return {"duplicate": duplicate, "saved": True, "note_id": note.id, "revision": note.revision}

    @http.route(
        "/codestra/call-control/v1/calls/<string:call_id>/disposition", type="jsonrpc", auth="user", methods=["POST"]
    )
    def disposition(self, call_id, disposition_code, notes, idempotency_key, sub_disposition_code=None):
        call = self._owned_call(call_id)
        if call.state not in {"completed", "failed", "missed", "rejected", "cancelled", "transferred"}:
            raise ValidationError("Disposition is available only after a terminal call event.")
        disposition = request.env["codestra.vicidial.disposition"].search(
            [("code", "=", disposition_code), ("active", "=", True)], limit=1
        )
        allowed = call.campaign_id.allowed_disposition_ids
        if not disposition or (allowed and disposition not in allowed):
            raise AccessError("Disposition is not valid for this campaign.")
        if disposition.requires_note and not (notes or "").strip():
            raise ValidationError("This disposition requires notes.")
        sub_disposition = request.env["codestra.call.sub.disposition"]
        if sub_disposition_code:
            sub_disposition = sub_disposition.search(
                [
                    ("parent_id", "=", disposition.id),
                    ("code", "=", sub_disposition_code),
                    ("active", "=", True),
                ],
                limit=1,
            )
            if not sub_disposition or (
                sub_disposition.campaign_ids and call.campaign_id not in sub_disposition.campaign_ids
            ):
                raise AccessError("Sub-disposition is not valid for this campaign.")
        _command, duplicate = self._command(
            call,
            "disposition",
            self._key({"idempotency_key": idempotency_key}),
            {"disposition_code": disposition.code, "sub_disposition_code": sub_disposition_code},
        )
        if not duplicate:
            completed_at = fields.Datetime.now()
            wrap_seconds = 0
            if call.wrap_up_started_at:
                wrap_seconds = max(0, int((completed_at - call.wrap_up_started_at).total_seconds()))
            call.sudo().write(
                {
                    "disposition_id": disposition.id,
                    "sub_disposition_id": sub_disposition.id or False,
                    "notes": notes or call.notes,
                    "wrap_up_completed_at": completed_at,
                    "wrap_up_seconds": wrap_seconds,
                }
            )
            self._audit(
                call,
                "call.disposition",
                {
                    "disposition": disposition.code,
                    "sub_disposition": sub_disposition.code,
                },
            )
        return {
            "duplicate": duplicate,
            "saved": True,
            "disposition": disposition.code,
            "sub_disposition": sub_disposition.code or None,
        }

    @http.route(
        "/codestra/call-control/v1/calls/<string:call_id>/workspace", type="jsonrpc", auth="user", methods=["POST"]
    )
    def workspace(self, call_id):
        call = self._owned_call(call_id)
        lead = call.crm_lead_id or call.lead_id
        events = request.env["codestra.vicidial.call.event"].search(
            [("call_id", "=", call.id)], order="sequence, occurred_at, id"
        )
        notes = request.env["codestra.call.note"].search([("call_id", "=", call.id)], order="write_date, id")
        dispositions = call.campaign_id.allowed_disposition_ids or request.env["codestra.vicidial.disposition"].search(
            [("active", "=", True)]
        )
        callbacks = request.env["codestra.callback"].search(
            [
                ("call_id", "=", call.id),
                ("tenant_id", "=", call.tenant_id),
            ],
            order="scheduled_at desc",
        )
        templates = request.env["codestra.call.note.template"].search(
            [
                ("active", "=", True),
                ("campaign_ids", "in", call.campaign_id.id),
            ],
            order="sequence, name",
        )
        activities = (
            request.env["mail.activity"].search(
                [
                    ("res_model", "=", "crm.lead"),
                    ("res_id", "=", lead.id),
                ],
                order="date_deadline, id",
                limit=20,
            )
            if lead
            else request.env["mail.activity"]
        )
        message_domain = [("model", "=", "crm.lead"), ("res_id", "=", lead.id)] if lead else []
        messages = (
            request.env["mail.message"].search(message_domain, order="date desc, id desc", limit=10)
            if message_domain
            else request.env["mail.message"]
        )
        partner = call.customer_id
        prior_domain = [("tenant_id", "=", call.tenant_id), ("id", "!=", call.id)]
        if lead:
            prior_domain.append(("crm_lead_id", "=", lead.id))
        elif partner:
            prior_domain.append(("customer_id", "=", partner.id))
        else:
            prior_domain.append(("normalized_number", "=", call.normalized_number))
        previous_calls = request.env["codestra.vicidial.call"].search(
            prior_domain, order="start_at desc, id desc", limit=10
        )
        payload = call.agent_payload()
        payload.update(
            {
                "company": {"id": call.customer_id.parent_id.id, "name": call.customer_id.parent_id.display_name}
                if call.customer_id.parent_id
                else None,
                "opportunity": {
                    "id": call.opportunity_id.id,
                    "name": call.opportunity_id.display_name,
                    "stage": call.opportunity_id.stage_id.display_name,
                }
                if call.opportunity_id
                else None,
                "location": {
                    "city": partner.city or None,
                    "state": partner.state_id.name or None,
                    "country": partner.country_id.name or None,
                }
                if partner
                else None,
                "timeline": [
                    {
                        "event": event.event_type,
                        "time": event.occurred_at,
                        "source": event.source,
                        "actor": event.actor_id.display_name or None,
                        "sequence": event.sequence,
                        "correlation_id": event.correlation_id,
                    }
                    for event in events
                ],
                "notes": [
                    {
                        "id": note.id,
                        "body": note.body,
                        "type": note.note_type,
                        "visibility": note.visibility,
                        "author": note.author_id.display_name,
                        "revision": note.revision,
                        "updated_at": note.write_date,
                    }
                    for note in notes
                ],
                "dispositions": [
                    {
                        "code": item.code,
                        "name": item.name,
                        "requires_note": item.requires_note,
                        "children": [
                            {
                                "code": child.code,
                                "name": child.name,
                                "requires_callback": child.requires_callback,
                                "requires_task": child.requires_task,
                            }
                            for child in request.env["codestra.call.sub.disposition"].search(
                                [
                                    ("parent_id", "=", item.id),
                                    ("active", "=", True),
                                    "|",
                                    ("campaign_ids", "=", False),
                                    ("campaign_ids", "in", call.campaign_id.id),
                                ],
                                order="sequence, name",
                            )
                        ],
                    }
                    for item in dispositions
                ],
                "callbacks": [
                    {
                        "id": item.id,
                        "scheduled_at": item.scheduled_at,
                        "timezone": item.timezone,
                        "reason": item.reason,
                        "status": item.status,
                        "owner": item.owner_id.display_name,
                    }
                    for item in callbacks
                ],
                "open_tasks": [
                    {
                        "id": item.id,
                        "summary": item.summary,
                        "due_date": item.date_deadline,
                        "owner": item.user_id.display_name,
                        "activity_type": item.activity_type_id.display_name,
                    }
                    for item in activities
                ],
                "recent_communications": [
                    {
                        "id": item.id,
                        "date": item.date,
                        "channel": "email" if item.message_type == "email" else "odoo",
                        "subject": item.subject or "(no subject)",
                        "status": "recorded",
                    }
                    for item in messages
                ],
                "previous_calls": [
                    {
                        "call_id": item.call_id,
                        "date": item.start_at,
                        "direction": item.direction,
                        "disposition": item.disposition_id.display_name or None,
                        "duration": item.total_seconds or item.duration_seconds,
                        "notes": item.notes or None,
                    }
                    for item in previous_calls
                ],
                "sms_status": {"available": False, "reason": "SMS delivery is outside the authorized mission scope"},
                "note_templates": [{"id": item.id, "name": item.name, "body": item.body} for item in templates],
                "recording_id": call.recording_ids.filtered(lambda item: item.available)[:1].recording_id or None,
                "crm": {
                    "lead_id": lead.id or None,
                    "contact_id": call.customer_id.id or None,
                    "email": (call.customer_id.email if call.customer_id else lead.email_from) or None,
                    "phone": call.normalized_number or call.caller_id or call.destination,
                },
            }
        )
        self._audit(call, "call.workspace.viewed", {"sequence": call.sequence})
        return payload

    @http.route(
        "/codestra/call-control/v1/calls/<string:call_id>/callbacks", type="jsonrpc", auth="user", methods=["POST"]
    )
    def callback(self, call_id, scheduled_at, timezone, reason, idempotency_key, priority="1"):
        call = self._owned_call(call_id)
        key = self._key({"idempotency_key": idempotency_key})
        _command, duplicate = self._command(call, "callback", key, {"scheduled_at": scheduled_at})
        if duplicate:
            callback = request.env["codestra.callback"].search([("call_id", "=", call.id)], order="id desc", limit=1)
            return {"duplicate": True, "callback_id": callback.id or None, "dispatch_enabled": False}
        lead = call.crm_lead_id or call.lead_id
        if not lead:
            raise ValidationError("A callback requires a correlated CRM lead.")
        callback = request.env["codestra.callback"].create(
            {
                "name": f"Callback for {lead.display_name}",
                "lead_id": lead.id,
                "owner_id": request.env.user.id,
                "call_id": call.id,
                "tenant_id": call.tenant_id,
                "campaign_id": call.campaign_id.id,
                "phone": call.normalized_number or call.destination or call.caller_id,
                "scheduled_at": scheduled_at,
                "timezone": timezone,
                "reason": reason,
                "priority": priority,
            }
        )
        self._audit(call, "call.callback", {"callback_id": callback.id})
        return {"duplicate": False, "callback_id": callback.id, "dispatch_enabled": False}

    @http.route(
        "/codestra/call-control/v1/calls/<string:call_id>/callbacks/<int:callback_id>/<string:action>",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
    )
    def callback_lifecycle(self, call_id, callback_id, action, scheduled_at=None, timezone=None):
        call = self._owned_call(call_id)
        callback = request.env["codestra.callback"].search(
            [
                ("id", "=", callback_id),
                ("call_id", "=", call.id),
                ("tenant_id", "=", call.tenant_id),
            ],
            limit=1,
        )
        if not callback:
            raise AccessError("Callback is outside the authorized call scope.")
        if action == "reschedule":
            if not scheduled_at:
                raise ValidationError("A new callback time is required.")
            callback.action_reschedule(scheduled_at, timezone)
        elif action == "complete":
            callback.action_complete()
        elif action == "cancel":
            callback.action_cancel()
        else:
            raise ValidationError("Unsupported callback action.")
        self._audit(call, f"call.callback.{action}", {"callback_id": callback.id})
        return {
            "callback_id": callback.id,
            "status": callback.status,
            "scheduled_at": callback.scheduled_at,
            "dispatch_enabled": False,
        }

    @http.route(
        "/codestra/call-control/v1/calls/<string:call_id>/history", type="jsonrpc", auth="user", methods=["POST"]
    )
    def history(self, call_id, offset=0, limit=20):
        call = self._owned_call(call_id)
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))
        domain = [("tenant_id", "=", call.tenant_id)]
        lead = call.crm_lead_id or call.lead_id
        if lead:
            domain.append(("crm_lead_id", "=", lead.id))
        elif call.customer_id:
            domain.append(("customer_id", "=", call.customer_id.id))
        else:
            return {"items": [], "offset": offset, "limit": limit}
        calls = request.env["codestra.vicidial.call"].search(
            domain, order="start_at desc, id desc", offset=offset, limit=limit
        )
        return {
            "items": [
                {
                    "call_id": item.call_id,
                    "date": item.start_at,
                    "direction": item.direction,
                    "campaign": item.campaign_code,
                    "agent": item.agent_id.name,
                    "duration": item.talk_duration or item.duration_seconds,
                    "disposition": item.disposition_id.code,
                    "notes_present": bool(item.notes),
                    "recording_available": item.recording_status == "available",
                }
                for item in calls
            ],
            "offset": offset,
            "limit": limit,
        }

    @http.route(
        "/codestra/call-control/v1/calls/<string:call_id>/record-opened", type="jsonrpc", auth="user", methods=["POST"]
    )
    def record_opened(self, call_id, model, record_id):
        call = self._owned_call(call_id)
        lead = call.crm_lead_id or call.lead_id
        allowed = {("crm.lead", lead.id), ("res.partner", call.customer_id.id)}
        if (model, int(record_id)) not in allowed:
            raise AccessError("CRM record is not correlated to this call.")
        self._audit(call, "call.record_opened", {"model": model, "record_id": int(record_id)})
        return {"recorded": True}

    @http.route(
        "/codestra/call-workspace/v1/calls/<string:call_id>/recording/playback",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
    )
    def recording_playback(self, call_id):
        reviewer = request.env.user.has_group("codestra_vicidial_crm.group_supervisor") or request.env.user.has_group(
            "codestra_vicidial_crm.group_qa"
        )
        call = self._review_call(call_id) if reviewer else self._owned_call(call_id)
        manager = request.env.user.has_group("codestra_vicidial_crm.group_manager")
        if not manager and not request.env.user.can_view_recordings:
            raise AccessError("Recording playback permission is required.")
        recording = call.recording_ids.filtered(lambda item: item.available and item.access_level == "permitted")[:1]
        if not recording or not recording.recording_id:
            raise ValidationError("No authorized recording is available for this call.")
        params = request.env["ir.config_parameter"].sudo()
        base_url = (params.get_param("codestra.recording_api_internal_url") or "").rstrip("/")
        secret = params.get_param("codestra.recording_api_service_secret") or ""
        environment = params.get_param("codestra.recording_environment") or "production"
        ca_file = params.get_param("codestra.recording_api_ca_file") or True
        if not base_url.startswith("https://") or not secret:
            raise ValidationError("Secure recording retrieval is not configured.")
        try:
            response = requests.post(
                f"{base_url}/api/v1/recordings/{recording.recording_id}/playback-url",
                headers={
                    "Authorization": f"Bearer {secret}",
                    "X-Codestra-Environment": environment,
                    "X-Service-Identity": "codestra-odoo",
                },
                json={
                    "requester_type": "odoo",
                    "user_level": 9 if manager else 8,
                    "campaign_authorized": True,
                    "group_authorized": True,
                    "ttl_seconds": 120,
                },
                timeout=5,
                verify=ca_file,
            )
            response.raise_for_status()
            result = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise ValidationError("Authorized recording retrieval is temporarily unavailable.") from exc
        playback_url = result.get("playback_url")
        parsed = urlparse(playback_url or "")
        try:
            expires_in = int(result.get("expires_in", 0))
        except (TypeError, ValueError) as exc:
            raise ValidationError("Recording service returned an invalid playback grant.") from exc
        if parsed.scheme != "https" or not parsed.netloc or not (1 <= expires_in <= 120):
            raise ValidationError("Recording service returned an invalid playback grant.")
        self._audit(call, "call.recording.viewed", {"recording_id": recording.recording_id})
        return {"playback_url": playback_url, "expires_in": expires_in, "cacheable": False}

    @staticmethod
    def _review_call(call_id):
        if not (
            request.env.user.has_group("codestra_vicidial_crm.group_supervisor")
            or request.env.user.has_group("codestra_vicidial_crm.group_qa")
        ):
            raise AccessError("Supervisor or QA access is required.")
        call = request.env["codestra.vicidial.call"].search([("call_id", "=", call_id)], limit=1)
        if not call:
            raise AccessError("The call is outside the authorized review scope.")
        return call

    @http.route("/codestra/call-workspace/v1/calls/search", type="jsonrpc", auth="user", methods=["POST"])
    def call_search(
        self,
        date_from=None,
        date_to=None,
        agent_id=None,
        campaign=None,
        direction=None,
        phone=None,
        disposition=None,
        call_id=None,
        recording_available=None,
        offset=0,
        limit=50,
    ):
        if not (
            request.env.user.has_group("codestra_vicidial_crm.group_supervisor")
            or request.env.user.has_group("codestra_vicidial_crm.group_qa")
        ):
            raise AccessError("Call search requires supervisor or QA access.")
        domain = [("tenant_id", "=", request.env.user.codestra_tenant_id)]
        for value, clause in (
            (date_from, ("start_at", ">=")),
            (date_to, ("start_at", "<=")),
            (agent_id, ("agent_id", "=")),
            (campaign, ("campaign_code", "=")),
            (direction, ("direction", "=")),
            (disposition, ("disposition_id.code", "=")),
            (call_id, ("call_id", "=")),
        ):
            if value:
                domain.append((clause[0], clause[1], int(value) if clause[0] == "agent_id" else value))
        if phone:
            normalized = request.env["codestra.vicidial.call"].normalize_number(phone)
            domain.append(("normalized_number", "=", normalized))
        if recording_available is not None:
            domain.append(
                ("recording_status", "=", "available")
                if recording_available
                else ("recording_status", "!=", "available")
            )
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))
        Call = request.env["codestra.vicidial.call"]
        records = Call.search(domain, order="start_at desc, id desc", offset=offset, limit=limit)
        return {
            "items": [
                {
                    "call_id": item.call_id,
                    "linkedid": item.linkedid,
                    "date": item.start_at,
                    "agent": item.agent_id.name,
                    "agent_id": item.agent_id.id,
                    "campaign": item.campaign_code,
                    "direction": item.direction,
                    "phone": item.normalized_number or item.caller_id or item.destination,
                    "customer": item.customer_id.display_name or None,
                    "disposition": item.disposition_id.code or None,
                    "duration": item.total_seconds or item.duration_seconds,
                    "recording_available": item.recording_status == "available",
                }
                for item in records
            ],
            "total": Call.search_count(domain),
            "offset": offset,
            "limit": limit,
        }

    @http.route(
        "/codestra/call-workspace/v1/calls/<string:call_id>/detail", type="jsonrpc", auth="user", methods=["POST"]
    )
    def call_detail(self, call_id):
        call = self._review_call(call_id)
        events = request.env["codestra.vicidial.call.event"].search(
            [("call_id", "=", call.id)], order="sequence, occurred_at, id"
        )
        notes = request.env["codestra.call.note"].search([("call_id", "=", call.id)])
        reviews = request.env["codestra.call.qa.review"].search([("call_id", "=", call.id)])
        self._audit(call, "call.detail.viewed", {"role": "reviewer"})
        lead = call.crm_lead_id or call.lead_id
        return {
            "call": {
                "call_id": call.call_id,
                "linkedid": call.linkedid,
                "correlation_id": call.correlation_id,
                "state": call.state,
                "sequence": call.sequence,
                "direction": call.direction,
                "phone": call.normalized_number or call.caller_id or call.destination,
                "campaign": call.campaign_code,
                "agent": call.agent_id.name,
                "extension": call.extension,
                "customer": call.customer_id.display_name or None,
                "contact_id": call.customer_id.id or None,
                "lead": lead.display_name or None,
                "lead_id": lead.id or None,
                "ringing_at": call.ringing_at,
                "answered_at": call.answered_at,
                "connected_at": call.connected_at,
                "ended_at": call.ended_at,
                "duration": call.total_seconds or call.duration_seconds,
                "disposition": call.disposition_id.code or None,
                "sub_disposition": call.sub_disposition_id.code or None,
            },
            "timeline": [
                {
                    "event": item.event_type,
                    "time": item.occurred_at,
                    "sequence": item.sequence,
                    "source": item.source,
                    "correlation_id": item.correlation_id,
                }
                for item in events
            ],
            "notes": [
                {
                    "id": item.id,
                    "author": item.author_id.display_name,
                    "body": item.body,
                    "type": item.note_type,
                    "revision": item.revision,
                }
                for item in notes
            ],
            "qa": [
                {
                    "id": item.id,
                    "score": item.score,
                    "state": item.state,
                    "reviewer": item.reviewer_id.display_name,
                    "reviewed_at": item.reviewed_at,
                    "coaching_required": item.coaching_required,
                }
                for item in reviews
            ],
            "recording": {
                "status": call.recording_status,
                "reference": call.recording_reference or None,
                "public_url": None,
            },
            "audit": {"call_id": call.call_id, "linkedid": call.linkedid, "correlation_id": call.correlation_id},
        }

    @http.route("/codestra/call-workspace/v1/supervisor/dashboard", type="jsonrpc", auth="user", methods=["POST"])
    def supervisor_dashboard(self):
        if not request.env.user.has_group("codestra_vicidial_crm.group_supervisor"):
            raise AccessError("Supervisor access is required.")
        agents = request.env["codestra.vicidial.agent"].search(
            [
                ("tenant_id", "=", request.env.user.codestra_tenant_id),
                ("campaign_ids.supervisor_ids", "in", request.env.user.id),
                ("active", "=", True),
            ]
        )
        terminal = ["completed", "failed", "missed", "rejected", "cancelled", "transferred"]
        calls = request.env["codestra.vicidial.call"].search(
            [
                ("agent_id", "in", agents.ids),
                ("state", "not in", terminal),
            ],
            order="write_date desc",
        )
        current = {item.agent_id.id: item for item in calls}
        statuses = {"active": "ready", "paused": "break", "offline": "offline"}
        items = []
        for agent in agents:
            call = current.get(agent.id)
            state = call.state if call else statuses.get(agent.status, "offline")
            items.append(
                {
                    "agent_id": agent.id,
                    "name": agent.name,
                    "extension": agent.phone_login,
                    "status": state,
                    "campaigns": agent.campaign_ids.mapped("campaign_id"),
                    "call_id": call.call_id if call else None,
                    "call_started_at": call.start_at if call else None,
                    "customer": call.customer_id.display_name if call and call.customer_id else None,
                }
            )
        return {
            "agents": items,
            "counts": {
                state: sum(1 for item in items if item["status"] == state)
                for state in {item["status"] for item in items}
            },
            "queue_metrics": {"available": False, "reason": "No authoritative queue snapshot in scope"},
        }

    @http.route("/codestra/call-workspace/v1/calls/<string:call_id>/qa", type="jsonrpc", auth="user", methods=["POST"])
    def qa_score(self, call_id, scores, comment=None, coaching_required=False, submit=True):
        if not request.env.user.has_group("codestra_vicidial_crm.group_qa"):
            raise AccessError("QA access is required.")
        call = self._review_call(call_id)
        categories = (
            "greeting",
            "verification",
            "product_knowledge",
            "compliance",
            "call_control",
            "empathy",
            "closing",
        )
        if not isinstance(scores, dict) or set(scores) != set(categories):
            raise ValidationError("All QA categories are required and unknown categories are denied.")
        review = request.env["codestra.call.qa.review"].create(
            {
                "call_id": call.id,
                **{name: int(scores[name]) for name in categories},
                "comment": comment,
                "coaching_required": bool(coaching_required),
                "state": "submitted" if submit else "draft",
            }
        )
        self._audit(call, "call.qa.scored", {"review_id": review.id, "score": review.score, "state": review.state})
        return {"review_id": review.id, "score": review.score, "state": review.state}

    @http.route(
        "/codestra/call-workspace/v1/qa/<int:review_id>/coaching", type="jsonrpc", auth="user", methods=["POST"]
    )
    def create_coaching(self, review_id, due_date, comments=None):
        if not (
            request.env.user.has_group("codestra_vicidial_crm.group_supervisor")
            or request.env.user.has_group("codestra_vicidial_crm.group_qa")
        ):
            raise AccessError("Supervisor or QA access is required.")
        review = request.env["codestra.call.qa.review"].browse(review_id).exists()
        if not review or review.tenant_id != request.env.user.codestra_tenant_id:
            raise AccessError("The QA review is outside the authorized scope.")
        call = self._review_call(review.call_id.call_id)
        assignee = call.agent_id.odoo_user_id
        if not assignee:
            raise ValidationError("The call agent has no Odoo identity for coaching.")
        coaching = request.env["codestra.call.coaching"].create(
            {
                "name": f"Coaching: {call.call_id}",
                "review_id": review.id,
                "assigned_agent_id": assignee.id,
                "due_date": due_date,
                "comments": comments,
            }
        )
        self._audit(call, "call.coaching.created", {"coaching_id": coaching.id, "assigned_agent_id": assignee.id})
        return {"coaching_id": coaching.id, "state": coaching.state}

    @http.route(
        "/codestra/call-workspace/v1/coaching/<int:coaching_id>/acknowledge",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
    )
    def acknowledge_coaching(self, coaching_id):
        coaching = request.env["codestra.call.coaching"].browse(coaching_id).exists()
        if not coaching:
            raise AccessError("Coaching is unavailable.")
        coaching.action_acknowledge()
        self._audit(coaching.call_id, "call.coaching.acknowledged", {"coaching_id": coaching.id})
        return {"coaching_id": coaching.id, "state": coaching.state, "acknowledged_at": coaching.acknowledged_at}

    @http.route(
        "/codestra/call-workspace/v1/calls/<string:call_id>/tasks", type="jsonrpc", auth="user", methods=["POST"]
    )
    def create_follow_up(self, call_id, summary, due_date, priority="1", note=None, owner_id=None):
        call = self._owned_call(call_id)
        lead = call.crm_lead_id or call.lead_id
        if not lead:
            raise ValidationError("A follow-up requires a correlated CRM lead.")
        owner = request.env["res.users"].browse(int(owner_id)).exists() if owner_id else request.env.user
        if not owner or owner.codestra_tenant_id != call.tenant_id:
            raise AccessError("Task owner is outside the call tenant.")
        activity = request.env["mail.activity"].create(
            {
                "res_model_id": request.env["ir.model"]._get_id("crm.lead"),
                "res_id": lead.id,
                "activity_type_id": request.env.ref("mail.mail_activity_data_todo").id,
                "summary": str(summary)[:256],
                "note": note,
                "date_deadline": due_date,
                "user_id": owner.id,
            }
        )
        self._audit(
            call, "call.follow_up.created", {"activity_id": activity.id, "owner_id": owner.id, "priority": priority}
        )
        return {"activity_id": activity.id, "created": True}

    @staticmethod
    def _command(call, action, key, payload):
        Command = request.env["codestra.call.control.command"]
        raw = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256((call.call_id + "\n" + action + "\n" + raw).encode()).hexdigest()
        prior = Command.search([("idempotency_key", "=", key)], limit=1)
        if prior:
            if prior.request_hash != digest or prior.call_id != call or prior.action != action:
                raise ValidationError("Idempotency-Key conflicts with a different command.")
            return prior, True
        command_action = action
        telephony_action = action in {"outbound", "answer", "decline", "hangup", "hold", "resume", "transfer"}
        command = Command.create(
            {
                "idempotency_key": key,
                "request_hash": digest,
                "call_id": call.id,
                "action": command_action,
                "actor_id": request.env.user.id,
                "correlation_id": call.correlation_id,
                "payload_json": raw,
                "state": "queued" if telephony_action else "confirmed",
            }
        )
        if telephony_action:
            request.env["codestra.integration.event"].sudo().create(
                {
                    "name": f"Call control {action}",
                    "event_type": f"call.command.{action}",
                    "source_system": "odoo",
                    "destination_system": "middleware",
                    "direction": "outbound",
                    "correlation_id": call.correlation_id,
                    "idempotency_key": "command:" + key,
                    "payload_json": json.dumps(
                        {
                            "command_id": command.id,
                            "call_id": call.call_id,
                            "action": action,
                        },
                        sort_keys=True,
                    ),
                    "payload_hash": digest,
                    "state": "queued",
                }
            )
        request.env["codestra.integration.audit"].sudo().create(
            {
                "actor_user_id": request.env.user.id,
                "action": f"call.{action}",
                "model_name": call._name,
                "record_res_id": call.id,
                "correlation_id": call.correlation_id,
                "after_json": json.dumps({"command_id": command.id}),
                "success": True,
            }
        )
        return command, False
