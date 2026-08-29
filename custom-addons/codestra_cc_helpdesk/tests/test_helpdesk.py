from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestCampaignHelpdesk(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["cc.business.unit"]._adopt_legacy_records()
        cls.Campaign = cls.env["cc.campaign"].with_context(active_test=False)
        cls.Profile = cls.env["cc.customer.profile"]
        cls.Queue = cls.env["cc.helpdesk.queue"]
        cls.Policy = cls.env["cc.helpdesk.sla.policy"]
        cls.Ticket = cls.env["cc.helpdesk.ticket"]
        cls.campaign_a = cls.Campaign.search([("code", "=", "COD-WEB-OUT")], limit=1)
        cls.campaign_b = cls.Campaign.search(
            [("id", "!=", cls.campaign_a.id)], limit=1
        )
        cls.requester = cls._create_user(
            "Helpdesk Requester",
            "cc-helpdesk-requester@example.invalid",
            ["codestra_cc_security.group_cc_global_administrator"],
        )
        cls.approver = cls._create_user(
            "Helpdesk Approver",
            "cc-helpdesk-approver@example.invalid",
            ["codestra_cc_security.group_cc_global_administrator"],
        )
        cls.service = cls._create_user(
            "Helpdesk Identity Service",
            "cc-helpdesk-service@example.invalid",
            [
                "base.group_user",
                "codestra_identity_provisioning.group_provisioning_service",
                "codestra_cc_crm.group_cc_crm_service",
            ],
        )
        cls.agent_a = cls._create_user(
            "Helpdesk Agent A",
            "cc-helpdesk-agent-a@example.invalid",
            ["codestra_cc_security.group_cc_campaign_agent"],
        )
        cls.agent_b = cls._create_user(
            "Helpdesk Agent B",
            "cc-helpdesk-agent-b@example.invalid",
            ["codestra_cc_security.group_cc_campaign_agent"],
        )
        cls._activate_membership(cls.agent_a, cls.campaign_a, "HELPDESK-MEMBER-A")
        cls._activate_membership(cls.agent_b, cls.campaign_b, "HELPDESK-MEMBER-B")
        cls.profile_a = cls._create_profile(cls.campaign_a, "a")
        cls.profile_b = cls._create_profile(cls.campaign_b, "b")
        cls.profile_a.with_user(cls.requester).write(
            {"assigned_user_id": cls.agent_a.id}
        )
        cls.profile_b.with_user(cls.requester).write(
            {"assigned_user_id": cls.agent_b.id}
        )
        cls.queue_a, cls.policy_a = cls._create_queue_and_policy(cls.campaign_a, "a")
        cls.queue_b, cls.policy_b = cls._create_queue_and_policy(cls.campaign_b, "b")
        cls.ticket_a = cls._create_ticket(
            cls.campaign_a, cls.queue_a, cls.profile_a, cls.agent_a, "A"
        )
        cls.ticket_b = cls._create_ticket(
            cls.campaign_b, cls.queue_b, cls.profile_b, cls.agent_b, "B"
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
    def _activate_membership(cls, user, campaign, ticket):
        employee = cls.env["hr.employee"].create(
            {"name": user.name, "user_id": user.id, "company_id": cls.env.company.id}
        )
        membership = cls.env["cc.campaign.membership"].with_user(
            cls.requester
        ).create(
            {
                "user_id": user.id,
                "employee_id": employee.id,
                "campaign_id": campaign.id,
                "role": "agent",
                "requested_by_id": cls.requester.id,
                "source_ticket": ticket,
                "starts_at": fields.Datetime.now(),
            }
        )
        membership.with_user(cls.requester).action_submit_identity()
        operation = membership.with_user(cls.approver).action_approve_identity()
        operation.with_user(cls.service).action_record_readback(
            {
                target: {"status": "matched", "evidence_hash": "a" * 64}
                for target in operation.required_targets
            },
            f"staging://helpdesk/{ticket.lower()}",
        )
        membership.with_user(cls.approver).action_activate()
        return membership

    @classmethod
    def _create_profile(cls, campaign, suffix):
        partner = cls.env["res.partner"].create(
            {
                "name": f"Synthetic Helpdesk Customer {suffix.upper()}",
                "email": f"helpdesk-{suffix}@example.invalid",
                "phone": "+1 555 000 3001" if suffix == "a" else "+1 555 000 3002",
            }
        )
        return cls.Profile.with_user(cls.requester).create_from_partner(
            partner, campaign, f"helpdesk-profile-{suffix}"
        )

    @classmethod
    def _create_queue_and_policy(cls, campaign, suffix):
        queue = cls.Queue.with_user(cls.requester).create(
            {
                "name": f"{campaign.code} Support",
                "campaign_id": campaign.id,
                "queue_key": f"support-{suffix}",
            }
        )
        policy = cls.Policy.with_user(cls.requester).create(
            {
                "name": f"{campaign.code} Normal SLA",
                "campaign_id": campaign.id,
                "queue_id": queue.id,
                "priority": "1",
                "version": 1,
                "first_response_minutes": 30,
                "resolution_minutes": 240,
                "requested_by_id": cls.requester.id,
                "source_ticket": f"HELPDESK-SLA-{suffix.upper()}",
            }
        )
        policy.with_user(cls.requester).action_submit()
        policy.with_user(cls.approver).action_approve()
        return queue, policy

    @classmethod
    def _create_ticket(cls, campaign, queue, profile, agent, suffix):
        return cls.Ticket.with_user(cls.requester).create(
            {
                "campaign_id": campaign.id,
                "queue_id": queue.id,
                "customer_profile_id": profile.id,
                "assigned_user_id": agent.id,
                "subject": f"Synthetic helpdesk ticket {suffix}",
                "description": "Synthetic non-sensitive support request.",
                "priority": "1",
            }
        )

    def test_sla_requires_separate_approval_and_is_immutable(self):
        draft = self.Policy.with_user(self.requester).create(
            {
                "name": "Campaign A SLA Version 2",
                "campaign_id": self.campaign_a.id,
                "queue_id": self.queue_a.id,
                "priority": "2",
                "version": 2,
                "first_response_minutes": 15,
                "resolution_minutes": 120,
                "requested_by_id": self.requester.id,
                "source_ticket": "HELPDESK-SLA-SEPARATION",
            }
        )
        with self.assertRaises(AccessError):
            self.Policy.with_user(self.requester).create(
                {
                    "name": "Forged SLA requester",
                    "campaign_id": self.campaign_a.id,
                    "queue_id": self.queue_a.id,
                    "priority": "3",
                    "version": 99,
                    "requested_by_id": self.approver.id,
                    "source_ticket": "HELPDESK-SLA-FORGED-REQUESTER",
                }
            )
        draft.with_user(self.requester).action_submit()
        with self.assertRaises(AccessError):
            draft.with_user(self.requester).with_context(
                _cc_sla_write_capability=True
            ).write({"state": "approved"})
        with self.assertRaises(AccessError):
            draft.with_user(self.requester).write({"resolution_minutes": 180})
        with self.assertRaises(AccessError):
            draft.with_user(self.requester).action_approve()
        draft.with_user(self.approver).action_approve()
        self.assertEqual(draft.state, "approved")
        with self.assertRaises(AccessError):
            draft.with_user(self.requester).write({"resolution_minutes": 180})
        self.policy_a.with_user(self.approver).action_retire()
        self.assertEqual(self.policy_a.state, "retired")

    def test_ticket_deadlines_and_governed_workflow(self):
        self.assertEqual(
            self.ticket_a.first_response_due_at,
            self.ticket_a.opened_at + timedelta(minutes=30),
        )
        self.assertEqual(
            self.ticket_a.resolution_due_at,
            self.ticket_a.opened_at + timedelta(minutes=240),
        )
        ticket = self.ticket_a.with_user(self.agent_a)
        ticket.action_start()
        ticket.action_record_first_response()
        ticket.write(
            {"resolution": "Synthetic issue resolved.", "resolution_code": "FIXED"}
        )
        ticket.action_resolve()
        ticket.action_close()
        self.assertEqual(self.ticket_a.state, "closed")
        self.assertEqual(self.ticket_a.sla_state, "met")
        self.assertTrue(self.ticket_a.first_response_at)
        self.assertTrue(self.ticket_a.resolved_at)
        self.assertTrue(self.ticket_a.closed_at)
        with self.assertRaises(ValidationError):
            ticket.action_record_first_response()

    def test_ticket_scope_is_derived_and_cross_campaign_create_fails(self):
        created = self.Ticket.with_user(self.agent_a).create(
            {
                "queue_id": self.queue_a.id,
                "customer_profile_id": self.profile_a.id,
                "subject": "Agent-created same-campaign ticket",
                "description": "Safe synthetic request.",
            }
        )
        self.assertEqual(created.campaign_id, self.campaign_a)
        self.assertEqual(created.assigned_user_id, self.agent_a)
        with self.assertRaises(AccessError):
            self.Ticket.with_user(self.agent_a).create(
                {
                    "queue_id": self.queue_b.id,
                    "customer_profile_id": self.profile_b.id,
                    "subject": "Forged cross-campaign ticket",
                }
            )
        with self.assertRaises(AccessError):
            created.with_user(self.agent_a).write({"campaign_id": self.campaign_b.id})
        with self.assertRaises(AccessError):
            created.with_user(self.agent_a).with_context(
                _cc_ticket_workflow_capability=True
            ).write({"state": "closed"})
        with self.assertRaises(AccessError):
            created.with_user(self.agent_a).write({"assigned_user_id": False})
        with self.assertRaises(AccessError):
            created.with_user(self.agent_a).write({"priority": "3"})
        with self.assertRaises(AccessError):
            created.with_user(self.agent_a).write({"csat_score": 5})
        with self.assertRaises(AccessError):
            self.Ticket.with_user(self.agent_a).create(
                {
                    "queue_id": self.queue_a.id,
                    "customer_profile_id": self.profile_a.id,
                    "subject": "Forged closed ticket",
                    "state": "closed",
                }
            )
        with self.assertRaises(UserError):
            created.with_user(self.agent_a).export_data(["ticket_number", "subject"])
        with self.assertRaises(AccessError):
            created.with_user(self.agent_a).copy()

    def test_ticket_query_surfaces_and_direct_id_do_not_leak(self):
        TicketA = self.Ticket.with_user(self.agent_a)
        self.assertIn(self.ticket_a, TicketA.search([]))
        self.assertNotIn(self.ticket_b, TicketA.search([]))
        self.assertFalse(TicketA.search([("id", "=", self.ticket_b.id)]))
        self.assertFalse(
            TicketA.name_search(self.ticket_b.ticket_number, operator="=", limit=10)
        )
        grouped = TicketA._read_group([], ["state"], ["__count"])
        self.assertGreaterEqual(sum(count for _state, count in grouped), 1)
        with self.assertRaises(AccessError):
            self.ticket_b.with_user(self.agent_a).read(["subject"])
        action = self.profile_a.with_user(self.agent_a).action_open_tickets()
        self.assertEqual(action["domain"], [("customer_profile_id", "=", self.profile_a.id)])
        self.assertEqual(
            action["context"]["default_customer_profile_id"], self.profile_a.id
        )

    def test_sla_breach_and_sensitive_note_policy(self):
        old = fields.Datetime.now() - timedelta(hours=6)
        breached = self.Ticket.with_user(self.requester)._create_imported(
            {
                "campaign_id": self.campaign_a.id,
                "queue_id": self.queue_a.id,
                "customer_profile_id": self.profile_a.id,
                "assigned_user_id": self.agent_a.id,
                "subject": "Synthetic overdue ticket",
                "description": "Safe synthetic request.",
                "opened_at": old,
            }
        )
        breached.action_refresh_sla_state()
        self.assertEqual(breached.sla_state, "resolution_breached")
        with self.assertRaises(ValidationError):
            breached.with_user(self.agent_a).write(
                {"description": "Customer pasted a card number into this note."}
            )

    def test_ticket_chatter_and_activity_are_campaign_scoped(self):
        message = self.ticket_a.message_post(body="Campaign A ticket update")
        activity = self.env["mail.activity"].create(
            {
                "res_model_id": self.env["ir.model"]._get_id(self.ticket_a._name),
                "res_id": self.ticket_a.id,
                "activity_type_id": self.env.ref("mail.mail_activity_data_todo").id,
                "summary": "Campaign A ticket follow-up",
                "user_id": self.agent_a.id,
                "date_deadline": fields.Date.today(),
            }
        )
        self.assertEqual(message.cc_campaign_id, self.campaign_a)
        self.assertEqual(activity.cc_campaign_id, self.campaign_a)
        self.assertFalse(
            self.env["mail.message"].with_user(self.agent_b).search(
                [("id", "=", message.id)]
            )
        )
        self.assertFalse(
            self.env["mail.activity"].with_user(self.agent_b).search(
                [("id", "=", activity.id)]
            )
        )
