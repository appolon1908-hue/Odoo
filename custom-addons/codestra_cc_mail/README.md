# Codestra Contact Center Campaign Mail

Canonical, fail-closed mail isolation for Campaign Workspaces.

The module provides campaign-owned routes, sender identities, distribution
groups and membership read-back, immutable inbound event and quarantine
evidence, and campaign-tagged mail messages, followers, activities, and
attachments. Alias resolution is server-side; browser or message-body campaign
values are never authority. Cross-campaign thread tokens are quarantined.

Safe attachments require a bounded type and size plus SHA-256 malware-scan and
content evidence. Rejected content is not stored as an Odoo attachment; only
hashed quarantine metadata is retained. Outbound preparation fixes From,
Reply-To, signature, footer, and tracking domain to the campaign identity.

This is a staging-only implementation. It has no public inbound controller, no
transport worker, no automatic provider alias creation, and no external send.
`inbound_mutation_enabled`, `external_send_enabled`, and distribution delivery
remain false. The supplied controlled matrix contains no approved alias keys,
so production mail reconciliation remains blocked.

New installations also materialize the authority's global defaults
`CC_ENABLE_EMAIL_SEND=false` and
`CC_ENABLE_EMAIL_INBOUND_MUTATION=false`. These flags cannot enable transport:
route, sender, and distribution live switches are separately immutable at false
in this staging branch.
