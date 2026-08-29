# Security

- No passwords, tokens, cookies, Authorization values, keys, or resolved
  credentials may be stored.
- Payloads and audit metadata are recursively redacted and size bounded.
- Audit is append-only and hash chained with a deterministic non-secret hash.
- Idempotency records are service-managed and immutable.
- No live delivery, external calls, public controllers, or broad `sudo()` are
  implemented.
- Least-privilege ACLs reuse `codestra_base` groups.
- Every endpoint defaults disabled and test-only.
- Every Hub cron is inactive and reporting-only.
- External delivery remains middleware authority.
