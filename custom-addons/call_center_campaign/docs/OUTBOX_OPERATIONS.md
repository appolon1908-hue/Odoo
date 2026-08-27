# Campaign Design Outbox Operations

The outbox is source-only and disabled by default. Installing or upgrading this
module does not authorize delivery, provisioning, dialing, or external
communication.

## Delivery configuration

The inactive cron may only be enabled in an approved staging deployment after
the source, backup, and restore gates pass. The worker requires:

- `CODESTRA_MIDDLEWARE_CAMPAIGN_DESIGN_URL`, set to the exact HTTPS
  `/api/v1/campaign-designs/preview` endpoint;
- `CODESTRA_MIDDLEWARE_TOKEN_FILE`, set to an absolute protected credential
  file outside Git.

The worker claims rows in a short transaction, commits the claim, performs the
network request, and finalizes the outcome in another short transaction.
Processing claims older than five minutes are recoverable. Middleware receives
the immutable event UUID as its idempotency key.

## Uninstall policy

Uninstall is not supported after any outbox event has been accepted. Removing
the module would remove immutable integration and audit history. Rollback must
restore the exact pre-upgrade database and filestore from the independently
verified encrypted backup; it must not uninstall the module in place.

Before a future deployment, validate clean install and upgrade in an isolated
copy of the exact release. Production databases and filestores must remain
untouched.
