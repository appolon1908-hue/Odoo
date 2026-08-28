# Codestra Odoo VICIdial Certification

This add-on provides a deterministic, default-off certification lane for the
Codestra Odoo 19 and VICIdial CRM integration. It exists to exercise governed
CRM mutations with synthetic records while all live delivery and telephony
capabilities remain disabled.

## Safety boundary

- The `TEST_SYN` company, business unit, CRM team, pipeline, campaign, and
  mapping are inactive and are not production eligible.
- The synthetic company is an inactive child of Odoo's active main-company
  root. Odoo 19 Accounting requires an available company hierarchy during
  company creation; this relationship is structural only and does not grant
  a user access to the synthetic tenant.
- Tests require the explicit `_test_syn_certification` context capability.
- The add-on does not place calls, send messages, activate campaigns, invoke
  providers, write VICIdial tables, or change a live runtime during install.
- No credentials, customer data, recordings, or secret provider values belong
  in this module.

## Certification behavior

The test suite covers deterministic creation and update, exact replay,
conflicting replay rejection, event ordering, bounded retry state, callback
rescheduling, permanent DNC suppression, disposition mapping, and the disabled
synthetic company hierarchy. Each disposition has one canonical business code
and one physical VICIdial status code; either input is accepted, while Odoo
stores and reports the canonical business outcome.

Production activation remains outside this add-on and requires the reviewed
Middleware boundary, independent approval, staging certification, backup and
restore evidence, and the channel-specific production gates.
