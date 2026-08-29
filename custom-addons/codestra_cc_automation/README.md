# Codestra Contact Center Automation

Mission facade for deterministic mappings from approved business events and dispositions to an allowlisted n8n workflow catalog. Odoo publishes a versioned event through its transactional outbox; Middleware validates authorization and invokes an approved workflow; results return through the durable inbox.

The browser can never supply an executable workflow identifier. n8n is not a system of record and receives no Odoo database credential.
