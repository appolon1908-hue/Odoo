from odoo import SUPERUSER_ID, api

CHANNEL_TYPES = ("email", "sms", "phone", "webrtc")


def migrate(cr, version):
    """Backfill ``codestra.agent.channel`` rows for every existing campaign
    membership from data Odoo already has. Idempotent (skips any
    (employee, channel_type) pair that already has a row) and side-effect
    free: no Keycloak/VICIdial/Asterisk/Middleware call, no email/SMS, no
    credential or secret is read, written, or migrated.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    Channel = env["codestra.agent.channel"]
    Membership = env["cc.campaign.membership"]
    Request = env["codestra.provisioning.request"]
    Assignment = env["codestra.extension.assignment"]

    for membership in Membership.search([("employee_id", "!=", False)]):
        employee = membership.employee_id
        existing_types = set(
            Channel.search([("employee_id", "=", employee.id)]).mapped("channel_type")
        )
        missing_types = [t for t in CHANNEL_TYPES if t not in existing_types]
        if not missing_types:
            continue

        request = Request.search(
            [("employee_id", "=", employee.id)], order="id desc", limit=1
        )
        assignment = Assignment.search(
            [
                ("employee_id", "=", employee.id),
                ("state", "in", ("reserved", "committed")),
            ],
            order="id desc",
            limit=1,
        )
        desired_by_type = {
            "email": bool(request and request.needs_company_email),
            "sms": bool(getattr(membership, "sms_enabled", False)),
            "phone": bool(request and request.needs_sip_endpoint) or bool(assignment),
            "webrtc": bool(getattr(membership, "webrtc_enabled", False)),
        }

        for channel_type in missing_types:
            values = {
                "employee_id": employee.id,
                "membership_id": membership.id,
                "provisioning_request_id": request.id if request else False,
                "channel_type": channel_type,
                "desired_enabled": desired_by_type[channel_type],
            }
            if channel_type == "phone" and assignment:
                values["extension_assignment_id"] = assignment.id
            Channel.create(values)
