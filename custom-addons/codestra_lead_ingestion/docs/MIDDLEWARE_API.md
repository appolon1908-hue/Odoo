# Middleware contract

Middleware claims `codestra.lead.import.outbox` rows with state `pending` or
`retry` under the Middleware Service identity. Each payload contains only lead
UUID, batch UUID, campaign/list mapping, normalized dial destination, limited
identity/script data, eligibility, correlation ID and idempotency key.

Acknowledgements call `codestra.lead.import.line.apply_middleware_ack` with:

```json
{"status":"accepted|rejected|sent|reconciled","idempotency_key":"...",
 "correlation_id":"...","vicidial_lead_id":"...","vicidial_list_id":"..."}
```

The integration boundary must authenticate the service identity, validate
schema/company/batch, reject replay, and audit each request. Repeated
idempotency keys return success without a duplicate state change.
