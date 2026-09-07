# Codestra Campaign-Specific CRM Operating Model
## Odoo 19, VICIdial, VoIP, Automation, Roles, Governance, and Controls — Master Specification v2.0

> **Document class:** Engineering specification and Codex execution contract  
> **Platform:** Self-hosted Odoo 19 with controlled middleware and VICIdial/Asterisk integration  
> **Implementation posture:** Staging-first and fail-closed  
> **Production activation:** Not authorized by this document  
> **Audience:** Odoo developers, telephony engineers, middleware engineers, DevOps, security, QA, operations, and business-unit owners

---

## Document Control

| Field | Value |
|---|---|
| Specification version | 2.0 |
| Status | Approved for staged implementation and synthetic testing |
| Primary implementation root | `/root/codestra-production-completion` |
| Telephony implementation root | `/root/vicidial-sync-remediation` |
| Default feature-flag state | `false` |
| Default n8n workflow state | Inactive |
| Default event-delivery state | Disabled |
| Evidence standard | Functional execution + authoritative read-back + test result + checksum |
| Maximum recommendation without separate production approval | `STAGING-ONLY` |

### Change boundary

This specification authorizes discovery, development, controlled migrations, staging deployment, synthetic testing, reconciliation, rollback validation, documentation, and evidence generation.

It does **not** authorize:

- unrestricted production dialing;
- predictive dialing;
- customer communications;
- public DID reassignment;
- carrier-account changes;
- production lead publication;
- production n8n activation;
- AI voice activation;
- persistent production event delivery;
- production campaign activation;
- full production cutover.

---

## Executive Summary

Codestra requires one Odoo 19 platform that supports eight independently governed business units without forcing them into one generic CRM pipeline.

Each business unit must have its own:

- sales team and management hierarchy;
- pipeline stages and stage-transition rules;
- qualification fields and scoring;
- activity and SLA policies;
- dispositions and lost reasons;
- VICIdial campaign, user-group, inbound-group, and closer mappings;
- approval controls;
- dashboards and KPIs;
- backend security scope.

Shared foundations should be implemented once. Business-specific processes must remain configurable, version-controlled, testable, and independently secured.

The target is a professional operating platform—not a collection of manually configured CRM screens. Every critical rule must be implemented in backend models, constraints, access controls, record rules, middleware validation, migrations, XML data, and automated tests.

---

## Business Units

| Code | Business unit | Primary operating focus | Campaign prefix | Special governance |
|---|---|---|---|---|
| `MOY` | Moy Logistics | Transportation, freight, dispatch, carriers, shippers | `MOY-` | Authority, insurance, equipment, route validation |
| `COD` | Codestra | Web, mobile, AI, Odoo, automation, cloud services | `COD-` | Technical discovery, scope, estimate, delivery handoff |
| `SCP` | Senior Citizen Products | Product sales, caregivers, orders, support, reorders | `SCP-` | Consent, accessibility, non-medical claims, recurring-charge clarity |
| `MBL` | MoneyBee Business Loans | Working capital and business financing | `MBL-` | Human lending decision, underwriting approvals, document controls |
| `RLP` | RLP International Real Estate | Buyers, sellers, renters, investors | `RLP-` | Financial readiness, property matching, offer and closing controls |
| `FTP` | For the People | Donations, pledges, sponsorships, donor retention | `FTP-` | Consent, receipts, recurring donations, donor audit |
| `TRX` | TradeX | Trading technology, analytics, subscriptions, integrations | `TRX-` | Suitability, risk disclosure, no guaranteed-profit claims |
| `CAL` | Calderon Farm | Wholesale, export, produce contracts, partners | `CAL-` | Harvest, quality, packaging, logistics, export requirements |

---

## Authoritative Infrastructure Assignment

### Server A — Application and Control Plane

| Item | Value |
|---|---|
| Public IP | `65.109.65.169` |
| Private IP | `10.40.0.1` |
| Responsibilities | Odoo, middleware, n8n, PostgreSQL, Redis, NATS, Keycloak, Agent Desktop, AI, reporting, monitoring, evidence, release governance |
| Project root | `/root/codestra-production-completion` |
| Lock root | `/root/codestra-production-completion/.locks` |

### Server B — Telephony and Media Plane

| Item | Value |
|---|---|
| Public IP | `65.21.67.207` |
| Private IP | `10.40.0.2` |
| Responsibilities | VICIdial, Asterisk, MariaDB, campaigns, users, queues, SIP/WebRTC, carriers, recordings, telephony adapters, provisioning |
| Project root | `/root/vicidial-sync-remediation` |
| Lock root | `/root/vicidial-sync-remediation/.locks` |

### Cross-server rule

```text
Server A orchestrates cross-server work.
Server A may connect to Server B through the approved restricted SSH identity.
Server B must not require reverse SSH access to Server A.
```

---

## System-of-Record Matrix

| Domain | Authoritative system | Projection or consumer | Prohibited authority |
|---|---|---|---|
| Customers, leads, opportunities | Odoo | Middleware, reporting | VICIdial |
| Business units, teams, roles | Odoo | Keycloak, middleware | Browser-only filters |
| Business campaign definition | Odoo | Middleware, VICIdial test projection | Manual production-only setup |
| Runtime telephony campaigns | VICIdial | Odoo status projection | n8n |
| Live call state | Asterisk/VICIdial | Agent Desktop | Optimistic Odoo state |
| Canonical call session | Middleware/Odoo | Reporting | Ad hoc log-table joins |
| Raw recordings | Controlled object storage | Odoo opaque reference | Public URL |
| Identity | Keycloak | Odoo/VICIdial mapping | Shared passwords |
| Event delivery state | Middleware outbox | Odoo audit model | n8n memory |
| AI outputs | Odoo audited records | Reporting | Unversioned free text |
| Feature flags | Authoritative registry | Service-local cache | Unreconciled scattered flags |
| Evidence | Restricted evidence store | Executive report | Application logs containing secrets |

---

## Target Module Architecture

### Foundation

- `codestra_business_unit`
- `codestra_org_structure`
- `codestra_security_core`
- `codestra_feature_flags`
- `codestra_audit`

### CRM and pipeline

- `codestra_crm_core`
- `codestra_crm_pipeline`
- `codestra_customer_journey`
- `codestra_lead_assignment`
- `codestra_approval_controls`
- `codestra_disposition`

### Telephony and agent operations

- `codestra_call_session`
- `codestra_vicidial_connector`
- `codestra_transfer_management`
- `codestra_agent_desktop`
- `codestra_ivr`
- `codestra_callback`
- `codestra_appointment_prep`

