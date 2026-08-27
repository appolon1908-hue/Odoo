# CC-04 — Supervisor, Quality, Compliance, and Case Management

This branch adds mission ownership facades for supervisor operations, QA, and compliance, plus the first new operational business model: `codestra.case`.

## Case controls

- company isolation through record rules;
- links to existing customer, lead, campaign, and call records rather than copied data;
- validated complaint, dispute, refund-review, incident, and executive-escalation categories;
- deterministic state transitions;
- escalation reason and resolution requirements;
- chatter evidence for state changes;
- business-user deletion denied.

## Safety

Supervisor and provider controls remain disabled. Installing source does not authorize listening, whispering, barging, customer communication, refund execution, or external delivery.
