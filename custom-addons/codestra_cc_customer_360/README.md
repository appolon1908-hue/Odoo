# Codestra Contact Center Customer 360

Mission facade for one authorized timeline spanning calls, CRM activity, messages, appointments, callbacks, consent, complaints, and protected recording references.

It does not create a duplicate customer master. Contacts, leads, activities, and related business records remain owned by their audited Odoo models.

`codestra_cc_crm` owns the campaign-scoped customer projection and canonical CRM ownership. `codestra_cc_helpdesk` owns campaign queues, governed SLAs, and support tickets. This module composes those records into the authorized Customer 360 experience without copying them.