### Business operations

- `codestra_support`
- `codestra_fulfillment`
- `codestra_retention`
- `codestra_upsell`
- `codestra_workforce`
- `codestra_commission`

### Automation, AI, and reporting

- `codestra_automation_registry`
- `codestra_ai_core`
- `codestra_ai_qualification`
- `codestra_ai_transcription`
- `codestra_ai_call_audit`
- `codestra_ai_realtime_assistant`
- `codestra_reporting_core`
- `codestra_executive_dashboard`

### Reuse rule

Codex must first inventory existing modules and reuse compatible implementation. New modules are permitted only when they avoid duplicate models, conflicting migrations, duplicate security groups, and overlapping business logic.

---

## Data and Pipeline Governance

Every operational record must include, where applicable:

```text
business_unit_id
campaign_id
department_id
team_id
user_id
supervisor_id
company_id
security_classification
correlation_id
```

Every pipeline stage policy must define:

```text
pipeline
business_unit
sequence
allowed_source_stages
allowed_destination_stages
required_fields
allowed_roles
sla_duration
automatic_activities
automatic_notifications
disposition_mappings
approval_requirements
lost_reason_requirements
audit_behavior
policy_version
```

### Stage-transition rule

No user or automation may skip required stages unless an explicit, audited approval rule permits it.

Every transition must record:

- previous stage;
- new stage;
- trigger;
- user or service identity;
- timestamp;
- policy version;
- correlation ID;
- reason;
- approval reference when applicable.

---

## Security Model

Security must be enforced through:

- model access-control lists;
- backend record rules;
- field-level restrictions;
- model constraints;
- controller authorization;
- middleware authorization;
- Keycloak claims;
- VICIdial user groups;
- inbound-group permissions;
- WebSocket scopes;
- export restrictions;
- immutable audit records.

Hidden menus, hidden fields, disabled buttons, Studio layouts, and browser filtering are presentation controls—not security controls.

Required negative tests include:

- cross-business-unit denial;
- cross-campaign denial;
- cross-team denial;
- unauthorized reassignment denial;
- unauthorized export denial;
- unauthorized recording denial;
- unauthorized transcript denial;
- unauthorized API denial;
- do-not-call override denial;
- consent override denial.

---

## Telephony Integration Boundary

```text
VICIdial / Asterisk
        ↓
Controlled Codestra Middleware
        ↓
Odoo call, screen-pop, callback, transfer, and reconciliation APIs
```

Rules:

- Odoo and n8n must never perform operational writes directly to the VICIdial database.
- n8n must not participate in live SIP, RTP, call control, warm transfer, or real-time WebSocket screen-pop paths.
- Call state shown in Odoo must be authoritative, not optimistic.
- Every event and command must be authenticated, schema validated, idempotent, bounded, auditable, and reconciled.

---

## Canonical Event Controls

Every cross-system event must include:

```json
{
  "schema_version": 1,
  "event_id": "uuid",
  "event_type": "call.ended",
  "occurred_at": "UTC RFC3339",
  "observed_at": "UTC RFC3339",
  "source": {
    "system": "asterisk|vicidial|odoo|n8n",
    "server": "logical-server-id",
    "boot_id": "optional"
  },
  "business_unit_code": "COD",
  "campaign_code": "COD-WEB-OUT",
  "correlation_id": "stable-id",
  "deduplication_key": "sha256",
  "payload": {},
  "redaction_version": "1"
}
```

Required controls:

- mTLS or equivalent service authentication;
- request signature verification;
- idempotency keys;
- durable acceptance before success response;
- explicit delivery eligibility;
- bounded retries;
- dead-letter handling;
- circuit breaking;
- no historical replay;
- reconciliation after every accepted write;
- no response-body or secret logging.

---

## Implementation Program

| Phase | Scope | Exit gate |
|---|---|---|
| 0 | Discovery and reuse inventory | Inventory complete; no mutation before review |
| 1 | Foundation, business units, hierarchy, security | All negative security tests pass |
| 2 | CRM teams, fields, pipelines, aliases, activities | Repeatable clean-database recreation passes |
| 3 | Assignment, dispositions, approvals, lost reasons | Functional and audit tests pass |
| 4 | Middleware contracts and event reconciliation | Authentication, idempotency, retry, dead letter, read-back pass |
| 5 | VICIdial test projection and provisioning | Create/read-back/duplicate/cleanup pass |
| 6 | Agent Desktop, transfers, callbacks, IVR, appointments | Authoritative state and same-campaign transfer tests pass |
| 7 | Support, fulfillment, retention, upsell | End-to-end customer-journey linkage passes |
| 8 | n8n staging automation | Workflows inactive, versioned, idempotent, auditable |
| 9 | AI and human review | Structured outputs and prohibited-action tests pass |
| 10 | Dashboards and reporting | Metric lineage and reconciliation pass |
| 11 | Migration, UAT, restore, release candidate | Named-owner UAT and rollback rehearsal pass |
| 12 | Production cutover | Separate authenticated authorization required |

---

## Evidence Standard

A feature may be marked `PASS` only when all four conditions are met:

1. Functional execution
2. Authoritative read-back
3. Automated or controlled test result
4. Checksummed evidence reference

Every change must produce:

```text
evidence/<change-id>/
├── BASELINE.md
├── COMMAND-LEDGER.md
├── FILES-CHANGED.tsv
├── MIGRATIONS.md
├── TEST-RESULTS.md
├── SECURITY-RESULTS.md
├── RECONCILIATION.md
├── ROLLBACK.md
├── FINAL-REPORT.md
└── SHA256SUMS
```

Evidence must not contain secrets, raw authorization headers, full protected telephone numbers, customer audio, or unrestricted customer data.

---

---

# Detailed Functional Requirements

## 1. Objective

Develop a complete Odoo 19 CRM operating model for all Codestra business units and campaigns.

Do not use one generic pipeline for every team.

Each business unit must have:

- Its own CRM sales team
- Its own pipeline stages
- Its own required fields
- Its own qualification rules
- Its own lead-assignment rules
- Its own activities
- Its own dispositions
- Its own approval requirements
- Its own sales and operational KPIs
- Its own VICIdial campaign mappings
- Its own inbound and closer groups
- Its own security boundaries

The implementation must support:

1. Moy Logistics
2. Codestra
3. Senior Citizen Products
4. MoneyBee Business Loans
5. RLP International Real Estate
6. For the People Fundraising
7. TradeX
8. Calderon Farm

