# Codestra Contact Center Agent Desktop

Mission facade for the existing call popup, active-call workspace, customer context, campaign script, notes, callbacks, dispositions, prior interactions, and guarded call-control components.

The browser is not an authorization source. Record, campaign, tenant, and agent ownership are always resolved server-side. Required wrap-up remains a server-side rule before returning an agent to Ready.

The desktop consumes the canonical customer profiles, CRM records, and campaign support tickets from `codestra_cc_crm` and `codestra_cc_helpdesk`; it does not maintain a parallel customer or ticket store.
