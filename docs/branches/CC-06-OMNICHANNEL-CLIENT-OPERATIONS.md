# CC-06 — Omnichannel, Mailbox, Automation, and Client Operations

This branch adds mission facades for correlated email/SMS timelines, verified campaign-domain mailbox lifecycle, and allowlisted n8n automation. It also implements versioned client contracts and SLA definitions against canonical Odoo customer and campaign records.

## Commercial and operational controls

- authorized contacts must belong to the client company;
- approved terms are immutable and require a linked new version;
- approval requires an authorized contact and active SLA;
- activation requires a governed campaign;
- contract activation does not activate email, SMS, callbacks, n8n, or dialing;
- all provider effects remain disabled and Middleware-governed.
