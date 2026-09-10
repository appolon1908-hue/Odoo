# Codestra SMS through Middleware

This addon connects the existing CRM SMS composer and native SMS scheduler to
Middleware's canonical communications API, which dispatches through Telnexa.
Odoo never receives Telnexa credentials or calls Jasmin/Telnexa directly.

From a CRM lead, use the normal SMS action. The message must target that lead's
international-format phone number, with current SMS consent and no suppression,
blacklist, DNC, complaint hold or unresolved campaign. The configured company
and business unit must match the lead. Contact hours use the campaign timezone.
These checks run when queued and immediately before submission.

The addon owns all native SMS sending once installed. Unconfigured, out-of-scope
or non-CRM SMS fails closed; it does not fall back to Odoo IAP. This first release
supports one explicitly configured business unit and tenant per Odoo instance.

## Delivery and recovery

The native send transaction creates an immutable outbox record and a campaign
SMS history row; it performs no HTTP delivery. The scheduled worker commits
an indeterminate submission intent before its single message POST. A crash,
timeout, malformed response, or lost acknowledgement then uses only GET
`/v1/communications/messages/by-idempotency`. A 404 leaves the outcome unresolved
and cannot trigger another POST. Native Resend reuses the existing job.

Middleware acceptance maps to Processing, dispatch to Sent, and confirmed
delivery to Delivered. Final delivery states cannot regress. Notifications and
campaign correspondence are updated together; messages are retained instead of
being removed by native successful-send cleanup. Administrators can inspect
Settings → SMS Delivery. A queued SMS can be cancelled before submission;
already submitted messages require Middleware-side reconciliation.

## Configuration and release

Use `config/odoo-sms-middleware.env.example`. Credentials and private CA remain
mounted secret files. HTTPS certificate and hostname verification are mandatory;
redirects and ambient proxies are disabled. Only fixed error codes are stored.

Provision a Keycloak `odoo-sms` confidential service account with tenant-bound
claims, audience `middleware-api`, lifetime at most 300 seconds, and scopes
`odoo.sms.command.write` and `odoo.sms.status.read`. Its Middleware command
authority is limited to `sms.message.submit.*` on `telnexa-sms`. Sender and billing
account must already be approved for that tenant in Middleware/Telnexa. The
Odoo campaign ID is diagnostic metadata, never a provider campaign identifier.

Deploy the companion Middleware readback API and caller policy before installing
this addon from the reviewed Odoo release. Snapshot the database and filestore
and retain the previous addon release. Configure secrets, route and trust, then
validate in an isolated Odoo/PostgreSQL environment with a fake SMS provider.
Activate `CODESTRA_SMS_ENABLED` and `ALLOW_LIVE_SMS` only for the configured scope
after the provider release and live-delivery prerequisites are satisfied.

To pause delivery, set `ALLOW_LIVE_SMS=false`; GET reconciliation continues.
Retain this addon and its outbox during rollback so uncertain submissions cannot
fall through to another provider. Do not uninstall it, delete jobs or reset their
state to pending. Reconcile with Middleware/Telnexa before any separately
authorized replacement message.

This source change is not evidence of production activation or carrier delivery.
Inbound SMS/STOP/HELP processing remains with Middleware/Telnexa; this addon
projects outbound results. It does not create a second provider webhook endpoint.