Production dialing, production lead publication, and production campaign activation must remain disabled until acceptance testing is complete.

---

## 2. Required Development Approach

Codex must build the CRM layer in the following order:

1. Inspect existing Odoo CRM customizations.
2. Inventory current models, fields, stages, teams, activities, and security rules.
3. Reuse compatible modules and models.
4. Create shared CRM foundations.
5. Create specialized pipelines for each business unit.
6. Add required fields and validation rules.
7. Implement activities and SLA policies.
8. Implement lead assignment.
9. Implement dispositions.
10. Implement role-specific permissions.
11. Connect the Phone/VoIP event model.
12. Add approval controls.
13. Add dashboards and reports.
14. Run automated security and workflow tests.
15. Produce an evidence-backed implementation report.

Do not create duplicate fields when equivalent fields already exist.

Do not rely only on manually configured Studio fields. Business-critical fields, rules, mappings, security, and test data should be version-controlled through custom modules, XML records, migrations, and automated tests.

Studio may be used for safe presentation changes, prototypes, or approved fields that do not require complex backend enforcement.

---

## 3. Shared CRM Foundation

Extend the following models where appropriate:

- `crm.lead`
- `crm.team`
- `res.partner`
- `mail.activity`
- `calendar.event`
- `sale.order`
- `helpdesk.ticket`
- `res.users`
- `hr.employee`

Create shared custom models:

- `codestra.business.unit`
- `codestra.campaign`
- `codestra.department`
- `codestra.operational.team`
- `codestra.disposition`
- `codestra.call.session`
- `codestra.transfer.session`
- `codestra.customer.journey`
- `codestra.sla.policy`
- `codestra.approval.request`
- `codestra.lead.assignment.rule`
- `codestra.pipeline.stage.policy`

---

## 4. Required Shared CRM Fields

Every lead or opportunity must include:

### Ownership and Security

- Business unit
- Sales team
- Department
- Operational team
- Campaign
- Assigned agent
- Assigned supervisor
- Account owner
- Security classification

### Contact Information

- Customer name
- Company
- Primary phone
- Normalized phone
- Alternate phone
- Email
- Preferred language
- Preferred contact method
- Customer time zone
- Preferred callback date and time

### Lead Attribution

- Lead source
- Source provider
- External lead ID
- Form or vendor ID
- UTM source
- UTM campaign
- UTM medium
- Original ingestion timestamp

### Qualification

- Fit Score
- Urgency Rating
- Lead priority
- Qualification status
- Decision-maker status
- Estimated revenue
- Expected close date
- AI summary
- Next Best Action
- Missing-information flags

### Consent and Communication

- Phone consent
- Email consent
- SMS consent
- Recording consent
- Do-not-call status
- Consent source
- Consent timestamp
- Consent version
- Contact-limit status

### Call-Center Fields

- VICIdial lead ID
- Last Call UniqueID
- Last disposition
- Call-attempt count
- Last call date
- Next callback
- Transfer status
- Closer assignment
- Recording reference
- Transcript reference

---

## 5. Pipeline Design Rules

Each pipeline stage must define:

- Business unit
- Pipeline
- Stage sequence
- Allowed originating stages
- Allowed destination stages
- Required fields
- Allowed roles
- SLA duration
- Automatic activities
- Automatic notifications
- Disposition mappings
- Approval requirements
- Lost-reason requirements
- Audit behavior

Codex must prevent unrestricted stage skipping.

Example:

```text
New Lead
→ Qualified
```

This transition should fail when validation, consent, or mandatory qualification steps are incomplete.

Each automated stage change must record:

- Previous stage
- New stage
- Trigger
- Acting user or service
- Timestamp
- Rule version
- Correlation ID
- Reason

---

## 6. Moy Logistics CRM Pipeline

### 6.1 Primary Purpose

Manage:

- Shippers
- Carriers
- Brokers
- Owner-operators
- Dispatch clients
- Freight customers
- Medical transportation customers
- Logistics partnerships

### 6.2 Recommended Pipeline

```text
New Logistics Lead
→ Contact and Data Validation
→ Lead Type Classification
→ Authority and Eligibility Review
→ AI Pre-Qualification
→ Initial SDR Contact
→ Operational Needs Assessment
→ Qualified Logistics Opportunity
→ Quote or Rate Request
→ Closer Handoff
→ Proposal or Rate Confirmation
→ Negotiation
→ Contract Pending
→ Contract Signed
→ Onboarding
→ Active Account
→ Retention
→ Expansion or Upsell
```

### 6.3 Lead-Type Subclassification

Required values:

- Shipper
- Carrier
- Broker
- Owner-Operator
- Fleet
- Dispatch Client
- Medical Transportation
- Passenger Transportation
- Courier
- Freight Forwarding
- Warehousing
- Other Logistics Prospect

### 6.4 Required Logistics Fields

#### Contact and Business

- Customer type
- Company name
- Contact name
- Decision-maker role
- Phone
- Email
- Preferred callback date
- Lead source
- Assigned campaign

#### Freight and Route

- Origin
- Destination
- Preferred lanes
- Freight type
- Load frequency
- Estimated monthly volume
- Average shipment weight
- Pickup requirements
- Delivery requirements

#### Equipment

- Equipment type
- Dry van
- Reefer
- Flatbed
- Box truck
- Sprinter van
- Specialized equipment
- Fleet size
- Number of drivers

#### Commercial

- Target rate
- Current provider
- Current dispatch rate
- Estimated monthly value
- Payment terms
- Factoring company
- Contract duration

#### Authority and Compliance

- DOT number
- MC number
- Authority status
- License details
- Insurance provider
- Insurance expiration
- Insurance requirements
- Safety or compliance review status

### 6.5 Stage Gates

#### Authority and Eligibility Review

Require when applicable:

- DOT or MC number
- Authority status
- Equipment type
- Operating region

#### Qualified Logistics Opportunity

Require:

- Lead type
- Operational need
- Route or service information
- Estimated volume
- Decision-maker status
- Expected value

#### Contract Signed

Require:

- Contract reference
- Pricing or rate terms
- Start date
- Responsible onboarding owner

### 6.6 Logistics Activities

- Verify DOT/MC
- Carrier Qualification Call
- Shipper Discovery Call
- Send Rate Sheet
- Request Insurance
- Request Carrier Packet
- Prepare Freight Quote
- Closer Follow-Up
- Contract Review
- Carrier Onboarding
- First Load Follow-Up
- Account Retention Review

### 6.7 Logistics Campaign Mapping

