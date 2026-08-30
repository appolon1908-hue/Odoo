# Repository Profile — `Odoo`

## Identity

- **Repository:** `appolon1908-hue/Odoo`
- **Category:** Business system — CRM and ERP
- **Visibility:** `private`
- **Default branch:** `main`
- **Authority:** Primary Odoo CRM, business-state, and custom-module authority
- **Status:** Active private repository for Odoo configuration, campaign workflows, and Codestra-specific modules.

## Purpose

Provides the system of record for CRM, contacts, opportunities, campaigns, operational business workflows, reporting, and approved product/contact-center integrations.

## Owns

- Odoo modules, models, views, security rules, migrations, and business workflows
- CRM/customer/opportunity/campaign state
- Campaign-isolated agent, supervisor, inbox, script, disposition, callback, recording, and reporting workflows where implemented

## Does not own

- Cross-system privileged API writes that bypass Middleware
- Provider runtimes such as Postal, Jasmin, or VICIdial
- n8n as a correctness or system-of-record database

## Key integrations

- Middleware
- n8n
- `Vicidialer-Codestra`
- Klyrow, Telnexa, provisioning, and product applications through governed contracts

## Current priorities

1. Enforce permanent one-campaign-per-agent isolation
2. Complete VICIdial/Odoo mapping modules and campaign-specific workflows
3. Route every external write through Middleware
4. Add module tests, migrations, backup/restore, upgrade, and rollback evidence

## Governance and safety

- Promotion model: `feature/docs/fix/security/upgrade -> development -> test -> staging -> production -> main`.
- Use pull requests and exact-head/merge-result validation; source merge never authorizes live CRM or campaign changes.
- Never commit passwords, access tokens, database dumps, attachments, recordings, or customer PII.
- Production modules and migrations must be immutable, reviewed, and reversible.
- This document does not change live Odoo data, create campaigns/users, send communications, or deploy modules.

## Account-wide catalog

See `appolon1908-hue/documentaions/REPOSITORY_CATALOG.md`.
