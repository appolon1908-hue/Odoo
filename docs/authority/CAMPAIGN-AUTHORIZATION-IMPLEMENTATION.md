# Campaign authorization — as implemented

Reference for how campaign access actually works in the code, as distinct from
how it is specified. Read against `origin/main` at `d48fded`.

`odoo_campaign_access_control_matrix.csv` states intent. This file states
behaviour. Where they disagree, see [Drift](#drift-from-the-access-control-matrix)
at the end — the disagreement is real and currently unresolved.

## The principle

Access is not granted by adding a user to a group. It is granted by an
**approved membership record**, and group membership is downstream of that.

`cc.campaign.membership` (`codestra_cc_security/models/campaign_security.py`)
binds `user_id`, `employee_id`, `campaign_id`, `role` and `state`. Three fields
on `res.users` are computed from the active ones:

| Field | Source |
| --- | --- |
| `cc_allowed_campaign_ids` | campaigns of all `state == "active"` memberships |
| `cc_allowed_business_unit_ids` | their business units |
| `cc_supervised_campaign_ids` | campaigns where `role == "supervisor"` and `is_primary_supervisor` |

Every record rule reads these. Suspending a membership empties the computed
scope and access disappears; there is no second place to revoke.

## Roles

Eight roles, each mapped to exactly one group through `ROLE_GROUP_XMLIDS`:

| Role | Implemented group |
| --- | --- |
| `agent` | `codestra_cc_security.group_cc_campaign_agent` |
| `senior_agent` | `codestra_cc_security.group_cc_senior_agent` |
| `supervisor` | `codestra_cc_security.group_cc_campaign_supervisor` |
| `qa` | `codestra_cc_security.group_cc_quality_analyst` |
| `workforce` | `codestra_cc_security.group_cc_workforce_analyst` |
| `compliance` | `codestra_cc_security.group_cc_compliance_officer` |
| `configuration_manager` | `codestra_cc_security.group_cc_campaign_configuration_manager` |
| `auditor` | `codestra_cc_security.group_cc_auditor` |

`agent`, `senior_agent` and `supervisor` form `OPERATIONAL_ROLES` — the roles
that touch live work and are subject to the one-membership rule below.

## How a lead is filtered

Three **global** rules on `crm.lead` apply to every user and are **ANDed**.
Each is one expression that branches on the caller's groups:

```
if global_administrator OR cc_crm_service OR active break-glass
                                  -> [(1, '=', 1)]                    everything
elif integration_service          -> business_unit_id in user's units
elif scoped_user                  -> campaign_id in cc_allowed_campaign_ids
elif manager                      -> business_unit_id in user's units
elif supervisor                   -> call_center_campaign_id.supervisor_ids
else                              -> campaign authorised AND (assigned to me
                                     OR my agent profile)
```

Defined in `codestra_cc_crm/security/crm_security.xml`, which overrides
`call_center_core.rule_lead_business_unit` and
`codestra_campaign_crm_os.rule_crm_lead_campaign_global`, plus its own
`rule_cc_crm_lead_global_scope`.

Two further rules are **group-scoped**, so they are ORed among the groups the
caller holds:

```
agent      -> ['|', ('user_id', '=', user.id), ('user_id', '=', False)]
supervisor -> [('campaign_id', 'in', user.cc_supervised_campaign_ids.ids)]
```

### What each role sees

**Agent.** Leads inside their membership's campaign, and of those, only leads
assigned to them or currently unassigned. The `user_id = False` clause is
deliberate: it is the work queue, and it is how unclaimed leads remain visible
to be picked up. An agent cannot see a colleague's assigned lead.

**Supervisor.** Campaigns where they are the *primary* supervisor, not merely a
member. A supervisor on a campaign without `is_primary_supervisor` gets no
supervisory visibility.

**Global administrator.** Short-circuits at the first branch of every global
rule and sees everything.

## What operational users cannot do

`crm.lead.write()` in `codestra_cc_crm/models/crm_workspace.py` adds two guards
beyond visibility:

* **Campaign ownership is immutable.** `campaign_id`,
  `cc_customer_profile_id` and `cc_source_list_key` cannot be changed by anyone
  without the migration capability, administrator or not. A lead cannot be moved
  between campaigns; it is recreated instead.
* **Agents cannot reassign.** `user_id`, `assigned_agent_profile_id` and the
  supervisor fields are rejected for operational users who are not supervisors.

## Granting a membership

Holding the administrator group is necessary but not sufficient. Activation
(`action_activate`, plus the constraint that backs it) requires all of:

* the caller is `group_cc_global_administrator`;
* **the requester is not the approver** — enforced twice, in the action and
  again in `_check_activation_conflicts`;
* a `source_ticket`;
* `last_sync_status == "matched"` and `read_back_evidence` present, so the
  downstream systems (Keycloak, Vicidial, campaign mail) have confirmed the
  grant actually landed;
* **at most one active operational membership per user**, so an agent cannot
  serve two campaigns;
* **at most one active primary supervisor per campaign**.

Supporting invariants:

* `user_id`, `employee_id`, `campaign_id`, `role` and `requested_by_id` are
  immutable after creation (`IMMUTABLE_MEMBERSHIP_FIELDS`).
* Memberships cannot be deleted — "campaign membership evidence cannot be
  deleted."
* Activation bumps `campaign.scope_version` and clears the registry cache, so
  stale scope cannot survive a grant.

The design intent is that a membership is *evidence*, not configuration: it
cannot be created without a ticket and a second person, cannot be issued without
proof the downstream systems agreed, and cannot be erased afterwards.

## Break-glass

`cc.break.glass.grant` is the emergency route to the `(1, '=', 1)` branch. It
carries its own separate approval and is time-bounded —
`cc_has_active_break_glass` is computed against the current time, so a grant
expires rather than needing to be revoked.

## Drift from the access-control matrix

`odoo_campaign_access_control_matrix.csv` names ten groups in its
`stable_odoo_group` column. **Seven do not exist in the code:**

| Named in the matrix | Present in `codestra_cc_security` |
| --- | --- |
| `group_cc_agent` | no — implemented as `group_cc_campaign_agent` |
| `group_cc_supervisor` | no — implemented as `group_cc_campaign_supervisor` |
| `group_cc_qa_analyst` | no — implemented as `group_cc_quality_analyst` |
| `group_cc_wfm_analyst` | no — implemented as `group_cc_workforce_analyst` |
| `group_cc_campaign_config_manager` | no — implemented as `group_cc_campaign_configuration_manager` |
| `group_cc_global_admin` | no — implemented as `group_cc_global_administrator` |
| `group_cc_technical_admin` | no — implemented as `group_cc_technical_administrator` |
| `group_cc_senior_agent` | yes |
| `group_cc_compliance_officer` | yes |
| `group_cc_auditor` | yes |

All ten rows also carry `status=MISSING`, while the role model is implemented
and enforced by the rules described above.

This matters because `has_group()` on an unknown external ID does not announce
itself. Any policy, rule or integration written against the matrix names would
silently fail to match, and whether that fails open or closed depends entirely
on which branch of which expression it sits in.

**This file does not resolve the drift**, because it cannot be determined from
the code whether the matrix is aspirational — recording names the project
intends to migrate to — or simply stale. Correcting an authority document is an
owner decision. Two directions are available:

1. The code is canonical: update `stable_odoo_group` to the seven implemented
   names and change `status` from `MISSING`.
2. The matrix is canonical: rename the seven groups in `codestra_cc_security`,
   with a migration for existing `res.groups` external IDs and membership data.

Until one is chosen, treat the group names in *this* file as authoritative for
anything being built now, because they are the ones the runtime resolves.