- `MOY-CARRIER-OUT`
- `MOY-SHIPPER-OUT`
- `MOY-DISPATCH-OUT`
- `MOY-SUPPORT-IN`
- `MOY-RETENTION-OUT`
- `MOY-UPSELL-OUT`

---

## 7. Codestra CRM Pipeline

### 7.1 Primary Purpose

Manage sales for:

- Website development
- E-commerce
- Mobile applications
- AI systems
- AI voice agents
- Odoo implementations
- CRM systems
- n8n automation
- Middleware
- Cloud infrastructure
- Hosting
- Maintenance
- Consulting

### 7.2 Recommended Pipeline

```text
New Technology Lead
→ Contact Validation
→ Company and Technology Enrichment
→ Service Classification
→ AI Pre-Qualification
→ SDR Discovery
→ Discovery Appointment Scheduled
→ Discovery Completed
→ Technical Review Required
→ Solutions Consultant Review
→ Qualified Technical Opportunity
→ Scope Preparation
→ Estimate Preparation
→ Proposal Sent
→ Proposal Follow-Up
→ Negotiation
→ Contract Review
→ Contract Signed
→ Deposit Pending
→ Deposit Received
→ Project Handoff
→ Delivery
→ Launch
→ Maintenance
→ Renewal
→ Upsell
```

### 7.3 Required Codestra Fields

#### Customer and Company

- Company name
- Industry
- Company size
- Decision maker
- Number of stakeholders
- Current website
- Current application
- Existing CRM
- Existing technology stack

#### Service Requirements

- Requested service
- Website type
- Mobile platform
- AI use case
- Odoo requirement
- Automation requirement
- Required integrations
- Hosting requirement
- Security requirement
- Support requirement

#### Commercial

- Budget range
- Estimated value
- Desired launch date
- Procurement process
- Payment expectations
- Maintenance interest
- Subscription interest

#### Technical Discovery

- Current systems
- Data sources
- API requirements
- User count
- Expected call volume
- Expected transaction volume
- Technical complexity
- Architecture-review status
- Engineering-review owner

### 7.4 Service Classification

Required values:

- Website
- E-commerce
- Mobile Application
- AI Voice Agent
- AI Chatbot
- Custom AI
- Odoo Implementation
- Odoo Customization
- VICIdial Integration
- n8n Automation
- Middleware
- Cloud Infrastructure
- Hosting
- Maintenance
- Technical Support
- Digital Marketing

### 7.5 Stage Gates

#### Discovery Completed

Require:

- Business problem
- Requested solution
- Budget range
- Timeline
- Decision-maker status
- Required integrations

#### Proposal Sent

Require:

- Scope
- Estimated hours
- Price
- Delivery timeline
- Proposal document

#### Project Handoff

Require:

- Signed contract
- Deposit status
- Approved scope
- Project manager
- Delivery milestones

### 7.6 Codestra Activities

- Initial Technology Call
- Website Audit
- Technical Discovery Meeting
- Requirements Review
- Engineering Estimate
- Proposal Preparation
- Proposal Follow-Up
- Contract Review
- Deposit Follow-Up
- Project Kickoff
- Maintenance Renewal
- Upsell Review

---

## 8. Senior Citizen Products CRM Pipeline

### 8.1 Primary Purpose

Manage:

- Product inquiries
- Caregiver inquiries
- Product sales
- Orders
- Support
- Warranty
- Returns
- Reorders
- Subscriptions
- Retention

### 8.2 Recommended Pipeline

```text
New Inquiry
→ Consent and Contact Validation
→ First Contact
→ Customer or Caregiver Identification
→ Needs Assessment
→ Product Category Identified
→ Product Recommended
→ Customer Understanding Confirmed
→ Follow-Up Required
→ Order Preparation
→ Payment or Approval Pending
→ Payment Confirmed
→ Fulfillment
→ Shipment
→ Delivery Confirmation
→ Customer Follow-Up
→ Reorder Eligible
→ Retention
→ Won
```

Lost should be available from approved stages with a required lost reason.

### 8.3 Required Senior Products Fields

- Product interest
- Product category
- Customer or caregiver
- Caregiver name
- Relationship to customer
- Preferred contact method
- Preferred language
- Accessibility requirements
- Delivery address
- Billing address
- Follow-up date
- Consent status
- Do-not-call status
- Special handling notes
- Order value
- Subscription status
- Reorder frequency
- Warranty status
- Return status
- Customer understanding confirmed
- Pricing explained
- Recurring-payment terms explained
- Shipping terms explained

### 8.4 Compliance Restrictions

Do not require unnecessary medical details.

Do not allow agents or AI to:

- Diagnose conditions
- Promise a cure
- Claim unsupported treatment benefits
- Misrepresent government affiliation
- Misrepresent insurance coverage
- Hide recurring charges
- Override do-not-call restrictions

### 8.5 Stage Gates

#### Product Recommended

Require:

- Product category
- Customer need
- Customer or caregiver identification
- Approved product recommendation

#### Customer Understanding Confirmed

Require:

- Price explained
- Shipping explained
- Recurring terms explained where applicable
- Consent confirmed

#### Payment Confirmed

Require:

- Order reference
- Payment status
- Product
- Quantity
- Delivery address

### 8.6 Senior Products Activities

- Initial Product Call
- Caregiver Follow-Up
- Send Product Information
- Pricing Confirmation
- Order Confirmation
- Payment Follow-Up
- Shipment Follow-Up
- Delivery Confirmation
- Warranty Review
- Reorder Reminder
- Retention Call
- Compliance Review

---

## 9. MoneyBee Business Loans CRM Pipeline

### 9.1 Recommended Pipeline

```text
New Loan Lead
→ Contact Validation
→ Business Validation
→ Consent Verification
→ AI Pre-Qualification
→ Initial Loan Call
→ Funding Needs Assessment
→ Preliminary Eligibility Review
→ Document Request
→ Documents Pending
→ Application Started
→ Application Complete
→ Underwriting Review
→ Additional Information Required
→ Offer Available
→ Closer Review
→ Offer Accepted
→ Contract Signed
→ Funding Pending
→ Funded
→ Renewal Eligible
→ Renewal
```

### 9.2 Required Loan Fields

- Business name
- Owner name
- Business type
- Industry
- Years in business
- Monthly revenue
- Annual revenue
- Requested amount
- Purpose of funds
- Existing obligations
- Credit range
- Bank-statement status
- Decision maker
- Funding timeline
- Application status
- Underwriter
- Approved amount
- Offer terms
- Funding status
- Renewal date
- Consent status

### 9.3 Controls

