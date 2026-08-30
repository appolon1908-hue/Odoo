# Odoo — Marketing and CRM System-of-Record Contract

## Mission
Odoo is the authoritative CRM/business system of record for leads, contacts, opportunities, activities, campaign-linked sales outcomes and downstream commercial workflow.

## Owns
- Lead/contact/opportunity records
- Sales pipeline stages and ownership
- Activities, appointments and follow-up tasks
- Campaign/source references used for CRM reporting
- Customer/account master records
- Qualified lead handoff to sales/closers
- Revenue outcomes used for closed-loop attribution

## Does Not Own
- Paid ad campaign execution or budgets
- AI provider routing
- Social publishing runtime
- Raw messaging provider delivery
- Gateway or identity policy
- Generic cross-system integration transport

## Canonical Lead Flow
Ad/social/form source -> Kong -> Middleware -> Codestra Marketing attribution -> Odoo lead/opportunity -> n8n workflow -> Codestra Communication/AI -> sales activity -> Odoo outcome -> Marketing attribution feedback.

## Required Data Contract
Each marketing-originated lead should preserve tenant/business, campaign ID, external campaign/ad identifiers, source, medium, landing context, consent metadata, correlation ID, first-touch timestamp, latest-touch timestamp and attribution version where available.

## Isolation and Authorization
Odoo access must respect the existing campaign/business isolation model. Marketing integration may create/update only the records and fields authorized by its service identity and must never broaden agent visibility across campaigns.

## Required Integration APIs/Module Surface
- Lead upsert by stable external identity
- Campaign/source mapping
- Activity/appointment creation
- Opportunity stage/outcome event publication
- Revenue/conversion feedback
- Communication history references
- Audit/correlation metadata

## Implementation Order
1. Canonical campaign/source mapping model
2. Idempotent lead ingestion
3. Attribution metadata fields
4. Activity/appointment synchronization
5. Opportunity outcome events
6. Revenue feedback to Marketing
7. Communication history linkage
8. Campaign-isolation and permission tests
9. Reporting and reconciliation