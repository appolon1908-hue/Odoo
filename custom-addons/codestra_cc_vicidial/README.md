# Codestra Contact Center VICIdial

Mission facade over the existing hardened VICIdial modules. It preserves the deployed `codestra_vicidial_crm` implementation and prevents a second dialer or a second call-history source from being created in Odoo.

Canonical public paths are terminated and authorized at Kong. Internal Odoo routes remain versioned implementation details. Mutating call-control requests stay disabled unless the existing feature flags, tenant mapping, agent binding, consent policy, Middleware authorization, and provider gates all permit the action.
