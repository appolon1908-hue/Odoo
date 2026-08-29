# Callback middleware synchronization

`codestra.callback` remains the Odoo CRM projection while middleware owns the
canonical scheduling state. Scheduling a callback creates an append-only
`codestra.callback.sync.job` in the same PostgreSQL transaction. Cron workers
obtain a short-lived Keycloak service token, send the idempotent command through
Kong, and persist the middleware UUID/version acknowledgement.

Production configuration is environment-only:

```text
CODESTRA_CALLBACK_SYNC_ENABLED=true
CODESTRA_CALLBACK_API_BASE_URL=https://api.codestra.agency/api/v1
CODESTRA_CALLBACK_TOKEN_URL=https://auth.codestra.agency/realms/codestra/protocol/openid-connect/token
CODESTRA_CALLBACK_CLIENT_ID=codestra-odoo-callback-service
CODESTRA_CALLBACK_CLIENT_SECRET_FILE=/run/secrets/callback_client_secret
CODESTRA_CALLBACK_CA_FILE=/run/secrets/callback_ca
CODESTRA_CALLBACK_ALLOWED_TENANT=COD
CODESTRA_CALLBACK_ALLOWED_CAMPAIGN=TEST_SYN
```

The client secret and CA must be read-only mounts. Jobs fail closed outside the
`COD/TEST_SYN` allowlist. HTTP authentication, authorization, validation, and
version conflicts become `reconciliation_required`; retryable transport/server
failures use bounded exponential backoff.

The reconciliation cron reads canonical middleware state and applies changes
with `skip_callback_sync`, preventing event loops while retaining Odoo history.
