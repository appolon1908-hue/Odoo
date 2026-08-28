# Codestra VICIdial CRM

Odoo 18 core call-center addon. Version 18.0.2.0.0 depends on `codestra_base` while preserving the installed technical name, transactional tables, model names, XML IDs, menus, security groups, and record relationships.

The addon owns CRM/user call-center extensions, VICIdial agents, campaigns, phones, calls/events, dispositions, transfers, recordings, queue snapshots, the single callback model, and the installed compatibility sync-event model. Generic integration tables remain compatibility-owned here until a migration-safe Integration Hub extension exists.

All live writes, synchronization, n8n delivery, external AI delivery, call control, and recording access are fail-closed through `codestra_base`. This addon performs no VICIdial/Asterisk request and stores no plaintext credential.

Legacy group XML IDs remain authoritative for current memberships and imply their matching `codestra_base` groups. Future transfer-request, compliance, AI, QA, automation, and notification models are deliberately excluded from active core loading and assigned to later suite addons.
