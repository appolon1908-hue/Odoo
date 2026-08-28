# Rollback

Disable `ODOO_LEAD_APPLY_ENABLED` and every action switch. Preserve
acknowledgement receipts. Uninstall only this module after confirming there are
no in-flight events; do not delete CRM leads or modify recording, telephony,
Asterisk, or VICIdial modules.

The apply and acknowledgement schemas, HMAC-V2 version/scope/method/path binding, and module
source are one compatibility unit. Do not roll back only one side. Revoke or
rotate the runtime HMAC secret through protected configuration when required;
never place it in source or evidence. Re-run the pinned manifest, install,
upgrade, authentication, replay, ACL, and vulnerability gates before any later
activation.

Do not enable HMAC-V1 as a rollback mechanism. Restore the Middleware signer and
Odoo verifier as one compatibility unit while all mutation switches remain off.
