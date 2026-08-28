# Codestra Contact Center Security

This module is the fail-closed authorization layer for canonical campaign
workspaces. It adds stable role groups, campaign memberships, database-backed
exact-one operational assignments, global campaign record rules, and governed
break-glass requests.

The module performs no external provisioning and enables no live capability.
An operational membership can become active only after approval, a source
ticket, and recorded reconciliation evidence. The identity branch owns OIDC,
session pinning, deprovisioning, and external desired-state synchronization.

## Invariants

- an agent or senior agent has at most one active campaign;
- a supervisor has at most one active campaign;
- a campaign has at most one active primary supervisor;
- active operational roles cannot overlap for the same user;
- campaign ownership cannot be changed in place;
- canonical campaign records are hidden when no active assignment exists;
- technical administrators receive no campaign data without an active,
  approved, time-bounded break-glass grant;
- neither memberships nor break-glass grants can be deleted.

All behavior remains **STAGING-ONLY**. Production activation remains rejected
by `codestra_cc_core`.
