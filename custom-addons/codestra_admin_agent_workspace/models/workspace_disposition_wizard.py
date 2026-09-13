import uuid

from odoo import api, fields, models


class CodestraWorkspaceDispositionWizard(models.TransientModel):
    """The only writable surface an agent has onto their own call's
    disposition_id/notes. codestra.vicidial.call keeps group_agent
    read-only (a governed addon's own ACL, not touched here); this
    transient model's ACL (this addon's own, new, ungoverned) is what an
    agent actually holds create/write on, and its one button delegates to
    codestra.vicidial.call.action_apply_workspace_disposition(), which
    re-checks call ownership server-side before writing anything.
    """

    _name = "codestra.workspace.disposition.wizard"
    _description = "Agent Workspace: Apply Call Disposition"

    call_id = fields.Many2one("codestra.vicidial.call", required=True)
    disposition_id = fields.Many2one("codestra.vicidial.disposition")
    notes = fields.Text()
    idempotency_key = fields.Char(default=lambda self: str(uuid.uuid4()), required=True, readonly=True, copy=False)

    @api.model
    def default_get(self, field_names):
        values = super().default_get(field_names)
        call_id = self.env.context.get("default_call_id")
        if call_id and "notes" in field_names:
            values["notes"] = self.env["codestra.vicidial.call"].browse(call_id).notes
        return values

    def action_submit(self):
        self.ensure_one()
        self.call_id.action_apply_workspace_disposition(
            disposition_id=self.disposition_id.id or None,
            notes=self.notes,
            idempotency_key=self.idempotency_key,
        )
        return {"type": "ir.actions.act_window_close"}
