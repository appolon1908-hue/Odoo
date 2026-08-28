# Rollback — Codestra Contact Center Calls

Rollback is an application and schema rollback on a disposable staging copy,
not deletion of operational evidence.

1. Keep `CC_ENABLE_CALLBACK_PUBLICATION=false` and
   `CC_ENABLE_WARM_TRANSFER=false`; keep external referral delivery disabled.
2. Stop creation of new canonical callbacks, appointments, transfer requests,
   and referrals at the Odoo application boundary.
3. Export counts and hashes for `cc.operation.outbox`, callback history,
   transfer events, referrals, and referral deliveries. Preserve this evidence
   under the applicable retention policy.
4. Take and verify a PostgreSQL backup before changing the installed addon set.
5. Restore the prior tested branch/database pair on a disposable environment.
   Do not drop or truncate canonical call-operation tables in place.
6. Confirm that the legacy click-to-call popup and legacy appointment module
   still load, and that no held event was delivered externally.
7. Reconcile callback, transfer, and referral identifiers before authorizing a
   new migration attempt.

The branch creates no remote VICIdial/Asterisk/n8n state, so there is no remote
mutation to undo. Any environment that shows an externally delivered event is
outside this branch's certified state and requires incident review.
