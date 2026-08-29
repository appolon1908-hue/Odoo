# Codestra Client Portal

Authenticated client users can read only contracts, SLA definitions, and approved or invoiced usage owned by their commercial partner. Controller searches run without `sudo()` and are protected by portal ACLs plus partner-scoped record rules.

Restricted recordings, internal QA, raw call events, provider credentials, and cross-client data are not exposed. Additional ticket, lead, invoice-document, and approved-evidence views require separate reviewed access rules before being added.
