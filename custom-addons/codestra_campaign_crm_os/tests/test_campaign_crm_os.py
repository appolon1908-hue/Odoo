from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged
from ..hooks import GLOBAL_AUTOMATIONS, WORKFLOWS, post_init_hook
from ..controllers.automation_actions import CodestraCampaignAutomationActionController


@tagged("post_install","-at_install")
class CampaignCRMOSTest(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        parameters = cls.env["ir.config_parameter"].sudo()
        parameters.set_param("codestra.integration.environment", "TEST")
        parameters.set_param("codestra.integration.organization_public_id", "codestra-test")
        post_init_hook(cls.env)

    def test_five_distinct_workflows_and_required_fixtures(self):
        workflows=self.env["codestra.campaign.workflow"].with_context(active_test=False).search([])
        self.assertEqual(set(workflows.mapped("key")),{"transportation","codestra_development","moneybee","senior_products","student_repayment"})
        canonical = {
            "transportation": "MOY-SHIPPER-OUT",
            "codestra_development": "COD-WEB-OUT",
            "moneybee": "MBL-NEW-LOAN-OUT",
            "senior_products": "SCP-PRODUCT-OUT",
            "student_repayment": "SRP-STUDENT-OUT",
        }
        self.assertTrue(all(not row.active and row.lifecycle_state == "DRAFT" for row in workflows))
        self.assertTrue(all(not row.campaign_id or row.campaign_id.code == canonical[row.key] for row in workflows))
        self.assertIn("QUOTE_SENT",workflows.filtered(lambda x:x.key=="transportation").status_ids.mapped("code"))
        self.assertIn("FUNDED",workflows.filtered(lambda x:x.key=="moneybee").status_ids.mapped("code"))

    def test_complete_campaign_automation_catalog_is_registered_inactive(self):
        Automation = self.env["codestra.campaign.automation"].with_context(active_test=False)
        for workflow_key, spec in WORKFLOWS.items():
            expected = {key: key for key in spec["automations"]}
            expected.update(GLOBAL_AUTOMATIONS)
            expected.update({
                f"{workflow_key}_{action.lower()}": "CDST_FollowupDue_v1"
                for action in spec["followups"].values()
            })
            rows = Automation.search([
                ("workflow_id.key", "=", workflow_key),
                ("key", "in", sorted(expected)),
            ])
            self.assertEqual(set(rows.mapped("key")), set(expected))
            self.assertFalse(any(rows.mapped("active")))
            self.assertEqual({row.key: row.n8n_workflow_key for row in rows}, expected)

    def test_cod_web_out_template_contract_is_safe_and_versioned(self):
        templates=self.env["mail.template"].search([
            ("codestra_template_key","like","cod_web_out_%_v1")
        ])
        self.assertEqual(len(templates),12)
        for template in templates:
            self.assertEqual(template.codestra_template_version,1)
            self.assertEqual(template.codestra_locale,"en_US")
            self.assertTrue(template.codestra_plain_body)
            self.assertTrue(template.body_html)
            self.assertEqual(template.codestra_sender_identity_ref,"SALES_SENDER")
            self.assertEqual(template.codestra_reply_to_identity_ref,"SUPPORT_REPLY_TO")
            self.assertNotIn("password",template.body_html.lower())

    def test_system_canary_profile_is_fail_closed(self):
        unit=self.env["call.center.business.unit"].search([],limit=1)
        campaign=self.env["call.center.campaign"].create({
            "name":"Canary Campaign","code":"CANARY-PROFILE-TEST",
            "business_unit_id":unit.id,"active":False,
        })
        profile=self.env["codestra.agent.profile"].create({
            "name":"System Canary","agent_type":"SYSTEM_CANARY",
            "campaign_ids":[(6,0,campaign.ids)],"canary_only":True,
            "customer_traffic_allowed":False,"daily_capacity":1,
        })
        self.assertFalse(profile.user_id)
        with self.assertRaises(ValidationError):
            profile.customer_traffic_allowed=True

    def test_disposition_mapping_is_workflow_scoped(self):
        Mapping=self.env["codestra.campaign.disposition.mapping"]
        quote=Mapping.search([("workflow_id.key","=","transportation"),("disposition_code","=","QUOTE")])
        self.assertEqual(quote.status_id.code,"QUOTE_REQUESTED")
        self.assertFalse(Mapping.search([("workflow_id.key","=","moneybee"),("disposition_code","=","QUOTE")]))

    def test_impossible_transition_and_required_fields_are_rejected(self):
        workflow=self.env["codestra.campaign.workflow"].with_context(active_test=False).search([("key","=","moneybee")],limit=1)
        lead=self.env["crm.lead"].create({"name":"Synthetic MoneyBee","codestra_workflow_id":workflow.id})
        new=workflow.status_ids.filtered(lambda x:x.code=="NEW_BUSINESS_LEAD")
        funded=workflow.status_ids.filtered(lambda x:x.code=="FUNDED")
        lead.codestra_current_status_id=new
        with self.assertRaises(ValidationError): lead.action_codestra_transition(funded.id)
        documents=workflow.status_ids.filtered(lambda x:x.code=="DOCUMENTS_REQUESTED")
        lead.codestra_current_status_id=workflow.status_ids.filtered(lambda x:x.code=="PREQUALIFIED")
        with self.assertRaises(ValidationError): lead.action_codestra_transition(documents.id)

    def test_next_action_and_ai_attribution(self):
        workflow=self.env["codestra.campaign.workflow"].with_context(active_test=False).search([("key","=","codestra_development")],limit=1)
        unit=self.env["call.center.business.unit"].search([],limit=1)
        campaign=self.env["call.center.campaign"].create({"name":"Synthetic Development","code":"SYN-DEV-CRM-OS","business_unit_id":unit.id,"state":"draft"})
        workflow.campaign_id=campaign
        lead=self.env["crm.lead"].create({"name":"Synthetic Development","business_unit_id":unit.id,"is_codestra_call_center_lead":True,"call_center_campaign_id":campaign.id,"codestra_workflow_id":workflow.id,"user_id":self.env.user.id})
        connected=workflow.status_ids.filtered(lambda x:x.code=="CONNECTED")
        needs=workflow.status_ids.filtered(lambda x:x.code=="NEEDS_DISCOVERY")
        lead.codestra_current_status_id=connected
        lead.action_codestra_transition(needs.id,{"correlation_id":"synthetic-ai-correlation"},actor_type="AI",automation_id="synthetic-ai",model_or_service="isolated-model")
        event=self.env["codestra.activity.timeline"].search([("correlation_id","=","synthetic-ai-correlation")])
        self.assertEqual(event.actor_type,"AI"); self.assertEqual(event.actor_id,"synthetic-ai"); self.assertEqual(event.model_or_service,"isolated-model")

    def test_ai_profile_cannot_masquerade_without_attribution(self):
        with self.assertRaises(ValidationError): self.env["codestra.agent.profile"].create({"name":"Invalid AI","agent_type":"AI"})

    def test_campaign_action_route_is_explicit(self):
        routes = CodestraCampaignAutomationActionController.apply_campaign_actions.original_routing["routes"]
        self.assertEqual(routes, ["/api/v1/integration/campaign-actions"])

    def test_campaign_action_service_is_fail_closed_until_explicit_activation(self):
        workflow, campaign = self._bound_workflow("transportation", "ACTION-DENIED")
        lead = self.env["crm.lead"].create({
            "name": "Synthetic Denied Action", "business_unit_id": campaign.business_unit_id.id,
            "is_codestra_call_center_lead": True, "call_center_campaign_id": campaign.id,
            "codestra_workflow_id": workflow.id, "user_id": self.env.user.id,
        })
        with self.assertRaises(AccessError):
            self.env["codestra.campaign.action.service"].apply({
                "campaign_public_id": campaign.code,
                "business_unit_public_id": campaign.business_unit_id.code,
                "workflow_key": "CDST_" + "FollowupDue_v1", "actor_type": "SYSTEM",
                "actor_id": "codestra-middleware", "event_id": "event-denied",
                "execution_id": "execution-denied", "correlation_id": "correlation-denied",
                "actions": [{"action_type": "SET_NEXT_ACTION", "entity_type": "crm.lead",
                    "entity_id": str(lead.id), "values": {"next_action_type": "CALL",
                    "next_action_at": fields.Datetime.to_string(fields.Datetime.now() + timedelta(hours=1)),
                    "next_action_owner_id": self.env.user.id}}],
            })

    def test_campaign_action_service_applies_scoped_system_next_action(self):
        workflow, campaign = self._bound_workflow("moneybee", "ACTION-APPLY")
        workflow.lifecycle_state = "ACTIVE"
        automation = self.env["codestra.campaign.automation"].with_context(active_test=False).search([
            ("workflow_id", "=", workflow.id), ("n8n_workflow_key", "=", "CDST_FollowupDue_v1")
        ], limit=1)
        automation.active = True
        lead = self.env["crm.lead"].create({
            "name": "Synthetic Applied Action", "business_unit_id": campaign.business_unit_id.id,
            "is_codestra_call_center_lead": True, "call_center_campaign_id": campaign.id,
            "codestra_workflow_id": workflow.id, "user_id": self.env.user.id,
        })
        due_at = fields.Datetime.to_string(fields.Datetime.now() + timedelta(hours=1))
        result = self.env["codestra.campaign.action.service"].apply({
            "campaign_public_id": campaign.code,
            "business_unit_public_id": campaign.business_unit_id.code,
            "workflow_key": "CDST_" + "FollowupDue_v1", "actor_type": "SYSTEM",
            "actor_id": "codestra-middleware", "event_id": "event-applied",
            "execution_id": "execution-applied", "correlation_id": "correlation-applied",
            "actions": [{"action_type": "SET_NEXT_ACTION", "entity_type": "crm.lead",
                "entity_id": str(lead.id), "values": {"next_action_type": "CALL",
                "next_action_at": due_at, "next_action_owner_id": self.env.user.id}}],
        })
        self.assertEqual(result["status"], "APPLIED")
        self.assertEqual(lead.next_action_type, "CALL")
        event = self.env["codestra.activity.timeline"].search([
            ("correlation_id", "=", "correlation-applied"), ("action", "=", "next_action.set")
        ])
        self.assertEqual(len(event), 1)
        self.assertEqual(event.actor_type, "SYSTEM")

    def test_campaign_action_service_attributes_system_summary(self):
        workflow, campaign = self._bound_workflow("moneybee", "SUMMARY-APPLY")
        workflow.lifecycle_state = "ACTIVE"
        automation = self.env["codestra.campaign.automation"].with_context(active_test=False).search([
            ("workflow_id", "=", workflow.id), ("n8n_workflow_key", "=", "moneybee_offer_sent")
        ], limit=1)
        automation.active = True
        lead = self.env["crm.lead"].create({
            "name": "Synthetic Summary Action", "business_unit_id": campaign.business_unit_id.id,
            "is_codestra_call_center_lead": True, "call_center_campaign_id": campaign.id,
            "codestra_workflow_id": workflow.id, "user_id": self.env.user.id,
        })
        result = self.env["codestra.campaign.action.service"].apply({
            "campaign_public_id": campaign.code,
            "business_unit_public_id": campaign.business_unit_id.code,
            "workflow_key": "moneybee_offer_sent", "actor_type": "SYSTEM",
            "actor_id": "middleware-system", "event_id": "event-summary",
            "execution_id": "execution-summary", "correlation_id": "correlation-summary",
            "actions": [{"action_type": "CREATE_INTERNAL_SUMMARY", "entity_type": "crm.lead",
                "entity_id": str(lead.id), "values": {"body": "Bound system summary"}}],
        })
        self.assertEqual(result["status"], "APPLIED")
        note = self.env["codestra.campaign.note"].search([
            ("lead_id", "=", lead.id), ("correlation_id", "=", "correlation-summary")
        ], limit=1)
        self.assertEqual(note.author_id, self.env.ref("base.user_admin"))
        self.assertEqual(note.actor_type, "SYSTEM")
        self.assertEqual(note.actor_id, "middleware-system")
        event = self.env["codestra.activity.timeline"].search([
            ("lead_id", "=", lead.id), ("correlation_id", "=", "correlation-summary")
        ], limit=1)
        self.assertEqual(event.actor_id, "middleware-system")

    def test_outbox_materializes_scoped_authorized_action_plan(self):
        workflow, campaign = self._bound_workflow("moneybee", "OUTBOX-PLAN")
        workflow.lifecycle_state = "ACTIVE"
        automation = self.env["codestra.campaign.automation"].with_context(active_test=False).search([
            ("workflow_id", "=", workflow.id), ("key", "=", "moneybee_offer_sent")
        ], limit=1)
        automation.write({
            "active": True,
            "allowed_action_types": ["CREATE_INTERNAL_SUMMARY"],
            "action_plan": [{"action_type": "CREATE_INTERNAL_SUMMARY",
                "values": {"body": "Offer follow-up automation started."}}],
        })
        lead = self.env["crm.lead"].create({
            "name": "Synthetic Planned Action", "business_unit_id": campaign.business_unit_id.id,
            "is_codestra_call_center_lead": True, "call_center_campaign_id": campaign.id,
            "codestra_workflow_id": workflow.id, "user_id": self.env.user.id,
        })
        event = self.env["codestra.crm.outbox"].create_event(
            event_type="crm.campaign.automation.requested.v1", aggregate=lead,
            aggregate_version=1, correlation_id="correlation-plan",
            idempotency_key="automation-plan:event-1", campaign=campaign,
            payload={"lead_id": lead.id, "workflow_key": "moneybee_offer_sent"},
        )
        self.assertEqual(event.payload["workflow_key"], "moneybee_offer_sent")
        self.assertEqual(event.payload["authorized_actions"], [{
            "action_type": "CREATE_INTERNAL_SUMMARY", "entity_type": "crm.lead",
            "entity_id": str(lead.id), "values": {"body": "Offer follow-up automation started."},
        }])

    def test_action_plan_configuration_cannot_select_entity_target(self):
        workflow, _campaign = self._bound_workflow("transportation", "PLAN-TARGET-DENIED")
        automation = self.env["codestra.campaign.automation"].with_context(active_test=False).search([
            ("workflow_id", "=", workflow.id), ("key", "=", "transportation_quote_requested")
        ], limit=1)
        with self.assertRaises(ValidationError):
            automation.write({
                "allowed_action_types": ["CREATE_INTERNAL_SUMMARY"],
                "action_plan": [{"action_type": "CREATE_INTERNAL_SUMMARY", "entity_id": "999",
                    "values": {"body": "Forbidden arbitrary target"}}],
            })

    def test_outbox_rejects_caller_supplied_authorized_actions(self):
        workflow, campaign = self._bound_workflow("student_repayment", "PLAN-INJECTION-DENIED")
        lead = self.env["crm.lead"].create({
            "name": "Synthetic Injection", "business_unit_id": campaign.business_unit_id.id,
            "is_codestra_call_center_lead": True, "call_center_campaign_id": campaign.id,
            "codestra_workflow_id": workflow.id, "user_id": self.env.user.id,
        })
        with self.assertRaises(ValidationError):
            self.env["codestra.crm.outbox"].create_event(
                event_type="crm.campaign.automation.requested.v1", aggregate=lead,
                aggregate_version=1, correlation_id="correlation-injection",
                idempotency_key="automation-plan:injection", campaign=campaign,
                payload={"lead_id": lead.id, "workflow_key": "student_submission",
                    "authorized_actions": []},
            )

    def test_legacy_lead_is_preserved_for_explicit_migration_review(self):
        lead=self.env["crm.lead"].create({"name":"Legacy Unmapped Lead"})
        self.assertFalse(lead.migration_review_required)
        post_init_hook(self.env)
        self.assertTrue(lead.migration_review_required)
        self.assertFalse(lead.call_center_campaign_id)
        self.assertFalse(lead.codestra_workflow_id)

    def _bound_workflow(self, key, suffix):
        workflow = self.env["codestra.campaign.workflow"].with_context(active_test=False).search([("key", "=", key)], limit=1)
        unit = self.env["call.center.business.unit"].search([], limit=1)
        campaign = self.env["call.center.campaign"].create({
            "name": f"Synthetic {suffix}", "code": f"SYN-{suffix}",
            "business_unit_id": unit.id, "state": "draft",
        })
        workflow.write({"campaign_id": campaign.id, "active": True})
        return workflow, campaign

    def test_appointment_automation_uses_durable_outbox(self):
        workflow, campaign = self._bound_workflow("transportation", "APPOINTMENT")
        appointment = self.env["codestra.crm.appointment"].create({
            "campaign_id": campaign.id,
            "appointment_type_id": workflow.appointment_type_ids[:1].id,
            "assigned_agent_id": self.env.user.id,
            "supervisor_id": self.env.user.id,
            "scheduled_start": fields.Datetime.now() + timedelta(hours=24),
            "scheduled_end": fields.Datetime.now() + timedelta(hours=25),
            "timezone": "UTC", "meeting_channel": "PHONE",
            "correlation_id": "synthetic-appointment-correlation",
        })
        appointment.action_schedule_confirmation()
        event = self.env["codestra.crm.outbox"].search([
            ("idempotency_key", "=", f"appointment:{appointment.appointment_uuid}:confirmation")
        ])
        self.assertEqual(len(event), 1)
        self.assertEqual(event.event_type, "crm.appointment.created.v1")
        with self.assertRaises(AccessError):
            self.env["codestra.crm.outbox"].create({
                "event_type": "crm.forbidden.direct.v1",
                "aggregate_type": appointment._name,
                "aggregate_record_id": appointment.id,
                "aggregate_uuid": appointment.appointment_uuid,
                "aggregate_version": 1,
                "campaign_id": campaign.id,
                "correlation_id": "forbidden-direct-create",
                "idempotency_key": "forbidden-direct-create",
                "payload": {},
            })

    def test_notes_are_campaign_scoped_and_immutable(self):
        workflow, campaign = self._bound_workflow("senior_products", "NOTES")
        lead = self.env["crm.lead"].create({
            "name": "Synthetic Note Lead", "business_unit_id": campaign.business_unit_id.id,
            "is_codestra_call_center_lead": True, "call_center_campaign_id": campaign.id,
            "codestra_workflow_id": workflow.id, "user_id": self.env.user.id,
        })
        note = self.env["codestra.campaign.note"].create({
            "campaign_id": campaign.id, "lead_id": lead.id, "body": "Synthetic internal note",
            "visibility": "INTERNAL", "correlation_id": "synthetic-note-correlation",
        })
        timeline = self.env["codestra.activity.timeline"].search([
            ("correlation_id", "=", "synthetic-note-correlation")
        ])
        self.assertEqual(len(timeline), 1)
        self.assertEqual(timeline.event_type, "INTERNAL_NOTE")
        with self.assertRaises(AccessError):
            note.unlink()

    def test_cross_campaign_transfer_is_fail_closed(self):
        _, source = self._bound_workflow("moneybee", "TRANSFER-SOURCE")
        _, target = self._bound_workflow("student_repayment", "TRANSFER-TARGET")
        policy = self.env["codestra.campaign.transfer.policy"].create({
            "campaign_id": source.id, "transfer_type": "AGENT_TO_CLOSER",
        })
        self.assertEqual(
            self.env["codestra.campaign.transfer.policy"].authorize(source, "AGENT_TO_CLOSER"),
            policy,
        )
        with self.assertRaises(AccessError):
            self.env["codestra.campaign.transfer.policy"].authorize(source, "AGENT_TO_CLOSER", target)

    def test_daily_report_is_campaign_specific_and_idempotent(self):
        workflow, campaign = self._bound_workflow("codestra_development", "REPORT")
        self.env["crm.lead"].create({
            "name": "Synthetic Report Lead", "business_unit_id": campaign.business_unit_id.id,
            "is_codestra_call_center_lead": True, "call_center_campaign_id": campaign.id,
            "codestra_workflow_id": workflow.id, "user_id": self.env.user.id,
        })
        report_date = fields.Date.context_today(self.env.user)
        self.env["codestra.daily.operations.report"].generate(report_date)
        self.env["codestra.daily.operations.report"].generate(report_date)
        reports = self.env["codestra.daily.operations.report"].search([
            ("report_date", "=", report_date), ("campaign_id", "=", campaign.id)
        ])
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports.metrics["leads_total"], 1)
        self.assertIn("kpis", reports.metrics)

    def test_required_transition_values_are_persisted_and_override_is_audited(self):
        workflow, campaign = self._bound_workflow("transportation", "REQUIRED-FIELDS")
        lead = self.env["crm.lead"].create({
            "name": "Synthetic Quote", "business_unit_id": campaign.business_unit_id.id,
            "is_codestra_call_center_lead": True, "call_center_campaign_id": campaign.id,
            "codestra_workflow_id": workflow.id, "user_id": self.env.user.id,
        })
        quote_sent = workflow.status_ids.filtered(lambda row: row.code == "QUOTE_SENT")
        lead.action_codestra_transition(quote_sent.id, {
            "quote_reference": "SYN-QUOTE-1", "quote_sent_at": fields.Datetime.now(),
            "next_action_owner_id": self.env.user.id,
        }, override_reason="Synthetic administrator test")
        self.assertEqual(lead.quote_reference, "SYN-QUOTE-1")
        event = self.env["codestra.activity.timeline"].search([("lead_id", "=", lead.id)], limit=1)
        self.assertEqual(event.action, "status.override")
        self.assertEqual(event.safe_detail["override_reason"], "Synthetic administrator test")

    def test_document_scope_ai_policy_and_sms_consent_are_fail_closed(self):
        workflow, campaign = self._bound_workflow("moneybee", "BOUNDED")
        lead = self.env["crm.lead"].create({
            "name": "Synthetic Bounded Lead", "business_unit_id": campaign.business_unit_id.id,
            "is_codestra_call_center_lead": True, "call_center_campaign_id": campaign.id,
            "codestra_workflow_id": workflow.id, "user_id": self.env.user.id,
        })
        status = workflow.status_ids.filtered(lambda row: row.code == "DOCUMENTS_REQUESTED")
        definition = self.env["codestra.campaign.document.definition"].create({
            "workflow_id": workflow.id, "document_type": "BANK_STATEMENTS",
            "required_at_status_id": status.id,
        })
        document = self.env["codestra.campaign.document"].create({
            "definition_id": definition.id, "campaign_id": campaign.id, "lead_id": lead.id,
            "correlation_id": "synthetic-document",
        })
        document.action_set_state("RECEIVED", "protected://synthetic/document")
        self.assertEqual(document.state, "RECEIVED")
        with self.assertRaises(ValidationError):
            self.env["codestra.campaign.communication"].create({
                "channel": "SMS", "direction": "OUTBOUND", "campaign_id": campaign.id,
                "lead_id": lead.id, "correlation_id": "synthetic-sms",
                "idempotency_key": "synthetic-sms-no-consent",
            })
        ai = self.env["codestra.agent.profile"].create({
            "name": "Synthetic AI", "agent_type": "AI", "automation_name": "test",
            "model_or_service": "isolated", "permissions": ["CREATE_INTERNAL_SUMMARY"],
        })
        task = self.env["codestra.ai.task"].create({
            "agent_id": ai.id, "lead_id": lead.id, "task_type": "SUMMARIZE_LATEST_INTERACTION",
            "allowed_actions": ["CREATE_INTERNAL_SUMMARY"], "correlation_id": "synthetic-ai-task",
        })
        self.assertFalse(task.action_apply_result("CHANGE_FINANCIAL_STATE"))
        self.assertEqual(task.state, "DENIED")

    def test_role_and_cross_campaign_lead_visibility(self):
        Users = self.env["res.users"].sudo()
        unit_a = self.env["call.center.business.unit"].sudo().create({
            "name": "Synthetic RBAC A", "code": "SYN-RBAC-A",
        })
        unit_b = self.env["call.center.business.unit"].sudo().create({
            "name": "Synthetic RBAC B", "code": "SYN-RBAC-B",
        })

        def scoped_user(role, suffix, units):
            group = self.env.ref(f"call_center_core.group_call_center_{role}")
            return Users.create({
                "name": f"Synthetic {suffix}",
                "login": f"synthetic-{suffix.lower()}@example.invalid",
                "group_ids": [(6, 0, group.ids)],
                "call_center_business_unit_ids": [(6, 0, units.ids)],
                "call_center_default_business_unit_id": units[:1].id,
            })

        agent_a = scoped_user("agent", "Agent-A", unit_a)
        other_a = scoped_user("agent", "Agent-Other-A", unit_a)
        ai_a = scoped_user("agent", "AI-A", unit_a)
        supervisor_a = scoped_user("supervisor", "Supervisor-A", unit_a)
        manager_a = scoped_user("manager", "Manager-A", unit_a)
        admin = scoped_user("admin", "Admin-Global", unit_a | unit_b)
        campaign_a = self.env["call.center.campaign"].sudo().create({
            "name": "Synthetic RBAC Campaign A", "code": "SYN-RBAC-CAMPAIGN-A",
            "business_unit_id": unit_a.id,
            "authorized_user_ids": [(6, 0, (agent_a | other_a | ai_a | supervisor_a | manager_a).ids)],
            "agent_ids": [(6, 0, (agent_a | other_a | ai_a).ids)],
            "supervisor_ids": [(6, 0, supervisor_a.ids)],
        })
        campaign_b = self.env["call.center.campaign"].sudo().create({
            "name": "Synthetic RBAC Campaign B", "code": "SYN-RBAC-CAMPAIGN-B",
            "business_unit_id": unit_b.id,
            "authorized_user_ids": [(6, 0, admin.ids)],
        })
        human_profile = self.env["codestra.agent.profile"].sudo().create({
            "name": "Synthetic Human A", "user_id": agent_a.id,
            "agent_type": "HUMAN", "campaign_ids": [(6, 0, campaign_a.ids)],
        })
        ai_profile = self.env["codestra.agent.profile"].sudo().create({
            "name": "Synthetic AI A", "user_id": ai_a.id, "agent_type": "AI",
            "campaign_ids": [(6, 0, campaign_a.ids)], "automation_name": "synthetic-rbac",
            "model_or_service": "isolated-test-model",
        })
        lead_human = self.env["crm.lead"].sudo().create({
            "name": "Synthetic Agent A Lead", "business_unit_id": unit_a.id,
            "call_center_campaign_id": campaign_a.id, "user_id": agent_a.id,
            "assigned_agent_profile_id": human_profile.id,
        })
        lead_other = self.env["crm.lead"].sudo().create({
            "name": "Synthetic Other A Lead", "business_unit_id": unit_a.id,
            "call_center_campaign_id": campaign_a.id, "user_id": other_a.id,
        })
        lead_ai = self.env["crm.lead"].sudo().create({
            "name": "Synthetic AI A Lead", "business_unit_id": unit_a.id,
            "call_center_campaign_id": campaign_a.id, "user_id": ai_a.id,
            "assigned_agent_profile_id": ai_profile.id,
        })
        lead_b = self.env["crm.lead"].sudo().create({
            "name": "Synthetic Campaign B Lead", "business_unit_id": unit_b.id,
            "call_center_campaign_id": campaign_b.id,
        })

        def visible(user):
            return set(self.env["crm.lead"].with_user(user).search([
                ("id", "in", (lead_human | lead_other | lead_ai | lead_b).ids)
            ]).ids)

        self.assertEqual(visible(agent_a), {lead_human.id})
        self.assertEqual(visible(ai_a), {lead_ai.id})
        self.assertEqual(visible(supervisor_a), {lead_human.id, lead_other.id, lead_ai.id})
        self.assertEqual(visible(manager_a), {lead_human.id, lead_other.id, lead_ai.id})
        self.assertEqual(visible(admin), {lead_human.id, lead_other.id, lead_ai.id, lead_b.id})

    def test_case_and_complaint_are_separate_audited_queues(self):
        workflow, campaign = self._bound_workflow("student_repayment", "CASE")
        customer = self.env["res.partner"].create({"name": "Synthetic Case Customer"})
        lead = self.env["crm.lead"].create({
            "name": "Synthetic Case Lead", "partner_id": customer.id,
            "business_unit_id": campaign.business_unit_id.id,
            "call_center_campaign_id": campaign.id, "codestra_workflow_id": workflow.id,
            "user_id": self.env.user.id,
        })
        case = self.env["codestra.contact.center.case"].create({
            "customer_id": customer.id, "lead_id": lead.id, "campaign_id": campaign.id,
            "case_type": "SUPPORT", "category": "Synthetic", "owner_id": self.env.user.id,
            "sla_due_at": fields.Datetime.now() + timedelta(hours=4),
        })
        self.assertTrue(case.case_number.startswith("CASE-"))
        case.action_transition("OPEN")
        case.action_transition("RESOLVED", resolution="Synthetic resolution")
        self.assertEqual(case.state, "RESOLVED")
        self.assertTrue(self.env["codestra.activity.timeline"].search_count([
            ("correlation_id", "=", case.correlation_id), ("action", "=", "case.transition")
        ]))
        complaint = self.env["codestra.contact.center.complaint"].create({
            "customer_id": customer.id, "campaign_id": campaign.id,
            "owner_id": self.env.user.id, "customer_impact": "Synthetic only",
        })
        self.assertEqual(complaint.state, "RECEIVED")
        self.assertNotEqual(case._name, complaint._name)

    def test_qa_coaching_and_ai_identity_remain_campaign_scoped(self):
        _, campaign = self._bound_workflow("transportation", "QA")
        profile = self.env["codestra.agent.profile"].create({
            "name": "Synthetic QA Agent", "agent_type": "HUMAN", "user_id": self.env.user.id,
            "campaign_ids": [(6, 0, campaign.ids)],
        })
        scorecard = self.env["codestra.qa.scorecard"].create({
            "name": "Synthetic Transportation QA", "campaign_id": campaign.id,
            "criterion_ids": [(0, 0, {"code": "DISCLOSURE", "name": "Required disclosure", "weight": 1.0, "critical_error": True})],
        })
        review = self.env["codestra.qa.review"].create({
            "scorecard_id": scorecard.id, "agent_id": profile.id, "score": 72,
            "critical_error": True, "coaching_required": True,
        })
        coaching = self.env["codestra.coaching.session"].create({
            "qa_review_id": review.id, "campaign_id": campaign.id, "agent_id": profile.id,
            "coach_id": self.env.user.id, "reason": "Synthetic QA finding",
            "action_plan": "Review disclosure playbook", "due_at": fields.Datetime.now() + timedelta(days=2),
        })
        coaching.action_acknowledge()
        self.assertEqual(coaching.state, "ACKNOWLEDGED")
        self.assertTrue(coaching.acknowledged_at)

    def test_agent_state_workforce_knowledge_and_contact_policy(self):
        workflow, campaign = self._bound_workflow("senior_products", "WORKFORCE")
        campaign.write({"authorized_user_ids": [(4, self.env.user.id)], "agent_ids": [(4, self.env.user.id)]})
        profile = self.env["codestra.agent.profile"].create({
            "name": "Synthetic Workforce Agent", "agent_type": "HUMAN", "user_id": self.env.user.id,
            "campaign_ids": [(6, 0, campaign.ids)],
        })
        first = self.env["codestra.agent.state.event"].transition(profile, "AVAILABLE", campaign, "state-available")
        second = self.env["codestra.agent.state.event"].transition(profile, "ON_CALL", campaign, "state-on-call")
        self.assertTrue(first.ended_at)
        self.assertFalse(second.ended_at)
        shift = self.env["codestra.workforce.shift"].create({
            "agent_id": profile.id, "campaign_id": campaign.id,
            "scheduled_start": fields.Datetime.now() + timedelta(days=1),
            "scheduled_end": fields.Datetime.now() + timedelta(days=1, hours=8),
            "timezone": "UTC",
        })
        self.assertEqual(shift.state, "SCHEDULED")
        article = self.env["codestra.campaign.knowledge.article"].create({
            "title": "Synthetic Product Disclosure", "article_type": "DISCLOSURE",
            "campaign_ids": [(6, 0, campaign.ids)], "status_ids": [(6, 0, workflow.status_ids[:1].ids)],
            "body": "Synthetic disclosure content.",
        })
        self.assertIn(campaign, article.campaign_ids)
        lead = self.env["crm.lead"].create({
            "name": "Synthetic Policy Lead", "business_unit_id": campaign.business_unit_id.id,
            "call_center_campaign_id": campaign.id, "codestra_workflow_id": workflow.id,
            "user_id": self.env.user.id,
        })
        denied = self.env["codestra.contact.policy.service"].evaluate(lead, "SMS")
        self.assertFalse(denied["contact_allowed"])
        self.assertEqual(denied["reason"], "SMS_CONSENT_REQUIRED")

    def test_campaign_builder_lifecycle_and_distribution_are_audited(self):
        workflow, campaign = self._bound_workflow("student_repayment", "BUILDER")
        workflow.write({"active": False, "lifecycle_state": "DRAFT"})
        workflow.action_validate_configuration()
        self.assertEqual(workflow.lifecycle_state, "VALIDATED")
        workflow.action_stage(); self.assertEqual(workflow.lifecycle_state, "STAGING")
        workflow.action_activate(); self.assertTrue(workflow.active)
        agent = self.env["codestra.agent.profile"].create({
            "name":"Synthetic Human Agent","agent_type":"HUMAN","user_id":self.env.user.id,
            "campaign_ids":[(6,0,[campaign.id])],"daily_capacity":10,
        })
        lead = self.env["crm.lead"].create({
            "name":"Synthetic Distributed Lead","business_unit_id":campaign.business_unit_id.id,
            "is_codestra_call_center_lead":True,"call_center_campaign_id":campaign.id,
            "codestra_workflow_id":workflow.id,
        })
        rule = self.env["codestra.lead.distribution.rule"].create({
            "campaign_id":campaign.id,"strategy":"HUMAN_ONLY","eligible_agent_ids":[(6,0,[agent.id])],
        })
        self.assertEqual(rule.assign(lead),agent)
        self.assertEqual(lead.assigned_agent_profile_id,agent)
        self.assertTrue(self.env["codestra.activity.timeline"].search_count([
            ("lead_id","=",lead.id),("event_type","=","ASSIGNMENT_CHANGE")]))
