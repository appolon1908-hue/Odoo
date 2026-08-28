# Campaign CRM migration policy

This branch does not automatically adopt unrestricted `res.partner` or legacy
`crm.lead` rows into campaign workspaces. A controlled migration must first map
each record to exactly one canonical campaign, reject ambiguous or missing
ownership, create the tokenized `cc.customer.profile` through the governed CRM
service, and reconcile the canonical and legacy campaign/business-unit fields.

Dry-run counts, duplicate detection, rejected rows, reversible mapping evidence,
and a post-migration campaign-isolation read-back are required before activation.
No customer profile may be created from browser context or an inferred default.