AI may assist with qualification but must not make a final lending decision.

Require approval for:

- Marking underwriting approved
- Changing approved amount
- Changing offer terms
- Marking funded
- Overriding an eligibility hold

### 9.4 Activities

- Initial Funding Call
- Request Bank Statements
- Request Business Documents
- Application Follow-Up
- Underwriting Follow-Up
- Offer Review
- Contract Signature Follow-Up
- Funding Confirmation
- Renewal Review

---

## 10. RLP International Real Estate CRM Pipeline

### 10.1 Recommended Pipeline

```text
New Real Estate Lead
→ Contact Validation
→ Buyer, Seller, Renter, or Investor Classification
→ AI Qualification
→ Initial Agent Contact
→ Needs Assessment
→ Financial Readiness Review
→ Property Search or Listing Review
→ Property Match
→ Appointment Scheduled
→ Property Viewing
→ Follow-Up
→ Offer Preparation
→ Offer Submitted
→ Negotiation
→ Reservation or Deposit
→ Contract
→ Due Diligence
→ Closing Scheduled
→ Closed
→ Post-Closing Follow-Up
→ Referral
```

### 10.2 Required Real Estate Fields

- Lead type
- Buyer
- Seller
- Renter
- Investor
- Property type
- Location
- Preferred areas
- Budget
- Financing status
- Purchase timeline
- Number of bedrooms
- Number of bathrooms
- Property condition
- Investment objective
- Rental-yield target
- Assigned agent
- Property references
- Offer amount
- Commission
- Closing date

### 10.3 Activities

- Buyer Qualification Call
- Seller Discovery Call
- Financing Review
- Property Search
- Schedule Viewing
- Viewing Follow-Up
- Offer Preparation
- Contract Review
- Closing Preparation
- Post-Closing Follow-Up
- Referral Request

---

## 11. For the People Fundraising CRM Pipeline

### 11.1 Recommended Pipeline

```text
New Donor Lead
→ Consent Validation
→ Donor Classification
→ AI Pre-Qualification
→ Initial Fundraising Contact
→ Campaign Interest Identified
→ Fundraising Presentation
→ Donation Interest
→ Pledge Requested
→ Pledge Received
→ Donation Confirmation
→ Payment Pending
→ Payment Received
→ Receipt Issued
→ Donor Onboarding
→ Recurring Donation
→ Donor Retention
→ Upgrade or Sponsorship
```

### 11.2 Required Fundraising Fields

- Donor name
- Donor type
- Individual
- Company
- Sponsor
- Campaign interest
- Donation amount
- One-time or recurring
- Pledge date
- Payment status
- Receipt status
- Communication preference
- Consent status
- Donor tier
- Retention status
- Sponsorship interest

### 11.3 Activities

- Initial Donor Call
- Send Campaign Information
- Pledge Follow-Up
- Payment Follow-Up
- Send Receipt
- Donor Thank-You
- Recurring Donation Review
- Donor Retention Call
- Sponsorship Meeting

---

## 12. TradeX CRM Pipeline

### 12.1 Recommended Pipeline

```text
New TradeX Lead
→ Contact Validation
→ Customer Classification
→ Consent and Suitability Review
→ AI Pre-Qualification
→ Initial Sales Contact
→ Product Interest
→ Demo Scheduled
→ Demo Completed
→ Technical Discovery
→ Trial Requested
→ Trial Active
→ Trial Review
→ Qualified Opportunity
→ Technical Closer
→ Subscription Proposal
→ Contract Review
→ Contract Signed
→ Payment
→ Onboarding
→ Activation
→ Support
→ Renewal
→ Upsell
```

### 12.2 Required TradeX Fields

- Customer type
- Company
- Trading experience
- Product interest
- Platform
- Broker integration
- Data-feed requirement
- Number of users
- Budget
- Subscription level
- Trial status
- Demo date
- Risk disclosure acknowledged
- Contract status
- Renewal date
- Support tier

### 12.3 Compliance Controls

Require approved disclosure acknowledgment before:

- Demo completion
- Trial activation
- Contract signing

Agents and AI must not promise:

- Guaranteed profits
- Guaranteed returns
- Risk-free trading
- Specific future performance

### 12.4 Activities

- Initial TradeX Call
- Demo Appointment
- Technical Discovery
- Trial Setup
- Trial Follow-Up
- Risk Disclosure Review
- Proposal Follow-Up
- Onboarding
- Subscription Renewal

---

## 13. Calderon Farm CRM Pipeline

### 13.1 Recommended Pipeline

```text
New Buyer or Partner
→ Lead Classification
→ Buyer Validation
→ Product Interest
→ Quantity and Frequency Assessment
→ Quality and Packaging Requirements
→ Price Request
→ Sample or Farm Inspection
→ Quotation
→ Quotation Follow-Up
→ Negotiation
→ Purchase Order
→ Harvest Allocation
→ Packing
→ Logistics Scheduling
→ Delivery or Export
→ Invoice
→ Payment
→ Delivery Confirmation
→ Repeat Order
→ Contract Renewal
```

### 13.2 Required Farm Fields

- Buyer type
- Company
- Product
- Variety
- Requested quantity
- Order frequency
- Packaging
- Grade
- Delivery location
- Export country
- Required certifications
- Harvest date
- Target delivery date
- Price
- Payment terms
- Transportation requirement
- Repeat-order frequency
- Contract duration
- Inspection status
- Sample status

### 13.3 Activities

- Buyer Qualification Call
- Product Availability Review
- Send Product Sheet
- Arrange Sample
- Schedule Farm Inspection
- Prepare Quotation
- Confirm Harvest Allocation
- Confirm Packaging
- Schedule Logistics
- Delivery Confirmation
- Repeat Order Follow-Up

---

## 14. Lost Opportunity Management

Create controlled lost reasons by business unit.

### Universal Lost Reasons

- No Contact
- Not Interested
- Wrong Number
- Duplicate
- Existing Customer
- Budget
- Timing
- Competitor
- Missing Documents
- Ineligible
- Compliance Restriction
- Customer Cancelled
- Product Unavailable
- Service Unavailable

### Requirements

When marking lost:

- Require lost reason.
- Require comment for selected reasons.
- Record acting user.
- Record stage before loss.
- Create lost-review activity when required.
- Preserve call and activity history.
- Prevent deletion.

High-value lost opportunities must require supervisor or director approval.

---

## 15. User Roles and Permissions

### 15.1 CRM Agent

May:

