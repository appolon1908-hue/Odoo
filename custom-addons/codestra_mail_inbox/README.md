# Codestra Shared Mail Inbox

Odoo 19 Community shared work queues for seven brands and two queue types.

The module intentionally exposes no HTTP controller and sends no mail directly.
Normalized inbound events must arrive through authenticated Codestra middleware,
and outbound preparation always returns `external_delivery_enabled=False` with
the sender derived from the queue's exact allowlist entry.

Production installation is outside this staging module's authority.
