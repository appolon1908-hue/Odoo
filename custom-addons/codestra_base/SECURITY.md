# Security

Codestra Base uses least-privilege groups, stores no credentials, makes all integration flags fail closed, and performs no network or shell operations. It does not define controllers or unauthenticated routes. Odoo audit metadata is limited to business notes/source; native create/write audit fields are not duplicated.
