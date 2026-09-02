# Intake CRM release evidence

This release branch was rebuilt from the current `main` branch after PR #50 diverged from newly merged Marketing CRM/control-plane work.

The branch contains only the reviewed `codestra_intake_leads` module delta. It does not authorize module installation, live Odoo writes, deployment, or production mutation.

Required merge evidence:

- exact-head Odoo source validation
- exact merge-result validation
- immutable Odoo 19 + PostgreSQL runtime tests
- Security gates
- independent approval required by repository policy