- View assigned leads and opportunities
- Create leads
- Update approved customer fields
- Add call notes
- Schedule activities
- Move records through approved stages
- Select dispositions
- Create callbacks
- Use the Phone interface
- View personal performance
- View permitted recordings

May not:

- Delete leads
- Export customer lists
- Configure sales teams
- Manage users
- View unrelated business units
- Edit integrations
- Access all recordings
- Change automation rules
- Override consent
- Override do-not-call

Recommended base access:

```text
CRM User — Own Documents
```

Apply additional business-unit, campaign, team, and assignment record rules.

---

### 15.2 Senior Agent or Team Leader

May:

- Perform agent functions
- View assigned team records
- Reassign within the team
- Review overdue activities
- Monitor callbacks
- Assist with same-campaign transfers
- Review authorized recordings
- Correct dispositions with audit
- View team performance

May not:

- Manage global permissions
- Access integration credentials
- Export all-company records
- Access unrelated business units

Do not rely only on broad “All Documents” access. Add backend team and business-unit restrictions.

---

### 15.3 Supervisor

May:

- Monitor assigned pipeline
- Review calls and dispositions
- Reassign leads within authorized scope
- Approve escalations
- Review recordings
- Monitor callbacks
- Review missed activities
- View team reports
- Record quality-review results
- Handle failed transfers
- Escalate technical issues
- Assign coaching

Add review fields:

- Quality reviewed
- Quality score
- Supervisor comments
- Compliance status
- Escalation required
- Escalation reason
- Recording reviewed
- Review date
- Reviewed by

---

### 15.4 Campaign Manager

May:

- Create and update campaign configuration
- Configure campaign-specific stages
- Assign agents
- Review campaign conversion
- Review call outcomes
- Manage lead imports
- Review source performance
- Request campaign activation
- Review duplicate leads
- Approve campaign changes
- Configure disposition mappings
- Configure campaign activities

May not automatically:

- Manage all users
- Access integration secrets
- Access unrestricted system settings
- Access unrelated business units
- Activate production without approval

---

### 15.5 Business Unit Director

May:

- View all records in assigned business unit
- Review pipeline value
- Review forecasts
- Review team performance
- Approve special commercial terms
- Review lost reasons
- Review call-quality summaries
- Access business-unit dashboards
- Approve campaign launch requests
- Approve large opportunities

May not access another business unit without explicit cross-unit authorization.

---

### 15.6 Transfer Coordinator

Provide a focused workspace showing:

- Calls waiting for transfer
- Customer
- Current agent
- Business unit
- Campaign
- Requested destination
- Transfer status
- Available closer
- Specialist availability
- Transfer-attempt count
- Failure reason
- Customer hold time

Transfer stages:

```text
Transfer Requested
→ Waiting for Destination
→ Destination Contacted
→ Consulting
→ Transfer Connected
→ Transfer Failed
→ Callback Required
→ Completed
```

The coordinator must only route within the active campaign.

---

### 15.7 Closer

May:

- Receive assigned transferred opportunities
- Review qualification notes
- View relevant customer history
- Add closing notes
- Update expected revenue
- Create quotation
- Send proposal
- Mark won or request lost status
- Schedule follow-up
- Record final disposition
- Create fulfillment handoff

May not:

- Edit the source agent’s historical call events
- Change original call timestamps
- Change the original campaign
- Delete qualification history

---

### 15.8 Quality Assurance Reviewer

May:

- View authorized recordings
- Review call notes
- Assign quality scores
- Mark compliance findings
- Request coaching
- Record review comments
- Generate QA reports

Commercial CRM data should generally be read-only.

---

### 15.9 Integration Administrator

May:

- Manage webhook connector configuration
- Review integration events
- Review failed deliveries
- Replay approved test events
- Review mappings
- Review duplicate protection
- Review dead-letter records
- Rotate integration credentials

Must not automatically have unrestricted access to customer content.

---

### 15.10 Odoo Administrator

May manage:

- Applications
- Users
- Access rights
- Studio
- Automation
- Email configuration
- Phone configuration
- Technical troubleshooting

The administrator account must not be used for routine sales operations.

---

## 16. Activity Types

Create these shared activity types:

- Initial Call
- Second Call Attempt
- Third Call Attempt
- Send Information
- Discovery Meeting
- Requirements Review
- Supervisor Review
- Transfer Follow-Up
- Callback
- Proposal Follow-Up
- Contract Review
- Document Request
- Document Follow-Up
- Payment Follow-Up
- Quality Review
- Compliance Review
- Customer Onboarding
- Fulfillment Follow-Up
- Retention Review
- Lost Lead Review
- Renewal Follow-Up
- Reorder Follow-Up

---

## 17. Activity Plans

### Codestra Technology Lead

```text
Lead created
→ Initial Call immediately
→ Second Attempt after 4 business hours when unanswered
→ Discovery Meeting within 2 business days
→ Requirements Review after discovery
→ Proposal Follow-Up 3 days after proposal
→ Manager Escalation after 7 days without response
```

### Moy Logistics Lead

```text
Lead created
→ Initial Call immediately
→ Verify authority on first contact
→ Request documents within 1 business day
→ Quote Follow-Up within 24 hours
→ Contract Follow-Up after 3 business days
→ Onboarding activity after signature
```

### Senior Products Inquiry

```text
Inquiry created
→ First Contact immediately
→ Product Information after assessment
→ Order Follow-Up within 1 business day
→ Payment Follow-Up when pending
→ Delivery Confirmation after shipment
→ Reorder Reminder based on product policy
```

### MoneyBee Loan Lead

```text
Lead created
→ Initial Funding Call immediately
→ Document Request after qualification
→ Document Follow-Up after 1 business day
→ Application Review after documents received
→ Offer Follow-Up within 24 hours
→ Funding Confirmation after completion
```

---

## 18. Lead Assignment Engine

Create model:

`codestra.lead.assignment.rule`

Each rule must consider:

- Business unit
- Campaign
- Country
- Territory
- Service type
- Product interest
- Lead source
- Language
- Lead priority
- Fit Score
- Urgency Rating
- Agent availability
- Agent skills
- Existing account owner
- Current workload
- Shift
- Appointment capacity
- Closer requirements

### Assignment Priority

1. Existing customer owner
2. Exact business unit
3. Exact campaign
4. Required language
5. Required skill
6. Agent availability
7. Lowest active workload
8. Weighted round robin
9. Supervisor fallback

### Example Rules

