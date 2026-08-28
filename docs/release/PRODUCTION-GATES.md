# Production promotion gates

Production remains closed until all of the following are evidenced against the exact protected merged artifact:

```text
BACKUP_STATUS=PASS
RESTORE_REHEARSAL_GATE=PASS
SIGNED_IMMUTABLE_RELEASE=PASS
SBOM_STATUS=PASS
PROVENANCE_STATUS=PASS
INDEPENDENT_APPROVAL=PASS
STAGING_CERTIFICATION=PASS
ROLLBACK_REHEARSAL=PASS
PENDING_UNAPPROVED_OUTBOX=0
```

Activation must proceed read-only first, then through a bounded Odoo-write and final-call reconciliation canary. Email, SMS, callbacks, n8n, live VICIdial controls, and PSTN dialing are separate changes and remain disabled until their own provider, consent, geographic, sender, caller-ID, maintenance-window, canary, and reconciliation gates pass.
