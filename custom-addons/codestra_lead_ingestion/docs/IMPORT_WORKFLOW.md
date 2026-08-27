# Import workflow

Create a batch, select company/business unit/campaign/mapping, attach UTF-8 CSV
or XLSX, then Upload. Upload validates size, extension, MIME, checksum, headers,
formulas and row limits. Validate normalizes phones and emails, checks exact
duplicates, suppression/DNC, consent and campaign state. Invalid rows are
quarantined; fuzzy decisions remain review-only.

The controlled state machine is:

`draft → uploaded → validating → needs_review/awaiting_approval → approved →
importing → delivering → reconciling → completed`.

Only approved lines create CRM leads. Lead and outbox creation share the same
transaction/savepoint. Completion requires terminal delivery and zero
authoritative reconciliation difference.
