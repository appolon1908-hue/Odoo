# Odoo automatic campaign provisioning boundary

The repository-level contract is `AUTOMATIC_CAMPAIGN_PROVISIONING.md`.
This add-on implements only the Odoo-owned part of that contract:

- normal user and API campaign creation defaults to automatic design management;
- installation, import and reviewed migrations have an explicit opt-out context;
- every automatically managed campaign receives an immutable integration UUID and
  one idempotent `campaign.design.requested.v1` outbox event per revision;
- versioned design-request and preview records are retained in Odoo;
- complete middleware previews are hash-verified and rejected if they contain
  secret-shaped keys, wrong business-unit list IDs, non-canonical campaign-owned
  identifiers, active VICIdial resources, active n8n workflows or live feature
  flags;
- approval requires a complete current preview, zero validation errors and a
  recorded audit reason;
- approval emits `campaign.approved.v1` without authorizing provisioning,
  activation, dialing, email, SMS or any external live effect; and
- the built-in preview-delivery cron claims only design-request events, leaving
  approval and later lifecycle events for the governed middleware consumer.

Odoo does not allocate VICIdial identifiers, write VICIdial tables, create n8n
workflows or activate production resources. Those responsibilities remain with
Middleware, the restricted VICIdial adapter, VICIdial and n8n as declared in the
root contract.
