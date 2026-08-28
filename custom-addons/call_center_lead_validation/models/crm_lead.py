import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NON_DIGIT_RE = re.compile(r"\D+")


class CrmLead(models.Model):
    _inherit = "crm.lead"

    alternate_phone = fields.Char()
    normalized_phone = fields.Char(index=True, copy=False)
    normalized_alternate_phone = fields.Char(index=True, copy=False)
    normalized_email = fields.Char(
        string="Call Center Normalized Email", index=True, copy=False
    )
    validation_state = fields.Selection(
        [
            ("pending", "Pending"),
            ("valid", "Valid"),
            ("invalid", "Invalid"),
            ("duplicate", "Possible Duplicate"),
            ("blocked", "Blocked"),
        ],
        default="pending",
        required=True,
        index=True,
        tracking=True,
        copy=False,
    )
    validation_errors = fields.Text(readonly=True, copy=False)
    validation_checked_at = fields.Datetime(readonly=True, copy=False)
    duplicate_candidate_ids = fields.One2many(
        "call.center.duplicate.candidate", "lead_id", copy=False
    )
    source_quality_score = fields.Float(default=50.0)
    qualification_score = fields.Float(default=0.0)
    fraud_risk = fields.Boolean(tracking=True)
    fraud_risk_reason = fields.Char()
    invalid_number = fields.Boolean(readonly=True)
    existing_customer_id = fields.Many2one("res.partner", readonly=True)
    call_attempt_count = fields.Integer(default=0, readonly=True)

    @api.model
    def _normalize_phone_value(self, value):
        if not value:
            return False
        country = self.country_id
        phone_format = (
            self.env["call.center.phone.format"].search(
                [("country_id", "=", country.id), ("active", "=", True)], limit=1
            )
            if country
            else self.env["call.center.phone.format"]
        )
        if phone_format:
            result = phone_format.normalize(value)
            return result["e164"] if result["valid"] else False
        digits = NON_DIGIT_RE.sub("", value)
        if value.strip().startswith("+"):
            return f"+{digits}"
        country = self.country_id or self.env.company.country_id
        if country and country.phone_code and len(digits) <= 10:
            return f"+{country.phone_code}{digits}"
        return f"+{digits}" if digits else False

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._refresh_normalized_fields()
        return records

    def write(self, vals):
        result = super().write(vals)
        if {"phone", "alternate_phone", "email_from", "country_id"} & vals.keys() and not self.env.context.get("skip_call_center_normalize"):
            self._refresh_normalized_fields()
        return result

    def _refresh_normalized_fields(self):
        for lead in self:
            normalized_phone = lead._normalize_phone_value(lead.phone)
            policy_result = lead._evaluate_phone_policy(
                lead.phone, check_consent=False
            )
            super(CrmLead, lead.with_context(skip_call_center_normalize=True)).write(
                {
                    "normalized_phone": normalized_phone,
                    "normalized_alternate_phone": lead._normalize_phone_value(
                        lead.alternate_phone
                    ),
                    "normalized_email": (
                        lead.email_from.strip().lower() if lead.email_from else False
                    ),
                    "phone_validation_result": policy_result["result"],
                    "phone_validation_reason": policy_result["reason"],
                    "phone_number_type": policy_result["number_type"],
                }
            )

    def _evaluate_phone_policy(self, value=None, check_consent=True):
        self.ensure_one()
        campaign = self.call_center_campaign_id
        country = self.country_id
        if not value:
            return {
                "result": "invalid",
                "reason": "empty",
                "e164": False,
                "number_type": "unknown",
            }
        if not country:
            return {
                "result": "invalid",
                "reason": "customer_country_required",
                "e164": False,
                "number_type": "unknown",
            }
        country_policy = (
            campaign.country_policy_ids.filtered(
                lambda item: item.country_id == country and item.active
            )[:1]
            if campaign
            else self.env["call.center.campaign.country.policy"]
        )
        if campaign and campaign.country_policy_ids and (
            not country_policy or country_policy.policy == "blocked"
        ):
            return {
                "result": "blocked_country",
                "reason": "campaign_country_not_allowed",
                "e164": False,
                "number_type": "unknown",
            }
        if (
            country_policy
            and campaign.business_unit_id.company_id.country_id
            and country != campaign.business_unit_id.company_id.country_id
            and not country_policy.international_dialing_allowed
        ):
            return {
                "result": "blocked_country",
                "reason": "international_dialing_not_permitted",
                "e164": False,
                "number_type": "unknown",
            }
        phone_format = (
            country_policy.phone_format_id
            if country_policy
            else self.env["call.center.phone.format"].search(
                [("country_id", "=", country.id), ("active", "=", True)], limit=1
            )
        )
        if not phone_format:
            return {
                "result": "invalid",
                "reason": "phone_format_policy_missing",
                "e164": False,
                "number_type": "unknown",
            }
        normalized = phone_format.normalize(value)
        if not normalized["valid"]:
            return {
                "result": "invalid",
                "reason": normalized["reason"],
                "e164": False,
                "number_type": normalized["number_type"],
            }
        if check_consent and country_policy:
            if country_policy.dnc_enforced and "call.center.suppression" in self.env:
                identifier_hash = self.env["call.center.suppression"].hash_identifier(
                    normalized["e164"]
                )
                if self.env["call.center.suppression"].search_count(
                    [
                        ("identifier_type", "=", "phone"),
                        ("identifier_hash", "=", identifier_hash),
                        ("business_unit_id", "=", self.business_unit_id.id),
                        ("active", "=", True),
                    ]
                ):
                    return {
                        "result": "consent_blocked",
                        "reason": "dnc_suppression",
                        "e164": normalized["e164"],
                        "number_type": normalized["number_type"],
                    }
            if country_policy.consent_required and "call.center.consent" in self.env:
                if not self.env["call.center.consent"].search_count(
                    [
                        ("lead_id", "=", self.id),
                        ("channel", "=", "phone"),
                        ("status", "=", "granted"),
                    ]
                ):
                    return {
                        "result": "consent_blocked",
                        "reason": "phone_consent_missing",
                        "e164": normalized["e164"],
                        "number_type": normalized["number_type"],
                    }
        return {
            "result": "valid_format",
            "reason": "format_only_not_reachability_or_ownership",
            "e164": normalized["e164"],
            "number_type": normalized["number_type"],
        }

    def evaluate_calling_eligibility(self, moment=None, override=False, reason=None):
        self.ensure_one()
        phone_result = self._evaluate_phone_policy(
            self.phone, check_consent=True
        )
        if phone_result["result"] != "valid_format":
            return {"allowed": False, **phone_result}
        policy = self.call_center_campaign_id.country_policy_ids.filtered(
            lambda item: item.country_id == self.country_id and item.active
        )[:1]
        if not policy:
            return {
                "allowed": False,
                "result": "blocked_country",
                "reason": "campaign_country_policy_missing",
            }
        decision = policy.calling_hours_policy_id.evaluate(
            moment=moment,
            country=self.country_id,
            override=override,
            reason=reason,
        )
        return {**phone_result, **decision}

    def _validation_error_list(self):
        self.ensure_one()
        errors = []
        if not self.name:
            errors.append("missing_name")
        if not self.normalized_phone and not self.normalized_email:
            errors.append("missing_phone_and_email")
        if self.normalized_phone and not 8 <= len(self.normalized_phone.lstrip("+")) <= 15:
            errors.append("invalid_phone")
        if self.normalized_email and not EMAIL_RE.match(self.normalized_email):
            errors.append("invalid_email")
        if not self.business_unit_id:
            errors.append("missing_business_unit")
        if self.call_center_campaign_id and self.call_center_campaign_id.business_unit_id != self.business_unit_id:
            errors.append("campaign_business_unit_mismatch")
        if self.fraud_risk:
            errors.append("fraud_risk")
        return errors

    def action_validate_lead(self):
        for lead in self:
            lead._refresh_normalized_fields()
            lead.duplicate_candidate_ids.unlink()
            domain_parts = []
            if lead.normalized_phone:
                domain_parts.append(("normalized_phone", "=", lead.normalized_phone))
            if lead.normalized_email:
                domain_parts.append(("normalized_email", "=", lead.normalized_email))
            if lead.external_source_id:
                domain_parts.append(("external_source_id", "=", lead.external_source_id))
            candidates = self.browse()
            for field_name, operator, value in domain_parts:
                candidates |= self.search(
                    [
                        ("id", "!=", lead.id),
                        ("business_unit_id", "=", lead.business_unit_id.id),
                        (field_name, operator, value),
                    ],
                    limit=20,
                )
            for candidate in candidates:
                reasons = []
                if lead.normalized_phone and candidate.normalized_phone == lead.normalized_phone:
                    reasons.append("phone")
                if lead.normalized_email and candidate.normalized_email == lead.normalized_email:
                    reasons.append("email")
                if lead.external_source_id and candidate.external_source_id == lead.external_source_id:
                    reasons.append("external_source_id")
                self.env["call.center.duplicate.candidate"].create(
                    {
                        "lead_id": lead.id,
                        "candidate_lead_id": candidate.id,
                        "match_reasons": ",".join(reasons),
                        "confidence": min(100, 40 * len(reasons)),
                    }
                )
            partner_domain = []
            if lead.normalized_email:
                partner_domain = [("email_normalized", "=", lead.normalized_email)]
            lead.existing_customer_id = (
                self.env["res.partner"].search(partner_domain, limit=1)
                if partner_domain
                else False
            )
            errors = lead._validation_error_list()
            if candidates:
                state = "duplicate"
            elif errors:
                state = "invalid"
            else:
                state = "valid"
            lead.with_context(skip_call_center_normalize=True).write(
                {
                    "validation_state": state,
                    "validation_errors": "\n".join(errors) or False,
                    "validation_checked_at": fields.Datetime.now(),
                    "invalid_number": "invalid_phone" in errors,
                }
            )
            self.env["call.center.audit.event"].sudo().create(
                {
                    "business_unit_id": lead.business_unit_id.id,
                    "event_type": "lead.validated",
                    "model_name": lead._name,
                    "record_id": lead.id,
                    "new_values_json": {
                        "state": state,
                        "errors": errors,
                        "duplicate_count": len(candidates),
                    },
                }
            )
        return True

    def action_assign_by_campaign(self):
        for lead in self:
            campaign = lead.call_center_campaign_id
            if not campaign:
                raise ValidationError("A campaign is required before routing.")
            if lead.validation_state != "valid":
                raise ValidationError("Only validated leads may be routed.")
            agents = campaign.agent_ids.filtered(
                lambda user: user.active
                and lead.business_unit_id in user.call_center_business_unit_ids
            ).sorted("id")
            if not agents:
                raise ValidationError("No authorized active campaign agents are available.")
            if campaign.routing_strategy == "manual":
                continue
            counts = {
                agent.id: self.search_count(
                    [
                        ("user_id", "=", agent.id),
                        ("call_center_campaign_id", "=", campaign.id),
                        ("active", "=", True),
                    ]
                )
                for agent in agents
            }
            lead.user_id = min(agents, key=lambda agent: (counts[agent.id], agent.id))
        return True
