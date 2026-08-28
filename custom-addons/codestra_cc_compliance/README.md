# Codestra Contact Center Compliance

Adds campaign- and jurisdiction-versioned policy, immutable consent and
revocation evidence, immediate DNC/suppression, customer-local calling-window
decisions, fail-closed outreach capabilities, tokenized payment/recording-pause
evidence, legal holds, and retention decisions.

The pre-dial helper is invoked before the existing click-to-call agent and
middleware lookup for governed CRM records. Predictive, automated, AI-voice,
prerecorded-voice, payment-delivery, bulk-export, and every production feature
remain disabled. No direct VICIdial, Middleware, payment-provider, or recording
mutation is implemented.

Payment-card data, security codes, bank credentials, and authentication secrets
are rejected from governed CRM descriptions, campaign notes, and chatter.
Provider and evidence references are retained only as SHA-256 values. Legal and
jurisdictional approval, external read-back, and production activation remain
formal release gates.