- Freight leads → Moy Logistics
- Website leads → Codestra Web campaign
- AI inquiries → Codestra AI campaign
- Senior product inquiries → SCP Product campaign
- Business loan inquiries → MoneyBee
- Buyer leads → RLP Buyers
- Donation leads → For the People
- Trading software leads → TradeX
- Produce buyers → Calderon Farm
- High-value leads → Senior agent or closer review
- Existing customers → Current account owner
- Unanswered high-priority leads → Supervisor activity

Every assignment must be audited.

---

## 19. Phone Integration

Install and configure, as appropriate:

- CRM
- Sales
- Contacts
- Phone
- Discuss
- Calendar
- Helpdesk
- Studio where approved

For each user configure:

- Phone identity
- VICIdial user
- WebRTC or SIP endpoint
- Outbound caller ID
- Inbound permissions
- Campaign access
- Inbound-group access
- Working hours
- Transfer permissions
- Recording permissions
- Supervisor permissions
- Business unit
- Sales team

The custom call-center implementation must use:

```text
VICIdial/Asterisk
→ Controlled Middleware
→ Odoo call and screen-pop APIs
```

Do not expose unrestricted Odoo webhooks or direct VICIdial database writes.

---

## 20. Call-to-CRM Mapping

Every call must link to:

- Contact
- Lead or opportunity
- Assigned agent
- Supervisor
- Sales team
- Campaign
- Business unit
- Call direction
- Start time
- Answer time
- End time
- Duration
- Hold time
- Disposition
- Notes
- Callback
- Transfer result
- Recording reference
- Transcript reference
- AI summary
- QA result
- Compliance result

Call updates must be idempotent using Call UniqueID and event identifiers.

---

## 21. Disposition Framework

Create controlled dispositions.

### Universal Dispositions

- No Answer
- Busy
- Voicemail
- Wrong Number
- Disconnected Number
- Callback Requested
- Follow-Up Required
- Qualified
- Not Qualified
- Not Interested
- Do Not Call
- Transferred
- Transfer Failed
- Sale Completed
- Payment Pending
- Support Required
- Escalated
- Duplicate
- Existing Customer
- Appointment Scheduled
- Customer No-Show
- Documents Pending
- Compliance Review

Each disposition must define:

- Allowed campaigns
- Allowed roles
- Required fields
- Activity created
- Callback required
- Stage transition
- Lost behavior
- Supervisor approval
- Suppression behavior
- Retry delay
- Reporting category

---

## 22. Disposition Behaviors

### Callback Requested

Require:

- Callback date
- Callback time
- Time zone
- Callback reason

Actions:

- Create callback activity
- Keep opportunity open
- Assign callback to current agent
- Create VICIdial callback through middleware
- Schedule reminder

### Do Not Call

Require:

- Reason
- Customer confirmation
- Acting user

Actions:

- Update consent
- Add suppression
- Stop automated calling
- Stop SMS or email where appropriate
- Notify supervisor when policy requires
- Prevent future campaign publication
- Create immutable audit entry

### Transferred

Require:

- Transfer destination
- Transfer reason
- Handoff summary
- Transfer result

Actions:

- Update transfer session
- Preserve source-agent attribution
- Change ownership only after confirmed connection

### Sale Completed

Require:

- Product or service
- Value
- Payment status
- Contract or order reference
- Fulfillment owner

Actions:

- Mark opportunity won
- Create fulfillment handoff
- Schedule onboarding
- Preserve call and closer attribution

---

## 23. Approval Controls

Require approval for:

- Marking high-value opportunity lost
- Applying large discounts
- Changing final pricing
- External transfer
- Reopening closed opportunity
- Archiving sensitive records
- Customer-data export
- Changing business unit
- Changing account owner outside the team
- Overriding do-not-call
- Overriding consent restrictions
- Activating a production campaign
- Marking loan underwriting approved
- Changing loan offer terms
- Issuing large refunds
- Changing donation payment records
- TradeX compliance override

Approval records must contain:

- Requester
- Approver
- Action
- Record
- Previous value
- Requested value
- Reason
- Timestamp
- Result
- Expiration
- Audit reference

Do not rely solely on button visibility. Backend operations must verify approval.

---

## 24. Required Dashboards

### Agent Dashboard

- Assigned leads
- Activities
- Calls
- Callbacks
- Appointments
- Pipeline
- Sales
- Personal score
- QA
- Compliance
- Targets

### Team Leader Dashboard

- Team pipeline
- Unanswered leads
- Overdue activities
- Callback queue
- Transfer requests
- Agent availability
- Team conversion
- Team performance

### Supervisor Dashboard

- Agent status
- Campaign performance
- Calls and dispositions
- Appointments
- Transfers
- QA reviews
- Compliance findings
- Missed SLAs
- Coaching actions

### Campaign Manager Dashboard

- Lead source
- Lead age
- Contact rate
- Qualification rate
- Stage conversion
- Lost reasons
- Hopper publication
- Call outcomes
- Revenue
- Campaign rating

### Business Unit Director Dashboard

- Pipeline value
- Forecast
- Revenue
- Team performance
- Campaign comparison
- Large opportunities
- Lost opportunities
- QA
- Compliance
- Retention

---

## 25. Automated Tests

Codex must create tests for every business-unit pipeline.

### Pipeline Tests

For each business unit:

1. Create a lead.
2. Confirm default business unit and campaign.
3. Verify required fields.
4. Attempt unauthorized stage skip.
5. Confirm rejection.
6. Complete required fields.
7. Move to next stage.
8. Confirm activity generation.
9. Confirm audit history.
10. Mark won or lost through approved workflow.

### Security Tests

Test:

- Agent cannot access another business unit.
- Agent cannot access another campaign.
- Team leader sees assigned team only.
- Supervisor sees assigned teams only.
- Director sees assigned business unit only.
- QA reviewer cannot modify commercial values.
- Integration administrator cannot access unrestricted customer content.
- Agent cannot export leads.
- Agent cannot delete leads.
- Agent cannot override do-not-call.

### Disposition Tests

Test every disposition for:

- Required fields
- Stage movement
- Activities
- Suppression
- Callbacks
- Approval
- Idempotency
- Audit

### Phone Integration Tests

Test:

- Inbound call
- Outbound call
- Screen pop
- Call logging
- Disposition
- Callback
- Same-campaign transfer
- Cross-campaign rejection
- Recording
- Transcript
- Customer history

---

## 26. Codex Deliverables

Generate:

