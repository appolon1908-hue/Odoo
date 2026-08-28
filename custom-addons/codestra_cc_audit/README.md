# Codestra Contact Center Audit

Provides immutable, idempotent, hash-chained audit evidence for campaign scope
decisions, high-risk reads, exports, configuration, integrations, production
gates, and break-glass activity.

Evidence metadata rejects credential and secret-bearing keys. Reasons and source
references are retained only as SHA-256 hashes. Raw export, write, copy, and
deletion are disabled. Each actor owns a separate evidence hash chain so an
agent or technical administrator can append and verify its own minimized events
without receiving read access to another actor's evidence.

The module extends the existing time-bounded, separately approved break-glass
workflow with request, submission, activation, use, revocation, and expiry audit
events. It never enables production access or mutates original call events.
