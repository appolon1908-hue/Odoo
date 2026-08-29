# CC-07 — Revenue Assurance, Analytics, Data Quality, and Client Portal

This branch implements versioned rate plans, immutable usage snapshots, provider cost, revenue, margin, and invoice linkage; a bounded data-quality review queue; the mission analytics facade; and a partner-scoped client portal.

## Security and evidence

- usage requires an active plan and unique source/idempotency identities;
- historical rates and costs are snapshotted;
- approved usage is immutable and may be reversed only through stateful review;
- data-quality issues never auto-merge or delete source records;
- portal controllers do not use `sudo()`;
- portal ACLs and record rules restrict contracts, SLAs, and approved usage to the user's commercial partner;
- recordings, internal QA, raw events, and credentials remain unavailable in the portal.
