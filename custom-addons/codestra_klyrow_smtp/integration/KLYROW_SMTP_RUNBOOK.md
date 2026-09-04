# Klyrow SMTP and inbound-routing runbook

## Source policy

This addon prepares Odoo 19 for the fourteen verified Klyrow-managed production domains while remaining fail closed.

- `Klyrow Production` covers the exact thirteen-domain shared credential.
- `Beyvra Production` covers only `beyvra.com`.
- Both records use `mail.klyrow.com:25`, validated STARTTLS, username/password authentication, and `track.klyrow.com`.
- Both records are installed archived.
- No SMTP password is stored in Git.
- `booked4seasons.com` is archived and excluded because it remains Mailgun-managed.

## Secret import

Mount `/etc/klyrow/odoo-postal.env` read-only into the Odoo runtime and execute:

```bash
odoo shell -d "$ODOO_DATABASE" --no-http \
  < /mnt/extra-addons/codestra_klyrow_smtp/scripts/provision_klyrow_smtp.py
```

The protected file must:

- be a regular file, not a symlink;
- be owned and permissioned so no group or world bit is set;
- contain `KLYROW_ODOO_SMTP_PASSWORD=<value>`;
- optionally contain `KLYROW_BEYVRA_SMTP_PASSWORD=<value>` only after the dedicated Postal credential exists.

The helper never prints either value. It loads passwords, leaves both servers archived, leaves the shared credential state held, leaves the Beyvra state missing unless explicitly changed by an operator, and sets `codestra.mail.live_delivery_enabled=false`.

## Activation gates

A governed server is ready only when all of the following are true:

1. Its Odoo record is active.
2. Its password has been loaded.
3. Its Postal credential state is `active`.
4. `codestra.mail.live_delivery_enabled=true`.
5. `ENABLE_EXTERNAL_DELIVERY=true`.
6. `EMAIL_DELIVERY=true`.
7. `LIVE_EMAIL_DELIVERY=true`.

A successful Odoo connection test only proves the SMTP handshake and authentication path. It does not override these gates.

## Remaining provider work

- Release the `klyrow-production` Postal credential from hold.
- Create and verify the dedicated `beyvra-production` credential.
- Replace Gmail forwarding for the twelve drifted domains with the signed Klyrow → Middleware → Odoo adapter.
- Preserve only `support@<domain>` and `billing@<domain>` as Odoo destinations; legacy `admin@<domain>` aliases are archived and `appolon@<domain>` remains outside the Odoo shared inbox.
- Keep all tracking links on `https://track.klyrow.com/t/...`.
- Do not enable custom tracking hosts until each hostname has a valid certificate and an edge virtual host restricted to `/t/*`; the root application must never be served there.
