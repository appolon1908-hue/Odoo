# Codestra Contact Center Omnichannel

Mission facade for threading authorized email and SMS projections into the same customer interaction timeline. Provider acceptance, delivery, bounce, failure, and inbound-result events are correlated and deduplicated through the integration hub.

Odoo never writes directly to Postal/Klyrow, Jasmin/Telnexa, or provider databases. Every external delivery requires Middleware authorization plus the independently opened provider and compliance gate.
