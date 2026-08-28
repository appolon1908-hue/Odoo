# Codestra Contact Center Mailbox

Mission facade for verified campaign domains, normalized local parts, reservation, duplicate detection, inbound/outbound verification, provider projection, suspension, and termination.

The canonical campaign-owned mail contract is implemented by
`codestra_cc_mail`. This facade retains the earlier mailbox-provisioning
dependencies while the new module owns aliases, sender identity, distribution,
quarantine, chatter, activity, follower, and attachment scope.

The provider identity engine already enforces unique mailbox addresses and protected credential references. Duplicate first names fail closed for manager resolution; an existing mailbox is never silently replaced. Installation sends no email and creates no provider mailbox.
