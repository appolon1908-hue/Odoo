# Codestra Middleware Bridge

This Odoo 19 add-on emits synthetic, versioned business events to the separate Codestra Middleware authority. It does not implement provider orchestration, expose generic model writes, or connect directly to an external PostgreSQL database.

Outbound destinations must be credential-free HTTPS URLs. Business writes remain inside Odoo's ORM and approved service boundary.
