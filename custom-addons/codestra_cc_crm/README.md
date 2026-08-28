# Codestra Contact Center CRM

Canonical campaign CRM boundary for Odoo 19. Agents work through
`cc.customer.profile`, a campaign-owned projection with masked contact hints and
a restricted link to the authoritative contact. The global Contacts application
is not added to the campaign workspace.

Campaign CRM leads store a canonical `campaign_id`, customer profile, source-list
key, consent state, environment, and scope version. Operational creation derives
campaign authority from the authenticated active membership or selected profile;
browser/context campaign values cannot switch scope. Canonical ownership is also
kept consistent with the existing legacy campaign fields for compatibility.

Global record rules cover search, direct IDs, autocomplete, grouped queries, and
related campaign data. Agent/supervisor bulk export, copy, campaign reassignment,
raw contact rebinding, and customer-profile deletion are denied.
