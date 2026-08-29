# Security

Record rules isolate company and authorized business unit. Raw and normalized
PII is restricted to ingestion groups. Importers cannot approve or publish;
middleware can read delivery data and write acknowledgements but cannot create
CRM records or alter unrelated models. Audit and outbox records cannot be
deleted through normal ORM operations.

Uploaded binaries never enter outbox payloads. Payloads exclude credentials,
banking data, government identifiers, unrestricted notes and raw files.
Correlation and idempotency keys are mandatory. External callbacks must be
terminated by the authenticated integration boundary and call
`apply_middleware_ack`; no public unauthenticated controller is provided.

Retention must preserve legal holds, audit evidence and dialer history.
