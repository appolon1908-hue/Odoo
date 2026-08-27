# Odoo CRM fabric branch map

```text
integration/n8n-automation-contract-v2-20260827
  -> integration/codestra-crm-fabric-v2
       -> feature/crm-facade-api-v1
       -> feature/automation-outbox-v1
       -> feature/communication-history-v1
       -> feature/consent-projection-v1
       -> feature/contact-center-automation-v1
       -> test/crm-fabric-contracts-v1
```

No child branch may bundle gateway, n8n, telephony-provider, email-provider, SMS-provider, crawler-worker, or production deployment changes.