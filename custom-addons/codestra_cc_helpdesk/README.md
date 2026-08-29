# Codestra Contact Center Helpdesk

Canonical campaign-owned support boundary for the repository's Odoo 19
Community runtime. That runtime has no Enterprise `helpdesk.ticket` model, so
this module implements `cc.helpdesk.queue`, governed immutable-version
`cc.helpdesk.sla.policy`, and `cc.helpdesk.ticket` rather than claiming an
unavailable dependency is installed.

Ticket scope is derived from the authenticated active membership, customer
profile, and queue. Approved same-campaign SLA policy determines immutable first
response and resolution deadlines. State, first-response, resolution, closure,
and SLA evidence change only through governed methods. Chatter, activities,
followers, and attachments inherit the campaign tags and global isolation from
`codestra_cc_mail`.

The module does not expose the generic Contacts, CRM, or Helpdesk applications
to campaign agents. It performs no external notification or email delivery.
An Enterprise Helpdesk adapter remains a separately reviewable future migration
and must preserve these canonical IDs, rules, and SLA evidence.