```text
reports/crm-pipeline-design.md
reports/business-unit-field-matrix.csv
reports/pipeline-stage-matrix.csv
reports/activity-plan-matrix.csv
reports/disposition-matrix.csv
reports/role-permission-matrix.csv
reports/lead-assignment-matrix.csv
reports/approval-control-matrix.csv
reports/crm-security-test-results.md
reports/crm-functional-test-results.md
reports/crm-gap-report.md
reports/crm-production-gate.md
reports/SHA256SUMS
```

The field matrix must include:

- Business unit
- Pipeline
- Field
- Field type
- Required stage
- Required role
- Searchable
- Groupable
- Reportable
- Security classification
- Implementation status
- Test status

---

## 27. Status Classification

For every pipeline, field, role, activity, disposition, and approval rule, assign:

- `PASS`
- `PARTIAL`
- `FAIL`
- `MISSING`
- `BLOCKED`
- `NOT_TESTED`
- `STAGING_READY`
- `PRODUCTION_BLOCKED`

A feature may receive `PASS` only when:

- The implementation exists.
- Backend enforcement exists.
- Functional testing passes.
- Security testing passes where applicable.
- Evidence is recorded.

---

## 28. Definition of Done

The CRM development is complete when:

- Every business unit has a specialized pipeline.
- Every stage has documented entry and exit rules.
- Required fields are enforced by stage.
- Business-unit-specific activities exist.
- Lead assignment respects business unit, campaign, language, skills, availability, and existing ownership.
- Agents have limited, role-appropriate permissions.
- Supervisors can review team calls, pipeline, quality, and callbacks.
- Campaign managers can manage campaign operations without receiving global administration.
- Directors see only their assigned business units.
- Transfer Coordinators have a focused same-campaign queue.
- Closers can complete commercial workflows without changing historical call events.
- QA reviewers can score calls without modifying commercial records.
- Integration administrators can manage integrations without unrestricted customer access.
- Phone events link correctly to CRM.
- Dispositions create the correct activities and stage changes.
- Do-not-call immediately suppresses future automated contact.
- Approval controls protect sensitive operations.
- All pipelines, roles, activities, dispositions, and approvals pass automated tests.
- Production remains disabled until a separate acceptance authorization is issued.

---

## 29. Professional Codex Execution Contract

```text
Read the complete authenticated specification before changing anything.

Operate as the lead implementation engineer across Server A and Server B.

Server A is the application and control plane.
Server B is the telephony and media plane.
Server A orchestrates cross-server work through the approved restricted SSH
identity. Do not require reverse SSH from Server B.

Work autonomously through discovery, reuse analysis, implementation, testing,
remediation, reconciliation, rollback validation, documentation, and evidence.

Mandatory sequence:

1. Authenticate the specification, checksum, ownership, permissions, project
   roots, feature flags, project locks, and fail-closed baseline.

2. Complete a read-only inventory of:
   - repositories and dirty working trees;
   - Odoo version and databases;
   - installed and available modules;
   - Studio fields and automation;
   - models, fields, stages, teams, activities, and security;
   - migrations and schema heads;
   - middleware APIs and contracts;
   - VICIdial campaigns, groups, users, queues, DIDs, dispositions, and mappings;
   - Asterisk configuration and services;
   - n8n workflows and credentials metadata;
   - Keycloak clients, roles, and claims;
   - feature flags, containers, services, monitoring, backups, and evidence.

3. Produce a written reuse plan before mutation.

4. Reuse compatible work. Do not create duplicate fields, models, stages,
   modules, groups, migrations, event contracts, or workflows.

5. Implement shared foundations once and business-unit-specific configuration
   through version-controlled XML data, migrations, and policy records.

6. Enforce business-unit, campaign, department, team, assignment, recording,
   transcript, export, and API security at the backend.

7. Route all operational VICIdial and Asterisk writes through middleware.
   Never connect Odoo or n8n directly to the VICIdial database for operational
   writes.

8. Keep live transfers inside the active campaign. Cross-campaign interest must
   create a secondary opportunity and future callback rather than a live
   cross-campaign transfer.

9. Keep every production feature flag false.

10. Keep every new n8n workflow inactive.

11. Use synthetic customers, users, campaigns, DIDs, endpoints, telephone
    numbers, recordings, and approved sinks.

12. Never expose secrets in source, command lines, stdout, stderr, logs,
    fixtures, exports, traces, evidence, or reports.

13. Correct defects autonomously and rerun all affected tests.

14. Do not mark any feature PASS without functional execution, authoritative
    read-back, a test result, and a checksummed evidence reference.

15. Stop only for:
    - a true external dependency;
    - an authorization boundary;
    - a mandatory rollback trigger; or
    - completion of the approved stage.

Do not activate production dialing, customer communications, predictive
dialing, public DID changes, carrier changes, production lead publication,
production n8n, AI voice, provisioning, or persistent event delivery without a
separate authenticated production authorization.

Required final reporting:

- authenticated specification and source commit/digest;
- discovery and reuse inventory;
- what existed;
- what was reused;
- what was created;
- what changed;
- migrations;
- services and containers changed;
- tests executed;
- statuses for every feature;
- security results;
- reconciliation results;
- rollback results;
- evidence paths and checksums;
- unresolved blockers;
- production recommendation.

The maximum recommendation under this specification is STAGING-ONLY unless a
separate production authorization is authenticated.
```

---

## 30. Formal Production Gate

Production readiness requires every mandatory domain to be `PASS`:

```text
BUSINESS_UNIT_FOUNDATION=PASS
CRM_PIPELINES=PASS
BACKEND_SECURITY=PASS
LEAD_ASSIGNMENT=PASS
DISPOSITIONS_AND_APPROVALS=PASS
MIDDLEWARE_CONTRACTS=PASS
VICIDIAL_PROJECTION=PASS
TELEPHONY_ACCEPTANCE=PASS
ODOO_SYNCHRONIZATION=PASS
N8N_CANARY=PASS
AI_GOVERNANCE=PASS
REPORTING_RECONCILIATION=PASS
MONITORING_AND_ALERTS=PASS
BACKUP_AND_RESTORE=PASS
ROLLBACK_REHEARSAL=PASS
MIGRATION_ACCEPTANCE=PASS
BUSINESS_UAT=PASS
SECURITY_SIGNOFF=PASS
OPERATIONS_SIGNOFF=PASS
```

When any mandatory domain is incomplete:

```text
PRODUCTION_READY=NO
ENABLE_PRODUCTION_TRAFFIC=false
ENABLE_VICIDIAL_WRITES=false
ENABLE_LEAD_PUBLICATION=false
ENABLE_N8N_PRODUCTION=false
ENABLE_LIVE_CALL_CONTROL=false
ENABLE_PROVISIONING=false
```
