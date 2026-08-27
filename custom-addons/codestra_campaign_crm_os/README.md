# Codestra Campaign CRM Operating System

This Odoo 19 add-on provides campaign-specific workflows, statuses, automation mappings, agent profiles, activity timelines and corporate CRM controls.

## Model ownership

`codestra_data_quality` is the authoritative owner of `codestra.data.quality.issue`. This add-on extends that model with campaign and lead context; it does not declare a second concrete table owner.

## Installation and upgrade

The reviewed `post_init_hook` provisions deterministic inactive workflow metadata. The `19.0.1.3.0` upgrade migration normalizes legacy data-quality values and preserves historical records. Both are bound to the exact reviewed module tree in the canonical add-on registry.

## Safety

Business workflows, n8n mappings and campaign automations remain inactive by default. The browser cannot select arbitrary workflows, and customer communication remains subject to campaign, consent and provider gates.

## Verification

Run the module tests and `scripts/run_ci.sh`. Exact-tree drift, duplicate concrete model ownership and undeclared review exceptions fail closed.
