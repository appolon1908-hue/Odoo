# Codestra Revenue Assurance

Versioned client rate plans and immutable usage snapshots for provider cost, revenue, and gross margin. Plans are scoped to a client contract, optional governed campaign, billable unit, currency, and non-overlapping effective range.

Usage accepts an idempotency key and only an active plan. Unit rate and provider cost are copied into immutable snapshots so later plan versions cannot rewrite historical economics. Invoice linkage is explicit; this module never fabricates provider events or customer usage.
