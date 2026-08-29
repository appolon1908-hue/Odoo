# CC-05 — Workforce, Identity, Onboarding, and Training

This branch adds typed, company-scoped workforce shifts with verified attendance overlap and adherence calculations; a mission facade over the durable identity-provisioning engine; readiness-gated agent onboarding; and versioned training certifications.

## Guardrails

- published shifts do not modify VICIdial or payroll;
- open attendance records do not finalize adherence;
- onboarding approval requires every readiness gate;
- external provisioning starts only through an approved linked provisioning request;
- activation requires the provisioning request to be active and reconciled;
- training certification does not grant access by itself;
- no network identity or mailbox operation runs during installation.
