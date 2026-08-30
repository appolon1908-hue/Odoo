# Codestra Marketing CRM

Extends `crm.lead` with tenant-scoped marketing attribution and conversion-feedback metadata.

## Authority boundary

- Odoo remains the CRM/business system of record.
- Advertising-provider calls are forbidden from this addon.
- Cross-system effects must pass through Codestra Middleware.
- The addon does not create a new business model or grant new access rights.
- Existing `crm.lead` ACLs and record rules remain authoritative.

## Safety

Installation does not enable advertising, external messaging, social publishing, or provider writes.
