# Codestra Klyrow SMTP Routing

Odoo 19 routing controls for the fourteen verified Klyrow-managed production domains.

The addon adds two governed outgoing-server profiles, binds every managed brand to an exact FROM filter, records inbound-route drift, standardizes tracking on `track.klyrow.com`, and archives the stale `booked4seasons.com` Klyrow records. Legacy administration aliases are archived so only support and billing remain active Odoo destinations.

The implementation is deliberately fail closed:

- no password is committed;
- both outgoing-server records install archived;
- the shared credential starts in `hold`;
- the Beyvra credential starts in `missing`;
- managed domains cannot fall back to another SMTP server;
- pre-established SMTP sessions cannot bypass domain routing;
- live delivery requires one Odoo parameter and three environment kill switches;
- connection testing cannot convert a held credential into a delivery-ready route.

Normalized inbound replies continue through the signed Codestra middleware adapter. The source policy records that only `codestra.co` and `klyrow.com` are currently aligned; the other twelve domains remain drifted until their Gmail forwards are replaced.

See `integration/KLYROW_SMTP_RUNBOOK.md` for the secret-import and activation procedure.
