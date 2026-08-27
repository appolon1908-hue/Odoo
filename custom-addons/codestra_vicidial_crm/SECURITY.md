# Security

- Existing Agent, Closer, Supervisor, Manager, and Integration Administrator memberships are preserved.
- Agents are constrained to their own calls by record rule; recording access begins at Supervisor and is read-only.
- Integration and audit models are not available to Agents. Audit and compatibility sync records cannot be unlinked by normal users.
- The event endpoint is independently protected by timestamped HMAC-SHA256 verification and idempotency. Its reviewed `sudo()` is limited to the verified integration ledger path.
- No source contacts VICIdial/Asterisk, executes shell commands, stores plaintext credentials, or enables a live capability.
- Existing core XML IDs and database columns must not be renamed or removed without an explicit tested migration.
