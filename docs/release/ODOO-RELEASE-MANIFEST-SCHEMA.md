# Odoo release manifest schema

Every staging or production candidate must be paired with an immutable release manifest. The manifest is evidence, not a credential store, and must contain no customer data or secrets.

Required fields:

```text
SCHEMA_VERSION=1
SOURCE_SHA=<full protected-main commit SHA>
ODOO_IMAGE_DIGEST=<registry/name@sha256:digest>
POSTGRES_VERSION=<major.minor or immutable image identity>
MODULE_INVENTORY_HASH=<sha256 of sorted module/version/tree inventory>
MIGRATION_SET=<ordered migration identifiers or NONE>
MIGRATION_HASH=<sha256 of ordered migration content>
DATABASE_BACKUP_ID=<immutable backup-system identifier>
FILESTORE_BACKUP_ID=<matching immutable backup-system identifier>
BACKUP_CAPTURED_AT=<UTC RFC3339 timestamp>
ROLLBACK_REFERENCE=<approved recovery-run identifier>
CI_EVIDENCE_SHA256=<sha256>
SBOM_SHA256=<sha256>
SECRET_SCAN=PASS
SECURITY_SCAN=PASS
FRESH_INSTALL=PASS
UPGRADE_TEST=PASS
STAGING_CERTIFICATION=PENDING|PASS
```

Rules:

- `SOURCE_SHA` must belong to protected `main`.
- The Odoo image must be digest-pinned.
- Database and filestore identifiers must describe the same recovery point.
- A schema-changing release must identify an ordered migration set and matching rollback reference.
- Production requires staging certification for the identical SHA, image digest, module inventory hash and migration hash.
- Git rollback never substitutes for database and filestore recovery.
- Release records are append-only and retained with deployment and restore-test evidence.
