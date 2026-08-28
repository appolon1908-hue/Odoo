# Codestra Contact Center Calls

This Odoo 19 addon owns the canonical, campaign-scoped call-operation records
introduced by `feat/cc-callback-transfer`:

- `cc.callback.policy`, `cc.callback`, immutable callback history, and reminders;
- `cc.appointment` with a same-campaign appointment callback;
- `cc.transfer.route`, `cc.transfer`, and immutable transfer events;
- `cc.referral.route`, the source-safe `cc.referral`, and destination-only
  `cc.referral.delivery`;
- an immutable desired-state outbox whose rows remain held in staging; and
- canonical appointment-calendar, reminder-center, and callback-scheduler
  pop-outs. The existing VICIdial click-to-call popup remains the call-control
  owner.

## Security contract

Campaign ownership is immutable. Every operational create is derived from the
authenticated active membership, global record rules constrain all query
surfaces, and assignment checks require active same-campaign memberships.
Agents see their own work; primary supervisors see their one campaign. A live
transfer to another campaign is rejected and recorded with a safe explanation.
Cross-campaign service requests use an asynchronous referral: the source record
contains only a non-sensitive status, while the minimum-data destination record
is visible only inside the destination campaign.

Direct creation of transfer, referral, reminder, history, event, and outbox
evidence is protected by unforgeable in-process capabilities. Evidence cannot
be deleted or silently rewritten. Operational exports are disabled.

## Safe defaults

This is a staging-only implementation. These capabilities remain closed:

- `CC_ENABLE_CALLBACK_PUBLICATION=false`
- `CC_ENABLE_WARM_TRANSFER=false`
- external referral delivery is disabled

Scheduling and validation create held desired-state evidence, never network
traffic. The addon adds no public controller, direct database integration,
transport worker, or live telephony writer.

## Validation

`tests/test_call_operations.py` covers campaign derivation, calling-hour and
consent enforcement, held and idempotent outbox evidence, reminders,
appointments, same-campaign transfer success, cross-campaign transfer
rejection, exact-once results, minimum-data referrals, destination isolation,
immutable records, closed flags, and the canonical pop-out asset contract.

Full Odoo 19/PostgreSQL installation results are retained in the branch report
and `reports/odoo-staging-evidence.md` after GitHub runtime validation.
