# Campaign helpdesk migration policy

The tested Community runtime has no Enterprise `helpdesk.ticket` model, so this
branch does not automatically convert external or Enterprise tickets. A future
adapter must map every queue and ticket to exactly one canonical campaign and
customer profile, preserve source identifiers, timestamps, chatter evidence,
and original SLA outcomes, and reject ambiguous ownership.

SLA policies must be recreated as separately approved immutable versions before
ticket import. Migration dry runs, rejected-row evidence, rollback mappings, and
post-import cross-campaign authorization tests are mandatory. No migration may
silently reset deadlines, breach state, or resolution history.
