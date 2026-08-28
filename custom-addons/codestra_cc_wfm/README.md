# Codestra Contact Center Workforce Management

Campaign-scoped workforce policy, interval forecast, agent schedule, separately
approved schedule-change and overtime workflow, normalized adherence evidence,
exception acknowledgement, and privacy-minimized real-time capacity snapshots.

Published schedules are immutable. A change, cancellation, or overtime request
binds to the original schedule hash, requires a different primary supervisor or
global administrator to approve it, and may be applied only by campaign WFM.
Application cancels the original and publishes a replacement while retaining
the request, decision, and application hashes as evidence.

The module adds no dialer writer or public route. Normalized state and aggregate
metric ingestion is available only to the private event-service role, is
idempotent, and stores hashes rather than raw external payloads.
