# Platform RBAC implementation

This document is the source-of-truth map for the role architecture implemented
by the Odoo addons. It is intentionally separate from the external SaaS shell:
the SaaS UI may route users to different workspaces, but Odoo remains the
audited system of record for identity, tenant scope, campaign membership, and
provisioning evidence.

## Canonical roles

| Scope | Role | Odoo source of truth | Scope |
| --- | --- | --- | --- |
| Global | Platform Admin | `codestra.platform.user.platform_role=platform_admin` projected to `group_platform_admin` | All tenants and platform administration |
| Global | Platform Operator | `platform_role=platform_operator` projected to `group_platform_operator` | Cross-tenant operational support; read-heavy and status-only on identities |
| Tenant | Tenant Admin | `codestra.tenant.membership.role=tenant_admin` | Only active tenant memberships assigned to the Odoo user |
| Campaign | Supervisor | `cc.campaign.membership.role=supervisor` | One active primary supervised campaign |
| Campaign | Agent | `cc.campaign.membership.role=agent` | Own active campaign and assigned work |

The existing campaign roles `senior_agent`, `qa`, `workforce`,
`compliance`, `configuration_manager`, and `auditor` remain specialized
campaign-scoped roles. They are not aliases for Tenant Admin or Platform Admin.

## Evaluation rule

An effective permission is the intersection of:

```
assigned role
AND resource scope
AND account / membership state
AND product entitlement
AND environment policy
```

No role alone is sufficient to grant a cross-tenant mutation. A suspended or
terminated platform identity, inactive tenant membership, or non-active campaign
membership must remove the corresponding access path.

## Permission boundary

| Area | Platform Admin | Platform Operator | Tenant Admin | Supervisor | Agent |
| --- | --- | --- | --- | --- | --- |
| Tenants | full | read | assigned tenant read | none | none |
| Platform identities | full | read + suspend/reactivate | create/member fields/status in own tenant | none | none |
| Tenant memberships | full | read | create/update member lifecycle in own tenant; cannot promote/reassign | none | none |
| Provisioning | full approval/operations | read/triage | request through governed product flow | none | none |
| Phone/channel status | full | read | assigned identities read | campaign-scoped operational view | own/campaign view |
| Campaign configuration | full | read/triage | no native Odoo configuration in v1 | supervised campaign | none |
| Billing/infrastructure/security | full | no privileged mutation | no | no | no |

Platform Admin receives existing provisioning security/approval and global
contact-center capabilities through its explicit group projection. Platform
Operator does not inherit those mutation groups.

## Identity lifecycle

- Platform Admin can create or delete platform identities and assign global roles.
- Platform Operator can change only identity `status`.
- Tenant Admin can create a member identity only in an assigned tenant. The
  implementation creates a `member` tenant membership automatically; it cannot
  set `platform_role`, link an Odoo login, or assign `tenant_admin`.
- Only Platform Admin can create or promote a Tenant Admin.
- Campaign Supervisor/Agent access still comes from approved active campaign
  membership; it is never inferred from a tenant role.
- Odoo does not make synchronous Keycloak, VICIdial, SIP, email, or SMS calls.
  External effects remain in the governed provisioning/outbox path.

## Login and workspace routing contract

The external SaaS shell should route after identity verification:

| Role | Workspace |
| --- | --- |
| Platform Admin | `/admin` |
| Platform Operator | `/operations` |
| Tenant Admin | `/tenant` |
| Supervisor | `/supervisor` |
| Agent | `/workspace` |

If an identity has multiple active tenant/campaign memberships, show a workspace
selector. Display the selected tenant and environment in the header and show a
persistent “Viewing <tenant>” banner for internal users entering tenant context.

## Role-specific UI contract

Use a shared dark navigation shell with light work surfaces:

- Navigation: `#071426`, sidebar `#0B1D33`, selected `#102744`,
  hover `#183A63`.
- Primary action: `#0F5EEA`; interactive `#3B82F6`; page background
  `#F7F9FC`; card `#FFFFFF`; border `#E5EAF1`.
- Success/warning/error: `#16A34A`, `#F59E0B`, `#DC2626`.
- Use Inter, an 8px spacing grid, 12-column desktop layout, 220–240px
  sidebar, 64px header, and role-specific navigation. Keep infrastructure
  terms (Odoo, SMTP, SIP, Jasmin) out of the neutral login screen.

The Odoo addon supplies the authorization and safe projections. The external
SaaS frontend should consume these role/scope decisions rather than recreate
them independently.

## Verification gates

Before merging a role change:

1. Run Odoo 19/PostgreSQL runtime tests.
2. Verify positive and negative tests for every role boundary.
3. Verify tenant and campaign record-rule read-back with non-superuser accounts.
4. Confirm platform-role group synchronization after Odoo access creation.
5. Confirm provisioning remains outbox-only and no live external side effect is
   introduced.
6. Do not merge while required checks are pending, failing, or absent.
