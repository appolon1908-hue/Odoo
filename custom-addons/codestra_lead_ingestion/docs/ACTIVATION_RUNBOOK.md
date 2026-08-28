# Activation runbook

1. Keep every external flag false; install and run the tagged Odoo tests.
2. Assign scoped groups and create synthetic campaign/mapping/consent data.
3. Verify CSV/XLSX, duplicate, DNC, consent, quarantine, security and rollback.
4. In test only, enable middleware publication and verify duplicate publication
   produces one outbox/idempotency record.
5. Use a disabled/manual-only VICIdial test campaign and synthetic data.
6. Verify delivery, read-back, dispositions, callbacks and reconciliation zero.
7. Rehearse cancellation before delivery and suppression after delivery.
8. Obtain documented administrator and compliance approval for one
   company/campaign/jurisdiction; never enable all campaigns globally.

Stop immediately for DNC/consent bypass, duplicate delivery, unauthorized data,
read-back failure, or any nonzero reconciliation difference.
