# ADR-001: Campaign membership is the operational security scope

- Status: Accepted for staging implementation
- Date: 2026-08-28

## Decision

`cc.campaign.membership` is the sole human operational scope for agent and
supervisor access. Agents and senior agents have exactly one active operational
membership. Supervisors have exactly one active campaign, and every active
human-staffed campaign has exactly one active primary supervisor. Partial unique
indexes enforce the cardinality in PostgreSQL; Python constraints provide safe
messages; global record rules enforce scope on every campaign-owned model.

Authorization must cover ORM reads/writes, name search, grouped reads, exports,
mail, chatter, attachments, activities, bus notifications, reports, controllers,
and service methods. UI hiding is not authorization. Any privileged service path
must revalidate the campaign both before and after elevation.

## Consequences

The existing `authorized_user_ids` and `supervisor_ids` relations cannot remain an
independent authorization source. They require a controlled compatibility bridge
and migration to membership records. Ambiguous zero/multiple membership denies the
contact-center session. Reassignment revokes old sessions and completes only after
desired/actual read-back.
