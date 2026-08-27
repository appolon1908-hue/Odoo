from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestCodestraAiAssistantDraft(TransactionCase):
    def test_generation_and_independent_review(self):
        draft = self.env["codestra.ai.assistant.draft"].create(
            {
                "request_type": "interaction_summary",
                "idempotency_key": "assistant-fixture-1",
                "input_reference": "interaction:fixture-1",
                "prompt_hash": "a" * 64,
            }
        )
        draft.record_generation(
            provider="certification-provider",
            model_name="certification-model",
            response_hash="b" * 64,
            output_text="Customer requested a reviewed callback.",
        )
        self.assertEqual(draft.state, "generated")
        with self.assertRaises(ValidationError):
            draft.action_approve()

        reviewer_group = self.env.ref("codestra_ai_agent_assistant.group_codestra_ai_reviewer")
        reviewer = self.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": "AI Reviewer",
                "login": "ai-reviewer-fixture@example.test",
                "email": "ai-reviewer-fixture@example.test",
                "group_ids": [Command.set([reviewer_group.id])],
            }
        )
        draft.with_user(reviewer).action_approve()
        self.assertEqual(draft.state, "approved")
        self.assertEqual(draft.reviewed_by_id, reviewer)
        for prohibited in ("send_message", "set_consent", "set_dnc", "approve_refund"):
            self.assertNotIn(prohibited, draft._fields)
