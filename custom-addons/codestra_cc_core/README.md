# Codestra Contact Center Core

Canonical, staging-safe campaign-workspace domain for the corporate contact
center.

The audited legacy implementation remains in `call_center_core`,
`call_center_campaign`, `codestra_interaction_workflow`, and the hardened
interaction records in `codestra_vicidial_crm`. The canonical `cc.business.unit`
and `cc.campaign` records use delegated one-to-one links to those existing owners;
they do not copy the legacy business fields or create parallel campaign truth.
The adoption loader is idempotent and gives existing records stable canonical
scope identities.

This module owns:

- `cc.business.unit` canonical wrappers;
- `cc.campaign` Campaign Workspaces and their staging-only lifecycle;
- `cc.campaign.channel` internal channel definitions with optional legacy mapping
  adoption;
- `cc.campaign.policy` versioned policy envelopes; and
- `cc.campaign.scoped.mixin` for immutable campaign ownership in downstream
  modules.

Human membership, global record rules, partial unique membership indexes, and
negative authorization tests belong to `codestra_cc_security` and the next
stacked branches. Until those modules land, only existing managers and system
administrators receive ACL access to these canonical models.

Live writes, external delivery, callbacks, and dialing remain disabled by default.
