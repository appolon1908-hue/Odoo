# Codestra Lead Ingestion

Governed CSV/XLSX ingestion for the existing Codestra CRM and call-center
modules. Odoo owns batches, leads, compliance decisions and audit. Middleware
owns delivery/retry/reconciliation. VICIdial owns dialing state. n8n is limited
to authenticated notifications and follow-up orchestration.

Dependencies: Odoo `base`, `mail`, `contacts`, `crm`,
`call_center_campaign`, `call_center_compliance`,
`call_center_lead_validation`, and `codestra_integration_hub`; Python
`openpyxl` and `phonenumbers`. `python-magic` is optional for a future
libmagic-backed MIME adapter.

All delivery flags and scheduled actions default inactive. The addon provides
no direct VICIdial SQL or Asterisk path and stores only an opaque middleware
authentication reference.

See `docs/INSTALLATION.md`, `docs/CONFIGURATION.md`, and
`docs/ACTIVATION_RUNBOOK.md`.
