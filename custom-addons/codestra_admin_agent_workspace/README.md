# Codestra Agent Workspace and Admin Console

Native Odoo backend screens that mirror the `codestra-platform` React
frontend's Agent Workspace and Admin Console, composed on top of the
existing three-scope authorization hierarchy rather than a new one:
`codestra.platform.user.platform_role` (global), `codestra.tenant.membership`
(per tenant), and `cc.campaign.membership` (per campaign).

## Agent Workspace

Reachable by any user holding an active `cc.campaign.membership`. Presents
the same three-panel information architecture as the React reference:
Phone (the logged-in agent's mapped `codestra.vicidial.call` state and
controls), Customer/CRM (the linked lead/customer's details and activity),
and Script & Disposition (a wizard writing back to the call's disposition).
No telephony logic is reimplemented here - the phone panel reads and calls
into `codestra_vicidial_crm`'s existing call-control model only.

## Admin Console

A KPI dashboard (`codestra.tenant.kpi`) scoped by role: `platform_admin` sees
every tenant, `platform_operator` gets the same data read-only, and
`tenant_admin` sees only the tenant(s) `_tenant_admin_tenant_ids()` already
grants them - the same scoping pattern `codestra.platform.user` uses
elsewhere, reused rather than reinvented here.

## Governance note

This addon is intentionally new and does not modify any file inside a
canonical-pinned or strict-mission-override addon listed in
`config/canonical-addon-baseline.json`; it only depends on them.
