from odoo import api, models
from odoo.exceptions import AccessError, ValidationError


class TestSynRepairService(models.AbstractModel):
    _name = "codestra.vicidial.test.syn.repair"
    _description = "Fail-Closed TEST_SYN Legacy Lead Repair"

    @api.model
    def _enabled(self):
        params = self.env["ir.config_parameter"].sudo()
        enabled = str(
            params.get_param(
                "codestra.telephony.auto_repair_owned_test_syn_leads"
            )
            or ""
        ).strip().lower()
        external_effects = str(
            params.get_param("codestra.telephony.external_effects_enabled")
            or ""
        ).strip().lower()
        return enabled == "true" and external_effects in {
            "",
            "0",
            "false",
            "no",
            "off",
        }

    @api.model
    def _single_test_syn_campaign(self, agent, campaign_code):
        active_campaigns = agent.campaign_ids.filtered(lambda item: item.active)
        if len(active_campaigns) != 1:
            return False
        campaign = active_campaigns[:1]
        if (
            campaign_code != "TEST_SYN"
            or campaign.campaign_id != "TEST_SYN"
            or campaign.mode != "test"
        ):
            return False
        return campaign

    @api.model
    def _authorized_canonical_campaign(self, campaign_code, lead):
        if (
            "call_center_campaign_id" not in lead._fields
            or "call.center.campaign" not in self.env
        ):
            return False

        Campaign = self.env["call.center.campaign"]
        required_fields = {
            "active",
            "authorized_user_ids",
            "business_unit_id",
            "code",
            "state",
        }
        if not required_fields.issubset(Campaign._fields):
            return False
        if not Campaign.check_access_rights("read", raise_exception=False):
            return False

        identity_domain = [("code", "=", campaign_code)]
        if "vicidial_campaign_id" in Campaign._fields:
            identity_domain = [
                "|",
                ("code", "=", campaign_code),
                ("vicidial_campaign_id", "=", campaign_code),
            ]
        try:
            campaigns = Campaign.search(
                [
                    ("active", "=", True),
                    ("state", "=", "active"),
                    ("business_unit_id", "=", lead.business_unit_id.id),
                    ("authorized_user_ids", "in", self.env.user.id),
                    *identity_domain,
                ],
                limit=2,
            )
        except AccessError:
            return False
        if len(campaigns) != 1:
            return False
        campaign = campaigns[:1]
        if (
            campaign.business_unit_id != lead.business_unit_id
            or self.env.user not in campaign.authorized_user_ids
        ):
            return False
        return campaign

    @staticmethod
    def _blocked_destination(record):
        return any(
            bool(record[field])
            for field in ("do_not_call", "x_do_not_call")
            if field in record._fields
        )

    @staticmethod
    def _raw_variants(normalized):
        digits = normalized.removeprefix("+")
        variants = [digits, "00" + digits]
        if len(digits) == 11 and digits.startswith("1"):
            variants.append(digits[1:])
        return tuple(dict.fromkeys(variants))

    @api.model
    def _try_lock_destination(self, normalized):
        self.env.cr.execute(
            "SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))",
            ("codestra:auto-test-syn:" + normalized,),
        )
        row = self.env.cr.fetchone()
        return bool(row and row[0])

    @api.model
    def _lock_lead(self, lead_id):
        self.env.cr.execute(
            "SELECT id FROM crm_lead WHERE id = %s FOR UPDATE",
            (lead_id,),
        )
        return bool(self.env.cr.fetchone())

    @api.model
    def _raw_leads(self, variants):
        return self.env["crm.lead"].sudo().search(
            [
                ("active", "=", True),
                ("x_codestra_phone_digits", "in", variants),
            ],
            order="id",
            limit=3,
        )

    @api.model
    def _raw_partner_exists(self, variants):
        return bool(
            self.env["res.partner"].sudo().search(
                [
                    ("active", "=", True),
                    ("x_codestra_phone_digits", "in", variants),
                ],
                limit=1,
            )
        )

    @api.model
    def repair_owned_lead(self, number, campaign_code, agent):
        """Repair one uniquely indexed, owner-controlled TEST_SYN lead."""
        if not self._enabled():
            return False
        if not self._single_test_syn_campaign(agent, campaign_code):
            return False

        Call = self.env["codestra.vicidial.call"]
        Lead = self.env["crm.lead"]
        Partner = self.env["res.partner"]
        if not Lead.check_access_rights("read", raise_exception=False):
            return False
        if not Lead.check_access_rights("write", raise_exception=False):
            return False
        if (
            "x_codestra_phone_digits" not in Lead._fields
            or "x_codestra_phone_digits" not in Partner._fields
        ):
            return False

        normalized = Call.normalize_number(number)
        variants = self._raw_variants(normalized)
        if not self._try_lock_destination(normalized):
            return False

        if Lead.sudo().search([("x_phone_e164", "=", normalized)], limit=1):
            return False
        if Partner.sudo().search(
            [("x_codestra_phone_e164", "=", normalized)],
            limit=1,
        ):
            return False

        raw_leads = self._raw_leads(variants)
        if len(raw_leads) != 1 or self._raw_partner_exists(variants):
            return False
        lead_id = raw_leads.id
        if not self._lock_lead(lead_id):
            return False

        candidate_fields = [
            "active",
            "business_unit_id",
            "company_id",
            "do_not_call",
            "phone",
            "user_id",
            "vicidial_campaign_id",
            "x_codestra_phone_digits",
            "x_do_not_call",
            "x_phone_e164",
            "x_vicidial_campaign_id",
        ]
        if "call_center_campaign_id" in Lead._fields:
            candidate_fields.append("call_center_campaign_id")
        candidate = Lead.sudo().browse(lead_id).exists()
        if not candidate:
            return False
        candidate.invalidate_recordset(candidate_fields)

        if self._raw_leads(variants).ids != [lead_id]:
            return False
        if self._raw_partner_exists(variants):
            return False
        if Lead.sudo().search([("x_phone_e164", "=", normalized)], limit=1):
            return False
        if Partner.sudo().search(
            [("x_codestra_phone_e164", "=", normalized)],
            limit=1,
        ):
            return False

        if (
            not candidate.active
            or candidate.user_id.id != self.env.user.id
            or candidate.x_phone_e164
            or candidate.x_codestra_phone_digits not in variants
            or candidate.vicidial_campaign_id
            or candidate.x_vicidial_campaign_id
        ):
            return False
        if (
            "call_center_campaign_id" in candidate._fields
            and candidate.call_center_campaign_id
        ):
            return False
        try:
            candidate_normalized = Call.normalize_number(candidate.phone)
        except ValidationError:
            return False
        if candidate_normalized != normalized:
            return False
        if self._blocked_destination(candidate):
            return False
        if not candidate.business_unit_id:
            return False
        if (
            candidate.company_id
            and candidate.company_id not in self.env.user.company_ids
        ):
            return False
        if "call_center_business_unit_ids" in self.env.user._fields:
            authorized_units = self.env.user.call_center_business_unit_ids
            if (
                candidate.business_unit_id not in authorized_units
                and not self.env.user.has_group("base.group_system")
            ):
                return False

        domain = [
            ("id", "=", lead_id),
            ("active", "=", True),
            ("user_id", "=", self.env.user.id),
            ("x_phone_e164", "=", False),
            ("vicidial_campaign_id", "=", False),
            ("x_vicidial_campaign_id", "=", False),
        ]
        if "call_center_campaign_id" in Lead._fields:
            domain.append(("call_center_campaign_id", "=", False))

        visible_lead = Lead.search(domain, limit=1)
        canonical_campaign = False
        if not visible_lead:
            if not self.env.user.has_group(
                "codestra_vicidial_crm.group_agent"
            ):
                return False
            canonical_campaign = self._authorized_canonical_campaign(
                campaign_code,
                candidate,
            )
            if not canonical_campaign:
                return False

        values = {
            "vicidial_campaign_id": campaign_code,
            "x_vicidial_campaign_id": campaign_code,
        }
        if canonical_campaign:
            values["call_center_campaign_id"] = canonical_campaign.id
        write_target = visible_lead or candidate.sudo()
        flush_fields = [
            "x_phone_e164",
            "vicidial_campaign_id",
            "x_vicidial_campaign_id",
        ]
        if canonical_campaign:
            flush_fields.append("call_center_campaign_id")

        try:
            with self.env.cr.savepoint():
                write_target.write(values)
                write_target._compute_codestra_phone()
                write_target.flush_recordset(flush_fields)
                write_target.invalidate_recordset(flush_fields)

                fresh = Lead.search([("id", "=", lead_id)], limit=1)
                if not fresh:
                    raise ValidationError(
                        "Automatic CRM record-rule visibility could not be verified."
                    )
                fresh.invalidate_recordset(flush_fields)
                if fresh.x_phone_e164 != normalized:
                    raise ValidationError(
                        "Automatic CRM phone normalization could not be verified."
                    )
                if (
                    fresh.vicidial_campaign_id != campaign_code
                    or fresh.x_vicidial_campaign_id != campaign_code
                    or (
                        canonical_campaign
                        and fresh.call_center_campaign_id != canonical_campaign
                    )
                ):
                    raise ValidationError(
                        "Automatic CRM campaign assignment could not be verified."
                    )
                return fresh
        except (AccessError, ValidationError):
            return False

