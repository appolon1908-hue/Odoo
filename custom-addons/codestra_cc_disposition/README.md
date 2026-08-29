# Codestra Contact Center Scripts and Dispositions

This mission module is the canonical adoption and governance layer for campaign
scripts and dispositions. It reuses `call.center.script` and
`codestra.disposition` through delegated records instead of copying compatible
legacy business data.

Implemented staging controls:

- campaign-owned `cc.script` identities and immutable `cc.script.version` rows;
- separate author/submission/approval, one approved version, and SHA-256 content
  binding;
- server-derived campaign rendering that omits internal prohibited-language and
  supervisor-only sections;
- exactly-once, append-only agent acknowledgement evidence;
- versioned `cc.disposition.set` and canonical `cc.disposition` adoption models;
- global campaign rules, agent approved-state filters, field restrictions,
  blocked bulk export, and immutable ownership;
- hard validation for one-to-six-character VICIdial status codes and versioned
  event names.

The original controlled `odoo_campaign_disposition_catalog.csv` is not present.
Every new disposition set therefore starts with `catalog_status=missing`, and
review/approval is blocked. No placeholder catalog, disposition seed, external
publication, live call control, or production activation is included.
