# Apiome: Contracts (SLA/API Agreements) - Feature Roadmap

> Smart contract generation and management for API agreements, SLAs, and data sharing between organizations. Contracts turns informal API partnerships into machine-readable, enforceable agreements with integrated billing, consent management, and an immutable audit trail—eliminating spreadsheet-based SLA tracking and manual invoice reconciliation.
>
> **Update (July 3, 2026)**: Epic 5 — Contract Testing & Deploy Gating (Pact) — extends the machine-readable half of a contract with consumer-driven contract testing. Every data-sharing contract can carry a Pact: consumers publish the interactions they depend on, provider builds are verified against them, and verification outcomes bind directly to SLA clauses (strike counters, breaking-change notice periods, deploy gates). A can-i-deploy gate blocks production releases that would break a contracted counterparty, with the same verdict available as a CI exit code. The [contracts mockups](mockups/contracts/README.md) were redesigned at the same time: every screen now renders inside a replica of the live `apiome-ui` shell — the real top platform bar (Home · Control Panel · Designer · Paths, tenant switcher) and the real Control Panel side menu (`DashboardSideNav.tsx`) with the new **Contracts**, **Contract Testing** (Pact), and **Billing & Audit** sections added to it — plus three new screens: `verification.html`, `matrix.html`, and `can-i-deploy.html`.
>
> **Update (July 3, 2026, gap analysis)**: A screen-by-screen walkthrough of the [contracts mockups](mockups/contracts/README.md) against Epics 1–5 surfaced features the mockups render that no issue covers (pricing-model authoring, billing-run orchestration, per-event hash chaining, mediation/settlement, GRC control mapping, runtime gateway enforcement of data-sharing specs, PII classification, stale-pact remediation, environment topology) plus everything the mockup README explicitly parks as "out of scope" (counterparty CRM, tenant policy administration, contract-event webhooks, e-signature providers, smart-contract execution). These are captured as **Epics 6–11** below. Where a gap strengthens an already-filed issue (#957–#980), the improvement is documented as a new issue that *extends* the original rather than mutating the filed issue text.
>
> **Revenue Model**: Per-contract pricing, enterprise legal package
>
> **Tech Stack**: NextJS App Router, Radix UI primitives, REST/OpenAPI 3.1, PostgreSQL with JSONB contract storage, Stripe/payment gateway integration, optional blockchain anchoring, Pact-compatible broker storage for consumer-driven contract testing
>
> **Design Mockups**: [docs/planning/mockups/contracts/](mockups/contracts/) (Epics 1–5, live-shell chrome)
>
> **Last Updated**: July 3, 2026

---

## MVP Definition

- Contract builder with form-based SLA definition (uptime %, latency targets, rate limits)
- Template library with pre-built contract templates (API agreement, data sharing, DPA)
- Schema-based data sharing contract linking Apiome schemas to usage terms
- Basic consent tracking with expiration dates and renewal reminders
- Usage metering pipeline feeding contract compliance checks
- Invoice generation from metered usage with PDF export
- Immutable contract event log with timestamped state transitions
- Contract status dashboard showing active, expiring, and violated contracts
- Pact storage bound to data-sharing contracts with consumer pact capture
- Provider verification workflow replaying contracted interactions, with results recorded as contract events
- Pricing model definition (flat fee, usage-tiered, per-seat) per contract — invoice generation (3.2) cannot produce line items without authored tier rates

---

## Epic 1: Contract Builder & Templates

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 1.1 (#957) | Contract Data Model & CRUD API | Core contract entity with lifecycle states and versioning | `enhancement`, `contracts`, `mvp`, `rest` | Yes |
| 1.2 (#958) | SLA Definition Editor | Visual editor for defining SLA terms (uptime, latency, rate limits) | `enhancement`, `contracts`, `mvp` | Yes |
| 1.3 (#959) | Contract Template Library | Pre-built and custom templates for common agreement types | `enhancement`, `contracts`, `mvp` | Yes |
| 1.4 (#960) | Contract Negotiation Workflow | Multi-party review, comment, and approval flow | `enhancement`, `contracts` | No |
| 1.5 (#961) | Contract Signing & Activation | Digital signature capture and contract activation | `enhancement`, `contracts`, `rest` | No |
| 1.6 (#962) | Contract Dashboard & Lifecycle | Overview of all contracts with status, expiration, and alerts | `enhancement`, `contracts`, `mvp` | Yes |

### Detailed Issue Descriptions

#### 1.1 (#957) — Contract Data Model & CRUD API

The contract data model is the foundation of the Contracts product. A contract entity contains parties (provider and consumer organizations), terms (an array of SLA clauses), effective dates (start, end, renewal date), status (draft, in-review, active, expired, terminated, violated), and version history. Each contract revision is stored as an immutable snapshot, enabling full audit of how terms evolved during negotiation.

The PostgreSQL schema includes a `contracts` table with JSONB columns for `terms` and `party_metadata`, a `contract_versions` table tracking each revision, and a `contract_events` table recording state transitions. The data model supports multi-party contracts where more than two organizations participate, with each party having a role (provider, consumer, observer).

REST endpoints follow standard CRUD: `POST /api/v1/contracts` (create draft), `GET /api/v1/contracts` (list with filters), `GET /api/v1/contracts/{id}` (detail with current terms), `PUT /api/v1/contracts/{id}` (update draft), and `DELETE /api/v1/contracts/{id}` (delete draft only). Status transitions use explicit action endpoints: `POST /api/v1/contracts/{id}/submit` (draft → in-review), `POST /api/v1/contracts/{id}/activate` (in-review → active), `POST /api/v1/contracts/{id}/terminate` (active → terminated). The OpenAPI spec defines discriminated union types for different term types (uptime, latency, rate-limit, data-retention).

**Acceptance Criteria**:
- Contract entity supports multiple parties with roles (provider, consumer, observer)
- Terms are stored as typed JSONB objects with discriminated union types
- Every contract update creates a new version snapshot in `contract_versions`
- State transitions are validated (e.g., cannot activate a draft without submitting first)
- Deletion is only permitted for contracts in draft status
- List endpoint supports filtering by status, party, and date range with cursor pagination

**Part of Epic: Contract Builder & Templates**

---

#### 1.2 (#958) — SLA Definition Editor

The SLA Definition Editor provides a visual interface for defining contract terms without writing JSON. Each SLA clause has a metric type (uptime percentage, response latency, error rate, rate limit, data retention period), a target value, a measurement window (rolling 24h, monthly, quarterly), and a consequence for breach (notification, credit, termination trigger).

The editor page at `/app/contracts/[id]/terms` renders a list of clause cards using Radix `Accordion` for expandable detail. Adding a clause opens a Radix `Dialog` with a Radix `Select` for metric type, number inputs for target and measurement window, and a Radix `RadioGroup` for breach consequence. Each clause displays a human-readable summary (e.g., "99.9% uptime measured monthly; breach triggers 10% service credit").

```
┌─────────────────────────────────────────────────────────────────┐
│  Contract: Acme ↔ Globex Data API          Status: Draft       │
│  [Terms]  [Parties]  [History]  [Preview]                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  SLA Terms                                    [+ Add Clause]   │
│                                                                 │
│  ▼ Uptime Guarantee                                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Metric: Uptime %     Target: 99.95%                     │   │
│  │ Window: Monthly      Breach: 15% service credit         │   │
│  │ Exclusions: Scheduled maintenance (up to 4h/month)      │   │
│  │                                        [Edit] [Remove]  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ▼ Response Latency                                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Metric: p95 Latency  Target: < 200ms                    │   │
│  │ Window: Rolling 24h  Breach: Notification only           │   │
│  │ Measurement: GET endpoints only                          │   │
│  │                                        [Edit] [Remove]  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ► Rate Limits (click to expand)                               │
│  ► Data Retention (click to expand)                            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

The SLA terms are persisted via `PATCH /api/v1/contracts/{id}` updating the `terms` JSONB array. Each term object conforms to a `ContractTerm` schema defined in the OpenAPI spec with required fields: `type`, `metric`, `target`, `window`, and `breach_consequence`. A preview mode renders the terms as a human-readable legal-style document.

**Acceptance Criteria**:
- Editor supports uptime, latency, error rate, rate limit, and data retention term types
- Each clause captures metric, target value, measurement window, and breach consequence
- Human-readable summary is auto-generated from structured term data
- Preview mode renders all terms as a formatted legal-style document
- Terms are validated for logical consistency (e.g., uptime target between 0–100%)
- Clause reordering is supported via drag-and-drop

**Part of Epic: Contract Builder & Templates**

---

#### 1.3 (#959) — Contract Template Library

The Contract Template Library provides pre-built contract templates that accelerate agreement creation. Templates cover common scenarios: Standard API Agreement, Data Sharing Agreement, Data Processing Agreement (DPA), Internal Service Level Agreement, and Partner Integration Agreement. Each template includes pre-populated SLA clauses, boilerplate legal text, and placeholder fields for customization.

The template gallery at `/app/contracts/templates` renders a grid of template cards with Radix `Card`-style layouts. Each card shows the template name, category, number of pre-populated clauses, and a brief description. Selecting a template creates a new contract draft pre-filled with the template's terms and text. Custom templates can be saved from any existing contract via a "Save as Template" action.

Backend endpoints include `GET /api/v1/contracts/templates` (list), `GET /api/v1/contracts/templates/{id}` (detail), `POST /api/v1/contracts/templates` (create custom), and `POST /api/v1/contracts/templates/{id}/instantiate` (create a contract from template). Templates are stored in a `contract_templates` table with a `terms_template` JSONB column and a `legal_text` text column. Organization-specific templates are scoped by tenant ID.

**Acceptance Criteria**:
- Library includes at least 5 pre-built templates covering API, data sharing, DPA, internal SLA, and partner agreements
- Templates pre-populate SLA clauses and legal boilerplate text
- "Save as Template" creates a custom template from any existing contract
- Template instantiation creates a new draft contract with all template fields editable
- Templates support placeholder variables (e.g., `{{provider_name}}`) that are filled during instantiation
- Organization-specific custom templates are visible only to that organization's users

**Part of Epic: Contract Builder & Templates**

---

#### 1.4 (#960) — Contract Negotiation Workflow

The Contract Negotiation Workflow enables multi-party review and approval of contract terms before activation. When a contract is submitted for review, all parties receive notifications and can comment on specific clauses, propose changes (creating a new version), or approve the current version. The contract activates only when all required parties have approved the same version.

The negotiation view at `/app/contracts/[id]/negotiate` renders the contract terms with inline comment threads (similar to document review). Each clause has a comment icon that opens a Radix `Popover` with the comment thread. Proposed changes create a diff view showing the current vs. proposed terms. Party approval status is shown as a checklist at the top of the page.

Backend endpoints include `POST /api/v1/contracts/{id}/comments` (add comment on a clause), `GET /api/v1/contracts/{id}/comments` (list comments), `POST /api/v1/contracts/{id}/propose` (submit a proposed revision), and `POST /api/v1/contracts/{id}/approve` (approve current version). The approval state machine tracks which parties have approved which version, resetting approvals when a new version is proposed.

**Acceptance Criteria**:
- All parties can comment on specific contract clauses with threaded discussions
- Proposed changes create a new contract version and reset all party approvals
- Approval status shows which parties have approved and which version they approved
- Contract cannot be activated until all required parties approve the same version
- Email notifications are sent for new comments, proposed changes, and approval requests
- Negotiation history is preserved showing the full evolution of terms and discussions

**Part of Epic: Contract Builder & Templates**

---

#### 1.5 (#961) — Contract Signing & Activation

Contract Signing & Activation captures digital consent from all parties and transitions the contract from in-review to active status. Each party's authorized representative must digitally sign the contract, which records their identity, timestamp, and IP address. Signing uses a click-to-sign mechanism with a legal acknowledgment checkbox rather than cryptographic digital signatures (enterprise tier may add PKI signing).

The signing page at `/app/contracts/[id]/sign` displays the final contract terms in read-only format with a signature block at the bottom. The signature block includes the signer's name (pre-filled from their profile), title, a legal acknowledgment checkbox, and a "Sign Contract" button. Upon all parties signing, the contract transitions to active and a signed PDF copy is generated and stored.

Backend endpoints include `POST /api/v1/contracts/{id}/sign` (record signature), `GET /api/v1/contracts/{id}/signatures` (list all signatures), and `GET /api/v1/contracts/{id}/signed-document` (download signed PDF). The `contract_signatures` table records `party_id`, `signer_user_id`, `signed_at`, `ip_address`, and `acknowledgment_text`. Activation is automatic when all required signatures are collected.

**Acceptance Criteria**:
- Signing page displays the complete contract in read-only format with all terms
- Signature capture records signer identity, timestamp, and IP address
- Legal acknowledgment checkbox must be checked before signing is permitted
- Contract automatically activates when all required parties have signed
- Signed PDF is generated and stored, downloadable by all parties
- Signature records are immutable and cannot be modified after creation

**Part of Epic: Contract Builder & Templates**

---

#### 1.6 (#962) — Contract Dashboard & Lifecycle

The Contract Dashboard provides a centralized view of all contracts with their current status, key dates, and health indicators. Contracts are displayed in a Radix `Table` with columns for title, parties, status, start date, end date, compliance score, and actions. Status badges use color coding: green (active, compliant), yellow (active, warning), red (violated), gray (draft, expired).

The dashboard at `/app/contracts` supports three views via Radix `Tabs`: "All Contracts" (full list), "Expiring Soon" (contracts expiring within 90 days), and "Violations" (contracts with active SLA breaches). A summary bar at the top shows total active contracts, contracts expiring this month, and current violation count. Each contract row links to its detail page.

The lifecycle engine runs hourly, checking active contracts for expiration (transitioning to expired), SLA compliance (flagging violations), and renewal triggers (sending notifications 90/60/30 days before expiration). Backend endpoints include `GET /api/v1/contracts/dashboard` (summary stats) and `GET /api/v1/contracts?view={all|expiring|violations}` (filtered lists).

**Acceptance Criteria**:
- Dashboard displays all contracts with status badges, parties, dates, and compliance score
- Three tab views filter contracts by all, expiring soon, and violations
- Summary bar shows total active, expiring this month, and violation counts
- Lifecycle engine checks contracts hourly for expiration and compliance
- Renewal notifications are sent at 90, 60, and 30 days before expiration
- Contract status transitions (active → expired, active → violated) are logged as events

**Part of Epic: Contract Builder & Templates**

---

## Epic 2: Data Sharing & Consent Management

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 2.1 (#964) | Schema-Based Data Sharing Contracts | Link Apiome schemas to data sharing agreements | `enhancement`, `contracts`, `mvp`, `rest` | Yes |
| 2.2 (#965) | Consent Tracking Engine | Track and manage consent for data sharing with audit trail | `enhancement`, `contracts`, `mvp`, `rest` | Yes |
| 2.3 (#966) | Expiration & Renewal Management | Automated expiration handling and renewal workflows | `enhancement`, `contracts`, `mvp` | No |
| 2.4 (#967) | Data Usage Monitoring | Track actual data usage against sharing agreement terms | `enhancement`, `contracts`, `rest` | No |
| 2.5 (#968) | Consent Revocation & Data Recall | Handle consent withdrawal and downstream data cleanup | `enhancement`, `contracts` | No |

### Detailed Issue Descriptions

#### 2.1 (#964) — Schema-Based Data Sharing Contracts

Schema-Based Data Sharing Contracts bind Apiome schema definitions to legal data sharing agreements. Instead of describing shared data in prose, the contract directly references specific schema classes and properties, creating a machine-readable specification of exactly what data is shared, in what format, and with what constraints.

The data sharing editor at `/app/contracts/[id]/data-sharing` renders a schema picker that lets users browse their Apiome schemas and select specific classes and properties to include in the sharing agreement. Selected schema elements are displayed in a tree view with checkboxes for individual properties. For each included element, users can set access restrictions (read, write, aggregate-only) and data handling requirements (encryption-at-rest, no-export, retention-limit).

Backend endpoints include `POST /api/v1/contracts/{id}/data-sharing` (define shared schemas), `GET /api/v1/contracts/{id}/data-sharing` (retrieve shared schema definitions), and `PUT /api/v1/contracts/{id}/data-sharing` (update). The `contract_data_sharing` table links `contract_id` to `schema_capture_class_id` with JSONB columns for `included_properties`, `access_level`, and `handling_requirements`. Validation ensures referenced schemas exist and are in a published state.

**Acceptance Criteria**:
- Schema picker browses Apiome schemas and allows property-level selection
- Access restrictions (read, write, aggregate-only) are configurable per schema element
- Data handling requirements (encryption, no-export, retention) are captured per element
- Referenced schemas must be in a published/captured state
- Changes to shared schema definitions create a new contract version
- Machine-readable data sharing spec is exportable as JSON for automated enforcement

**Part of Epic: Data Sharing & Consent Management**

---

#### 2.2 (#965) — Consent Tracking Engine

The Consent Tracking Engine records and manages consent grants from data subjects and organizations for data sharing activities defined in contracts. Each consent record captures the granting party, the contract and specific data sharing clause it covers, the consent timestamp, the expiration date, and the collection method (explicit opt-in, implied, contractual obligation).

Consent records are stored in a `consent_grants` table with fields for `contract_id`, `data_sharing_id`, `granting_party_id`, `granted_at`, `expires_at`, `collection_method`, `evidence_url` (link to signed consent form), and `status` (active, expired, revoked). The consent log is append-only—revocations create new records rather than modifying existing ones.

The consent management page at `/app/contracts/[id]/consent` displays all consent grants for a contract in a Radix `Table` with status indicators. Administrators can record new consent via a Radix `Dialog` form, view consent evidence, and initiate revocation workflows. The REST API provides `POST /api/v1/contracts/{id}/consent` (record consent), `GET /api/v1/contracts/{id}/consent` (list), and `GET /api/v1/contracts/{id}/consent/status` (aggregate consent status for the contract).

**Acceptance Criteria**:
- Consent records capture granting party, timestamp, expiration, collection method, and evidence
- Consent log is append-only with revocations recorded as new entries
- Consent status endpoint returns aggregate status (all consented, partial, missing)
- Expired consent is flagged automatically and triggers renewal notification
- Consent evidence (signed forms, email confirmations) can be attached as URLs
- Consent audit trail is exportable for compliance reporting

**Part of Epic: Data Sharing & Consent Management**

---

#### 2.3 (#966) — Expiration & Renewal Management

Expiration & Renewal Management automates the contract lifecycle around expiration dates. The system tracks three key dates per contract: effective date, expiration date, and renewal decision deadline (a configurable number of days before expiration). As the renewal deadline approaches, the system sends escalating notifications and surfaces the contract in the "Expiring Soon" dashboard view.

Contracts can be configured for auto-renewal (creating a new contract version with the same terms for the next period) or manual renewal (requiring explicit action). The renewal settings page at `/app/contracts/[id]/renewal` uses Radix `RadioGroup` for renewal mode selection and number inputs for notification lead times. When auto-renewal fires, both parties receive a notification with a 14-day opt-out window.

Backend logic runs as a daily scheduled job checking contracts approaching their renewal deadline. Endpoints include `PUT /api/v1/contracts/{id}/renewal-config` (set renewal preferences), `POST /api/v1/contracts/{id}/renew` (manual renewal), and `POST /api/v1/contracts/{id}/opt-out-renewal` (cancel auto-renewal). The `contract_renewals` table tracks renewal history with `old_contract_id`, `new_contract_id`, `renewal_type`, and `renewed_at`.

**Acceptance Criteria**:
- Notifications are sent at configurable intervals before expiration (default: 90, 60, 30, 7 days)
- Auto-renewal creates a new contract version with identical terms for the next period
- Auto-renewal includes a 14-day opt-out window for either party
- Manual renewal surfaces the contract for explicit re-negotiation
- Expired contracts transition to expired status and disable associated data sharing
- Renewal history is tracked with links between old and new contract versions

**Part of Epic: Data Sharing & Consent Management**

---

#### 2.4 (#967) — Data Usage Monitoring

Data Usage Monitoring tracks actual data access patterns against the terms defined in data sharing agreements. The system logs every data access event (API call, export, query) that touches shared data, comparing the access type and volume against the contract's permitted usage. Deviations trigger alerts and are surfaced on the contract compliance dashboard.

The monitoring dashboard at `/app/contracts/[id]/usage` displays time-series charts of data access volume by type (reads, writes, exports) alongside the contract's permitted limits. A compliance indicator shows green (within limits), yellow (approaching limits), or red (exceeded limits). Detailed access logs are available in a paginated Radix `Table` with filters for date range, access type, and accessing party.

```
  Data Access vs. Contract Limits — Acme ↔ Globex

  Reads/day
  5000 ┤
       │                    ╭───── Contract Limit: 4000/day
  4000 ┤··················/·····························
       │               ╱
  3000 ┤            ╱
       │         ╱
  2000 ┤·····╱
       │  ╱
  1000 ┤╱
       │
     0 ┤────┬────┬────┬────┬────┬────┬────┬────
       Mar 1  Mar 5  Mar 10 Mar 15 Mar 20 Mar 25 Mar 30 Apr 1

  [■ Actual Reads]  [--- Contract Limit]  Status: ▲ Warning
```

Backend endpoints include `GET /api/v1/contracts/{id}/usage` (aggregate usage vs. limits), `GET /api/v1/contracts/{id}/usage/logs` (detailed access logs), and `GET /api/v1/contracts/{id}/usage/compliance` (compliance status with deviation details). Usage data is collected via middleware that tags API requests with the originating contract and data sharing clause.

**Acceptance Criteria**:
- Usage tracking captures reads, writes, and exports against shared data per contract
- Time-series charts show actual usage alongside contract limits
- Compliance status transitions between green, yellow, and red based on usage thresholds
- Yellow warning triggers at 80% of contract limit; red at 100%
- Detailed access logs are paginated and filterable by date, type, and party
- Usage data is retained for the duration of the contract plus a configurable archive period

**Part of Epic: Data Sharing & Consent Management**

---

#### 2.5 (#968) — Consent Revocation & Data Recall

Consent Revocation & Data Recall handles the scenario where a party withdraws consent for data sharing. Revoking consent triggers a cascade: the consent record is marked revoked, the data sharing clause is suspended, the consumer party is notified of the revocation and given a deadline to delete or return the shared data, and the contract status may transition to partially-active or terminated depending on remaining valid clauses.

The revocation workflow at `/app/contracts/[id]/consent/revoke` uses a Radix `AlertDialog` to confirm the revocation with a mandatory reason field. After confirmation, a data recall notice is sent to the consumer party with a compliance deadline (configurable, default 30 days). The consumer party must acknowledge the recall and confirm data deletion via `POST /api/v1/contracts/{id}/consent/{consent_id}/confirm-deletion`.

Backend endpoints include `POST /api/v1/contracts/{id}/consent/{consent_id}/revoke` (initiate revocation), `GET /api/v1/contracts/{id}/recall-notices` (list active recall notices), and `POST /api/v1/contracts/{id}/recall-notices/{id}/acknowledge` (consumer acknowledges). Unacknowledged recall notices past their deadline are escalated to enterprise administrators and flagged as compliance violations.

**Acceptance Criteria**:
- Consent revocation records the revoking party, timestamp, and mandatory reason
- Data recall notice is sent to the consumer with a configurable compliance deadline
- Consumer must acknowledge recall and confirm data deletion before the deadline
- Unacknowledged recalls past deadline are escalated as compliance violations
- Partially-revoked contracts transition to partially-active status with remaining valid clauses
- Revocation and recall events are recorded in the immutable audit trail

**Part of Epic: Data Sharing & Consent Management**

---

## Epic 3: Billing & Revenue Integration

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 3.1 (#970) | Usage Metering Pipeline | Collect and aggregate billable usage events from contracts | `enhancement`, `contracts`, `mvp`, `rest` | Yes |
| 3.2 (#971) | Invoice Generation Engine | Generate invoices from metered usage and contract terms | `enhancement`, `contracts`, `mvp` | No |
| 3.3 (#972) | Payment Gateway Integration | Connect to Stripe and other payment processors | `enhancement`, `contracts`, `rest` | Yes |
| 3.4 (#973) | Revenue Sharing Calculator | Compute revenue splits for multi-party contracts | `enhancement`, `contracts` | No |
| 3.5 (#974) | Billing Dashboard & History | Manage invoices, payments, and billing history | `enhancement`, `contracts` | No |

### Detailed Issue Descriptions

#### 3.1 (#970) — Usage Metering Pipeline

The Usage Metering Pipeline collects billable events from API traffic and aggregates them into metering records aligned with contract billing periods. Billable events include API requests (by HTTP method and endpoint), data transfer volume, compute time for transformations, and storage consumption. Events are tagged with the originating contract ID and the specific billable clause.

The pipeline consists of three stages: (1) event ingestion via a lightweight middleware that publishes events to a Redis stream, (2) aggregation workers that consume the stream and compute period totals per contract per metric, and (3) a metering store in PostgreSQL (`billing_meter_records` table) that holds the aggregated values. Aggregation runs every 15 minutes for near-real-time billing visibility.

REST endpoints include `GET /api/v1/contracts/{id}/metering` (current period usage), `GET /api/v1/contracts/{id}/metering/history?from={iso}&to={iso}` (historical metering), and `GET /api/v1/contracts/{id}/metering/estimate` (projected invoice amount based on current usage rate). The OpenAPI spec defines `MeterRecord` with `contract_id`, `metric`, `value`, `unit`, `period_start`, `period_end`, and `tags`.

**Acceptance Criteria**:
- Billable events are captured for API requests, data transfer, compute time, and storage
- Events are tagged with contract ID and billable clause for accurate attribution
- Aggregation completes within 15 minutes of event occurrence
- Metering records are partitioned by billing period for efficient querying
- Projected invoice estimate is accurate within 5% of actual invoice
- Pipeline handles burst traffic of up to 10,000 events per second without data loss

**Part of Epic: Billing & Revenue Integration**

---

#### 3.2 (#971) — Invoice Generation Engine

The Invoice Generation Engine transforms metered usage into formal invoices. At the end of each billing period (monthly by default), the engine calculates line items by applying contract pricing tiers to metered usage, adds applicable taxes and adjustments (credits from SLA breaches), and generates an invoice document. Invoices include a unique invoice number, billing period, itemized charges, subtotal, tax, and total.

The invoice generation process is triggered automatically at period end or manually via `POST /api/v1/contracts/{id}/invoices/generate`. Generated invoices transition through states: draft → issued → paid → void. The invoice detail page at `/app/contracts/[id]/invoices/[invoiceId]` renders the invoice with a print-friendly layout and PDF download option.

Backend endpoints include `GET /api/v1/contracts/{id}/invoices` (list), `GET /api/v1/contracts/{id}/invoices/{invoiceId}` (detail), `POST /api/v1/contracts/{id}/invoices/{invoiceId}/issue` (send to consumer), and `GET /api/v1/contracts/{id}/invoices/{invoiceId}/pdf` (download PDF). The `invoices` table stores `contract_id`, `invoice_number`, `period_start`, `period_end`, `line_items` (JSONB), `subtotal`, `tax`, `total`, `status`, and `issued_at`.

**Acceptance Criteria**:
- Invoices are generated automatically at billing period end with correct line items
- Line items reflect metered usage multiplied by contract pricing tiers
- SLA breach credits are applied as negative line items with reference to the breach event
- Invoice PDF includes all required fields: invoice number, dates, items, subtotal, tax, total
- Invoice status transitions through draft → issued → paid → void with audit logging
- Manual invoice generation is available for ad-hoc billing scenarios

**Part of Epic: Billing & Revenue Integration**

---

#### 3.3 (#972) — Payment Gateway Integration

Payment Gateway Integration connects the invoicing system to external payment processors for automated payment collection. The initial integration targets Stripe, with the architecture designed to support additional gateways (PayPal, wire transfer) via a payment provider abstraction layer. Payment methods are stored securely with the gateway—only tokenized references are kept in Apiome.

The payment configuration page at `/app/contracts/[id]/billing/payment` allows the consumer party to add payment methods via Stripe's embedded payment element (Stripe.js). The provider party configures their Stripe connect account for receiving payments. Automatic payment collection attempts to charge the consumer's payment method when an invoice is issued, with configurable retry logic for failed payments.

Backend endpoints include `POST /api/v1/billing/payment-methods` (add via Stripe token), `GET /api/v1/billing/payment-methods` (list), `POST /api/v1/contracts/{id}/invoices/{invoiceId}/pay` (manual payment), and webhook handler at `/api/v1/billing/webhooks/stripe` for payment status updates. The `payment_transactions` table records `invoice_id`, `gateway`, `gateway_transaction_id`, `amount`, `currency`, `status`, and `processed_at`.

**Acceptance Criteria**:
- Stripe integration supports card and ACH payment methods via Stripe.js
- Payment methods are stored as tokenized references—no raw card data in Apiome
- Automatic payment collection fires when invoices are issued with configurable retry (3 attempts)
- Failed payments trigger notifications to both parties with a manual payment fallback
- Webhook handler processes Stripe events for payment confirmation and failure
- Payment provider abstraction layer supports adding new gateways without modifying core logic

**Part of Epic: Billing & Revenue Integration**

---

#### 3.4 (#973) — Revenue Sharing Calculator

The Revenue Sharing Calculator computes revenue splits for contracts involving multiple parties. Revenue sharing rules are defined per contract, specifying percentage or fixed-amount splits between provider, platform (Apiome), and optional intermediaries. The calculator applies these rules to each invoice, generating a distribution breakdown that shows how invoice proceeds are allocated.

Revenue sharing configuration at `/app/contracts/[id]/revenue-sharing` uses a form with Radix `Slider` components for percentage allocation, ensuring splits total 100%. The distribution breakdown is displayed alongside each invoice, showing the amount allocated to each party. Monthly settlement reports aggregate distributions across all contracts for each party.

Backend endpoints include `PUT /api/v1/contracts/{id}/revenue-sharing` (configure rules), `GET /api/v1/contracts/{id}/invoices/{invoiceId}/distribution` (per-invoice breakdown), and `GET /api/v1/billing/settlements?party_id={id}&period={month}` (monthly settlement report). The `revenue_distributions` table links `invoice_id` to party allocations with amounts and settlement status.

**Acceptance Criteria**:
- Revenue sharing rules support percentage-based and fixed-amount splits
- Split percentages are validated to total exactly 100%
- Per-invoice distribution breakdown is calculated automatically upon invoice generation
- Monthly settlement reports aggregate distributions across all contracts per party
- Distribution changes apply prospectively to future invoices only
- Revenue sharing configuration changes require approval from all contract parties

**Part of Epic: Billing & Revenue Integration**

---

#### 3.5 (#974) — Billing Dashboard & History

The Billing Dashboard provides a unified view of all billing activity across contracts. It displays outstanding invoices, recent payments, revenue trends, and overdue balances. The dashboard serves both provider and consumer perspectives—providers see incoming revenue, consumers see outgoing expenses, and platform administrators see the full picture.

The dashboard at `/app/billing` renders three Radix `Tabs`: "Invoices" (filterable table of all invoices), "Payments" (transaction history), and "Revenue" (time-series revenue chart). Summary cards at the top show total outstanding, total collected this month, and overdue amount. Invoice rows are clickable and link to the invoice detail page.

Backend endpoints include `GET /api/v1/billing/dashboard` (summary statistics), `GET /api/v1/billing/invoices` (cross-contract invoice list), `GET /api/v1/billing/payments` (transaction history), and `GET /api/v1/billing/revenue?from={iso}&to={iso}` (revenue time series). All endpoints support role-based filtering—providers see only their receivables, consumers see only their payables.

**Acceptance Criteria**:
- Dashboard displays outstanding invoices, recent payments, and revenue trends
- Summary cards show total outstanding, collected this month, and overdue amounts
- Invoice list supports filtering by contract, status, date range, and amount
- Revenue chart shows monthly revenue with breakdown by contract
- Role-based filtering ensures providers see receivables and consumers see payables
- Overdue invoices are highlighted with aging indicators (30, 60, 90+ days)

**Part of Epic: Billing & Revenue Integration**

---

## Epic 4: Audit Trail & Compliance

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 4.1 (#976) | Immutable Contract Event Log | Append-only event log recording all contract state changes | `enhancement`, `contracts`, `mvp`, `rest` | Yes |
| 4.2 (#977) | Dispute Resolution Evidence | Collect and present evidence for contract disputes | `enhancement`, `contracts` | No |
| 4.3 (#978) | Compliance Reporting Engine | Generate compliance reports for regulatory requirements | `enhancement`, `contracts`, `rest` | Yes |
| 4.4 (#979) | Blockchain Anchoring (Optional) | Anchor contract hashes to a public blockchain for tamper evidence | `enhancement`, `contracts` | Yes |
| 4.5 (#980) | Audit Export & Integration | Export audit trails in standard formats for external systems | `enhancement`, `contracts`, `rest` | Yes |

### Detailed Issue Descriptions

#### 4.1 (#976) — Immutable Contract Event Log

The Immutable Contract Event Log records every state change, modification, and action taken on a contract in an append-only event store. Events include contract creation, term modifications, status transitions, consent grants and revocations, invoice generation, payments, comments, and approvals. Each event captures the actor (user or system), timestamp, event type, and a payload containing the change details.

The event log is stored in a `contract_events` table with a write-only access pattern—no UPDATE or DELETE operations are permitted at the application layer. The table is partitioned by month for efficient querying. Each event includes a `sequence_number` for ordering and an optional `correlation_id` linking related events (e.g., all events from a single negotiation session).

The event timeline at `/app/contracts/[id]/history` renders events in a chronological list with type-specific formatting. Status transitions show before/after states, term modifications show diffs, and financial events show amounts. Filters allow narrowing by event type, actor, and date range. REST endpoints include `GET /api/v1/contracts/{id}/events` (paginated list) and `GET /api/v1/contracts/{id}/events/{eventId}` (detail with full payload).

**Acceptance Criteria**:
- All contract state changes are recorded as immutable events with actor and timestamp
- Event table enforces append-only access—no UPDATE or DELETE at the application layer
- Events include sequence numbers for deterministic ordering
- Timeline view renders events with type-specific formatting (diffs, state changes, amounts)
- Event log is filterable by event type, actor, and date range
- Correlation IDs link related events for session-level auditing

**Part of Epic: Audit Trail & Compliance**

---

#### 4.2 (#977) — Dispute Resolution Evidence

Dispute Resolution Evidence collects and organizes contract-related evidence into a structured case file when a dispute is raised. A dispute case bundles relevant events, contract versions, consent records, usage data, SLA breach reports, and communication history into a single reviewable package. This package serves as the evidentiary basis for resolving disagreements between parties.

The dispute management page at `/app/contracts/[id]/disputes` lists open and resolved disputes. Creating a new dispute via a Radix `Dialog` captures the dispute reason, affected clauses, and desired outcome. The system automatically assembles the evidence package by querying related events, usage records, and contract versions. Both parties can add supplementary evidence (file uploads, external links) to the case.

Backend endpoints include `POST /api/v1/contracts/{id}/disputes` (open dispute), `GET /api/v1/contracts/{id}/disputes` (list), `GET /api/v1/contracts/{id}/disputes/{disputeId}/evidence` (evidence package), and `POST /api/v1/contracts/{id}/disputes/{disputeId}/resolve` (record resolution). The `contract_disputes` table tracks `contract_id`, `raised_by`, `reason`, `affected_clauses`, `status`, and `resolution`. Evidence packages are generated as downloadable ZIP files.

**Acceptance Criteria**:
- Dispute creation captures reason, affected clauses, and desired outcome
- Evidence package is auto-assembled from related events, usage, and contract versions
- Both parties can add supplementary evidence (files, links) to the case
- Evidence package is downloadable as a ZIP containing all relevant documents
- Dispute resolution is recorded with outcome and agreed-upon actions
- Dispute timeline shows all activities from opening to resolution

**Part of Epic: Audit Trail & Compliance**

---

#### 4.3 (#978) — Compliance Reporting Engine

The Compliance Reporting Engine generates reports demonstrating contractual compliance for regulatory requirements. Reports cover data processing agreements (GDPR Article 28 compliance), SLA performance (uptime and latency over reporting period), consent management status (active consents, revocations, expirations), and data handling adherence (encryption, retention, access controls).

The reporting page at `/app/contracts/compliance/reports` allows selecting a report type, target contracts, and reporting period. Reports are generated asynchronously—a progress indicator shows generation status. Completed reports are available for download in PDF and CSV formats. Scheduled reports can be configured to run monthly and be delivered to specified email addresses.

Backend endpoints include `POST /api/v1/contracts/compliance/reports` (generate), `GET /api/v1/contracts/compliance/reports` (list generated reports), `GET /api/v1/contracts/compliance/reports/{id}` (status and download), and `PUT /api/v1/contracts/compliance/reports/schedule` (configure scheduled reports). The report generation job queries the event log, consent store, usage metrics, and SLA breach records to compile the report data.

**Acceptance Criteria**:
- Report types include GDPR compliance, SLA performance, consent status, and data handling
- Reports are generated asynchronously with progress tracking
- Completed reports are downloadable in PDF and CSV formats
- Scheduled reports run monthly and are delivered to configured email addresses
- Reports reference specific contract clauses and include supporting evidence
- Report generation completes within 5 minutes for contracts with up to 1 year of history

**Part of Epic: Audit Trail & Compliance**

---

#### 4.4 (#979) — Blockchain Anchoring (Optional)

Blockchain Anchoring provides optional tamper-evidence for contract events by periodically anchoring event hashes to a public blockchain. Rather than storing full contract data on-chain, the system computes a Merkle root of recent events and publishes it as a transaction to Ethereum (or a configurable chain). This allows any party to verify that the event log has not been retroactively altered.

The anchoring configuration at `/app/enterprise/settings/blockchain` uses Radix `Switch` to enable/disable anchoring and a Radix `Select` for chain selection. Anchoring runs on a configurable schedule (default: daily). Each anchoring transaction records the Merkle root, event range, and transaction hash. A verification endpoint allows recalculating the Merkle root from stored events and comparing against the on-chain anchor.

Backend endpoints include `POST /api/v1/contracts/audit/anchor` (trigger manual anchoring), `GET /api/v1/contracts/audit/anchors` (list anchoring records), and `POST /api/v1/contracts/audit/verify` (verify event integrity against on-chain anchor). The `audit_anchors` table stores `merkle_root`, `event_range_start`, `event_range_end`, `chain`, `transaction_hash`, and `anchored_at`.

**Acceptance Criteria**:
- Merkle root is computed from contract events within the anchoring window
- Anchoring transaction is published to the configured blockchain on schedule
- Verification endpoint recalculates Merkle root and compares against on-chain value
- Anchoring is optional and does not affect core contract functionality when disabled
- Anchoring records include chain name, transaction hash, and event range for traceability
- Gas costs for anchoring transactions are estimated and displayed before confirmation

**Part of Epic: Audit Trail & Compliance**

---

#### 4.5 (#980) — Audit Export & Integration

Audit Export & Integration enables exporting contract audit trails in standard formats for ingestion by external compliance, SIEM, and GRC systems. Supported export formats include JSON Lines (for log aggregation), CSV (for spreadsheet analysis), and SARIF (for security-focused tooling). Exports can be one-time downloads or continuous streams via webhook delivery.

The export configuration page at `/app/contracts/audit/export` allows setting up export profiles with target format, event type filters, and delivery method (download, webhook, S3 bucket). Webhook delivery sends batched events to a configured URL with HMAC signature verification. S3 delivery writes event files to a specified bucket with configurable prefix and partitioning.

Backend endpoints include `POST /api/v1/contracts/audit/export` (one-time export), `POST /api/v1/contracts/audit/export/profiles` (create continuous export profile), `GET /api/v1/contracts/audit/export/profiles` (list), and `DELETE /api/v1/contracts/audit/export/profiles/{id}` (stop continuous export). The export job supports pagination for large event sets and includes a `Content-Disposition` header for browser downloads.

**Acceptance Criteria**:
- Export formats include JSON Lines, CSV, and SARIF
- One-time exports support date range and event type filtering
- Continuous export profiles deliver events via webhook with HMAC signature
- S3 delivery writes partitioned files with configurable prefix
- Exports include all event metadata (actor, timestamp, type, payload)
- Large exports are paginated and streamed to prevent memory exhaustion

**Part of Epic: Audit Trail & Compliance**

---

## Epic 5 (#4239): Contract Testing & Deploy Gating (Pact)

Consumer-driven contract testing bound to legal contracts. Where Epics 1–4 make the *terms* of an agreement machine-readable, Epic 5 makes the *interface* machine-verifiable: each data-sharing contract can carry a Pact describing exactly which interactions the consumer depends on, providers are verified against those interactions on every build, and the outcomes feed the same SLA clauses, event log, and dispute machinery the rest of the product uses. This epic shares broker infrastructure with the Testing & QA roadmap's Epic 6 (#1914, `FUTURE_FEATURE_ROADMAP_TESTING.md`); the issues below cover the contract-binding layer, not a second broker.

### Summary Table

| #   | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|-----|-------|---------|--------|----------|-----|------------|------------------|
| 5.1 (#4240) | Pact Data Model & Contract Binding | Store pacts/pacticipants and bind each pact to a data-sharing contract clause | `enhancement`, `contracts`, `pact`, `mvp`, `rest` | Yes | Y | M | apiome-rest, apiome-db |
| 5.2 (#4241) | Consumer Pact Capture & Publication | CLI/CI publication of consumer pacts scoped to a contract | `enhancement`, `contracts`, `pact`, `mvp`, `rest` | Yes | Y | M | apiome-cli, apiome-rest |
| 5.3 (#4242) | Provider Verification & SLA Clause Binding | Replay contracted interactions against provider builds; failures accrue SLA strikes | `enhancement`, `contracts`, `pact`, `mvp` | No | Y | L | apiome-rest, apiome-ui |
| 5.4 (#4243) | Contract Compatibility Matrix | Consumer × provider verdict grid across all contracted pairs | `enhancement`, `contracts`, `pact` | Yes | N | M | apiome-ui, apiome-rest |
| 5.5 (#4244) | Can-I-Deploy Contract Gate | Release verdict combining pact verdicts, contract clauses, and consent status | `enhancement`, `contracts`, `pact` | No | N | L | apiome-rest, apiome-ui |
| 5.6 (#4245) | CI Integration & Gate Events | CLI exit-code parity, GitHub Actions reference workflow, gate webhooks | `enhancement`, `contracts`, `pact`, `rest` | Yes | N | S | apiome-cli, apiome-rest |

### Detailed Issue Descriptions

#### 5.1 (#4240) — Pact Data Model & Contract Binding

**Problem Statement**: Data-sharing contracts (2.1) describe *what* data is shared as schema references, but nothing verifies that the provider's running API actually honours the shape consumers depend on. Prose clauses can't catch a removed field.

**Solution/Scope**: Introduce pact storage bound to contracts. Tables: `pacticipants` (consumer/provider systems, keyed to contract parties), `pact_versions` (immutable pact documents as JSONB, content-addressed), and `contract_pacts` linking `pact_version_id` to `contract_id` and the specific data-sharing clause it enforces (source: Pact Broker's pacticipant/version model, adapted to tenant + contract scoping). REST endpoints: `PUT /api/v1/contracts/{id}/pacts/{consumer}/{version}` (publish), `GET /api/v1/contracts/{id}/pacts` (list), `GET /api/v1/contracts/{id}/pacts/{consumer}/latest` (fetch for verification). Pacts are immutable — republishing identical content is a no-op; changed content creates a new version and emits a `pact.published` contract event.

**Acceptance Criteria**:
- Pacticipants map to contract parties; a pact cannot be attached to a contract its consumer is not party to
- Pact versions are content-addressed and immutable; identical republish is idempotent
- Each pact binds to a specific data-sharing clause (e.g. DS-2.1) for enforcement attribution
- `pact.published` events are recorded in the immutable contract event log (4.1)
- Contracts without pacts continue to work (prose-only enforcement fallback)

**Parallelism/Dependencies**: Depends on 1.1 (contract model) and 2.1 (data-sharing clauses). Parallel with 5.2.

**Technical Stack**: PostgreSQL JSONB, REST/OpenAPI 3.1, Pact Specification v3/v4 document format.

**Part of Epic: Contract Testing & Deploy Gating (Pact)**

---

#### 5.2 (#4241) — Consumer Pact Capture & Publication

**Problem Statement**: Consumers already generate pacts in their test suites (pact-js, pact-jvm, etc.), but there is no path from a consumer's CI to the counterparty's contract in Apiome.

**Solution/Scope**: `apiome contracts publish-pact --contract <id> --consumer <name> --version <ver> ./pacts/*.json` uploads pact files against the contract, authenticating with a tenant API key scoped to the consumer party. Publication validates that every interaction in the pact touches only schema elements the data-sharing clause grants (access-level check: a pact asserting a `write` interaction against a `read`-only clause is rejected). The UI surfaces published pacts on the data-sharing screen (`data-sharing.html` mockup) with per-consumer coverage.

**Acceptance Criteria**:
- CLI publishes pact files against a contract with consumer-party API key auth
- Interactions are validated against the clause's access level and included properties; violations reject the publish with a clause reference
- Branch/tag metadata (e.g. `main`, environment tags) is recorded per pact version
- Publication triggers provider verification (5.3) via event
- Per-contract pact coverage is visible in the UI (consumers with/without pacts)

**Parallelism/Dependencies**: Depends on 5.1 for storage. Parallel with 5.3 UI work.

**Technical Stack**: apiome-cli (Node), REST, Pact Specification formats.

**Part of Epic: Contract Testing & Deploy Gating (Pact)**

---

#### 5.3 (#4242) — Provider Verification & SLA Clause Binding

**Problem Statement**: A pact is only useful if the provider is verified against it — and in a *contracted* relationship, a failed verification is not just a red build, it is a potential breach of terms with financial consequences.

**Solution/Scope**: Verification runs replay every contracted consumer's interactions against a provider build (staging URL or CI-launched instance), triggered by schema publish, pact publication, or nightly schedule. The verification screen (`verification.html` mockup) shows per-consumer pass/fail, a terminal-styled replay log with per-interaction verdicts referencing the violated clause, recent runs, and the pact ↔ clause binding table. Failed runs emit `verification.failed` events (4.1) and increment clause strike counters — e.g. a schema-fidelity clause breaching at 3 failed runs per 7-day window triggers its configured consequence (service credit, notification) through the existing SLA machinery (1.2).

```
  consumer pact ──▶ verification run ──▶ pass ──▶ matrix cell green
                        │
                        └─▶ fail ──▶ verification.failed event (4.1)
                                        │
                                        ├─▶ clause strike counter (1.2)
                                        │      └─▶ threshold ──▶ breach ──▶ credit / notify
                                        └─▶ dispute evidence pack (4.2)
```

**Acceptance Criteria**:
- Verification replays all contracted consumers' interactions against a provider build
- Runs are triggered by schema publish, pact publish, and a nightly schedule
- Per-interaction failures reference the violated contract clause in the log output
- Failed runs emit immutable `verification.failed` events and increment clause strike counters
- Strike thresholds trigger the clause's configured breach consequence via existing SLA machinery
- Verification evidence is automatically attachable to dispute cases (4.2)

**Parallelism/Dependencies**: Depends on 5.1 and 5.2; integrates with 1.2 (SLA clauses), 4.1 (event log), 4.2 (disputes).

**Technical Stack**: pact-verifier-compatible replay engine, worker queue, NextJS UI, REST.

**Part of Epic: Contract Testing & Deploy Gating (Pact)**

---

#### 5.4 (#4243) — Contract Compatibility Matrix

**Problem Statement**: With many counterparties and many consumer systems per contract, "is everything verified?" has no single answer surface.

**Solution/Scope**: A consumer × provider grid (`matrix.html` mockup) where every cell is the latest verification verdict for that contracted pair: emerald (verified), rose (failing), amber (stale &gt; 72 h), cyan (new pact, unverified), slate (no contract between the pair). Cells link to the underlying verification run. Companion panels list failing pairs (with clause strike status) and per-contract pact coverage. Backend: `GET /api/v1/contracts/matrix?consumer=&provider=&contract=` returning the verdict grid with cursor pagination for large tenants.

**Acceptance Criteria**:
- Matrix renders latest verdict per contracted consumer × provider pair with the five-state colour convention
- Cells link to the underlying verification run detail
- Failing-pairs panel shows clause strike status and links to disputes where attached
- Coverage panel shows consumers with/without pacts per active data-sharing contract
- Stale threshold (default 72 h) is configurable per tenant

**Parallelism/Dependencies**: Depends on 5.3 for verdict data. Parallel with 5.5.

**Technical Stack**: NextJS UI, REST aggregate endpoint.

**Part of Epic: Contract Testing & Deploy Gating (Pact)**

---

#### 5.5 (#4244) — Can-I-Deploy Contract Gate

**Problem Statement**: A provider can pass its own tests and still break a *contracted* counterparty in production — or violate a breaking-change notice clause — with billing and legal consequences the deploy pipeline knows nothing about.

**Solution/Scope**: A release gate (`can-i-deploy.html` mockup) answering "can `provider@version` deploy to `environment`?" by combining: (1) latest verification verdicts for every contracted consumer in that environment, (2) contract-level gates — breaking-change notice periods (removed fields require a notice event N days prior), and (3) consent status (a data-sharing clause with revoked consent blocks deploys that would continue serving that data). Verdicts render as a gradient banner (rose = blocked, emerald = safe) with a per-check table, unblock guidance, and are recorded as immutable `deploy.gate.blocked` / `deploy.gate.passed` events visible to all contract parties. Endpoint: `GET /api/v1/contracts/can-i-deploy?pacticipant=&version=&environment=`.

```
  candidate build ──▶ gate ──▶ pact verdicts (all contracted consumers)
                        ├────▶ clause gates (notice period, deploy-gate clause)
                        ├────▶ consent status (2.2 / 2.5)
                        └────▶ verdict ──▶ event log ──▶ CI exit code (5.6)
```

**Acceptance Criteria**:
- Gate combines pact verdicts, breaking-change notice clauses, and consent status into one verdict
- Blocked verdicts enumerate each blocker with contract, clause, and evidence links
- Verdicts are recorded as immutable contract events visible to all parties
- Unblock guidance covers: fix the change, negotiate an amendment (1.4), or wait for consumer release
- Environment model tracks which consumer versions are deployed where

**Parallelism/Dependencies**: Depends on 5.3 verdicts and 5.4's environment/version data; consumes 2.2/2.5 consent state.

**Technical Stack**: REST, NextJS UI, environment/version tracking tables.

**Part of Epic: Contract Testing & Deploy Gating (Pact)**

---

#### 5.6 (#4245) — CI Integration & Gate Events

**Problem Statement**: The gate only prevents incidents if pipelines consult it; parties also need to *hear about* verification failures and gate verdicts without polling.

**Solution/Scope**: `apiome contracts can-i-deploy --pacticipant <name> --version <ver> --to-environment <env>` returns the same verdict as the UI with exit code 0/1 for pipeline gating, plus a reference GitHub Actions workflow (publish pacts on consumer CI, verify + gate on provider CI). Gate and verification events fan out through webhooks (HMAC-signed, reusing the audit export delivery layer from 4.5) so counterparties' systems are notified of `verification.failed`, `deploy.gate.blocked`, and `pact.published` events.

**Acceptance Criteria**:
- CLI verdict matches the UI verdict exactly, with exit code 0 (safe) / 1 (blocked)
- Reference GitHub Actions workflow covers consumer publish and provider verify + gate
- Webhooks deliver verification and gate events with HMAC signatures and retry
- Webhook payloads include contract ID, clause references, and evidence URLs

**Parallelism/Dependencies**: Depends on 5.5 for the verdict; webhook delivery parallel with 5.4. Reuses 4.5 delivery infrastructure.

**Technical Stack**: apiome-cli, GitHub Actions YAML, webhook workers.

**Part of Epic: Contract Testing & Deploy Gating (Pact)**

---

## Epic 6 (#4246): Contract Authoring & Lifecycle Enhancements

Improvements to the Epic 1 surfaces identified by the mockup gap analysis: the `terms-editor.html`, `dashboard.html`, `templates.html`, `negotiate.html`, and `sign.html` mockups all render richer scope than issues 1.2–1.6 specify. Each issue below extends a filed issue without changing its text.

### Summary Table

| #   | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|-----|-------|---------|--------|----------|-----|------------|------------------|
| 6.1 (#4247) | Expanded Clause Catalog & Tiered Breach Consequences | Maintenance-window, support-response, and custom clause types; graduated credit tiers; structured sub-fields | `enhancement`, `contracts`, `rest` | Yes | N | M | apiome-ui, apiome-rest, apiome-db |
| 6.2 (#4248) | Dashboard Analytics, Search & Activity Feed | Drafts view, compliance-score definition, MRR column, lifecycle chart, renewals queue, events feed, search/sort/bulk actions | `enhancement`, `contracts` | Yes | N | M | apiome-ui, apiome-rest |
| 6.3 (#4249) | Template Governance & Analytics | Import/authoring, facets & search, usage analytics, template versioning, compliance-tag governance | `enhancement`, `contracts` | Yes | N | M | apiome-ui, apiome-rest, apiome-db |
| 6.4 (#4250) | Negotiation Counter-Proposals & Thread Resolution | Counter-propose path, comment resolve/archive lifecycle, revisions inbox, compare-versions view | `enhancement`, `contracts` | Yes | N | M | apiome-ui, apiome-rest |
| 6.5 (#4251) | Signing Integrity & Activation Tracker | SHA-256 document-hash binding, activation stepper, draft PDF, signer title capture | `enhancement`, `contracts`, `rest` | Yes | N | S | apiome-ui, apiome-rest |
| 6.6 (#4252) | Internal (Team-to-Team) Contract Mode | First-class internal SLA contracts: no billing, rolling term, same-tenant parties | `enhancement`, `contracts` | Yes | N | M | apiome-rest, apiome-ui, apiome-db |

### Detailed Issue Descriptions

#### 6.1 (#4247) — Expanded Clause Catalog & Tiered Breach Consequences

**Problem Statement**: Issue 1.2 (#958) enumerates five clause types with a scalar `breach_consequence`, but the `terms-editor.html` mockup ships seven clause types plus a custom escape hatch, graduated credit tiers, and structured sub-fields the schema cannot express — a removed field the editor renders is a clause the API cannot store.

**Solution/Scope**: Extend the `ContractTerm` discriminated union with **Maintenance Windows** (calendar schedule, notice period, counted against the uptime exclusion budget), **Support Response** (per-priority response targets, e.g. P0 < 30 min 24×7), and a **Custom term** type (free-form metric with optional structured target). Replace the scalar `breach_consequence` with a shape supporting `tiers[]` (magnitude-scaled consequences: Tier 1/2/3 breach ranges → 5% / 15% / 25% credit, as the mockup's live JSONB panel shows). Add per-clause structured sub-fields: `exclusions` (e.g. scheduled maintenance ≤ 4 h/month), rate-limit `burst` (sustained + burst-within-window), `measurement_scope` (e.g. "GET endpoints only"), and a `required` flag distinguishing mandatory from optional clauses. Ship the editor's **raw `terms[]` JSONB inspector** (read-only, with Copy) and the **validation side panel** that mixes logical-consistency checks with negotiation state (e.g. "1 unresolved comment on §2" cross-referenced from 1.4).

**Acceptance Criteria**:
- Maintenance-window, support-response, and custom clause types round-trip through the editor, API, and legal-prose preview
- `breach_consequence` supports an ordered `tiers[]` array; tier boundaries are validated as non-overlapping and credits feed 3.2's breach-credit line items
- `exclusions`, `burst`, `measurement_scope`, and `required` persist per clause and render in the human-readable summary
- The JSONB inspector always reflects the saved terms and updates live as clauses are edited
- The validation panel surfaces range violations, missing dates, and unresolved negotiation comments with links to the offending clause

**Parallelism/Dependencies**: Extends 1.2 (#958); tier credits integrate with 3.2 (#971). Parallel with all other Epic 6 issues.

**Technical Stack**: NextJS/Radix editor components, OpenAPI discriminated unions, PostgreSQL JSONB.

**Part of Epic: Contract Authoring & Lifecycle Enhancements**

---

#### 6.2 (#4248) — Dashboard Analytics, Search & Activity Feed

**Problem Statement**: Issue 1.6 (#962) specifies three tab views and a static count summary, but `dashboard.html` renders a Drafts tab, an MRR KPI with month-over-month deltas, a per-row `Value · MRR` column, a 30-day lifecycle-activity area chart, a renewals queue with day-countdown chips, an SLA-violations drill-down with credit math, and a cross-contract recent-events feed — none of which any issue owns.

**Solution/Scope**: Add a fourth **Drafts** tab; define the **compliance score** derivation (0–100% per contract, computed from clause breach counts weighted by severity over the current window — the number the row bar renders); add the **`Value · MRR` column** and MRR KPI card fed by Epic 3 metering (with `internal` / `tbd` fallbacks for unbilled contracts); add the **lifecycle activity chart** (activated / in-review / violations series, 30 d); embed the **renewals queue** (per-contract countdown, auto-renew vs. manual badges, sourced from 2.3) and the **active-violations panel** (target vs. actual, breach consequence, credit amounts, `disputed` state from 4.2); stream the **recent contract events feed** from 4.1. Add free-text search, sort controls (default "sorted by activity"), saved filters, numbered pagination, and bulk row actions (bulk export, bulk renewal decision).

**Acceptance Criteria**:
- Drafts tab lists draft contracts with counts in the tab strip; KPI cards show trend deltas (e.g. "+4 this quarter", "+6.2% vs. prior month")
- Compliance score derivation is documented and deterministic; identical inputs produce identical scores via a shared scoring service
- MRR KPI and per-row value column reconcile with Epic 3 metering within the current billing period
- Renewals queue, violations panel, and events feed link through to their owning screens (renewal config, violation detail, event log)
- Search, sort, saved filters, and pagination compose; bulk actions operate on the filtered selection
- Row micro-data renders: contract version tag, expiry countdown, `∞ rolling` for internal contracts, multi-party and regulation annotations, and a `Warning` status distinct from `Active`/`Violated`

**Parallelism/Dependencies**: Extends 1.6 (#962); consumes 4.1 events, 2.3 renewal state, 2.4 violation data, and 8.6 revenue figures (degrades gracefully before 8.6 lands). Parallel within Epic 6.

**Technical Stack**: NextJS, Radix Tabs/Table, REST aggregate endpoints, shared scoring service.

**Part of Epic: Contract Authoring & Lifecycle Enhancements**

---

#### 6.3 (#4249) — Template Governance & Analytics

**Problem Statement**: Issue 1.3 (#959) covers pre-built templates and "Save as Template" only, while `templates.html` shows Import and New-template entry points, category/scope facets, search, per-template instance counts with a "Most used" badge, template version identifiers (`tpl_dpa_gdpr_v4`), edit attribution, and compliance tags (`SCC v2021`, `GDPR Art. 28`) — template lifecycle is unspecified.

**Solution/Scope**: Add **template import** (upload JSON/markdown template files) and **blank authoring**; **category chips** (API agreement, Data sharing, DPA/GDPR, Internal SLA, Partner) with **Platform vs. Organization scope toggles** and free-text search; **usage analytics** (instance counts per template, "Most used" popularity badge); **template versioning** with edit attribution (author, last-edit timestamp) and extended metadata chips (placeholder count, word count, consent-required, billing mode, party count). Add a **governance flow**: when a template gains a new version (e.g. updated SCC revision), contracts instantiated from the outdated version are flagged and their owners notified with a diff of the template change.

**Acceptance Criteria**:
- Templates can be imported from file and authored from scratch, in addition to save-as-template
- Gallery supports category facets, platform/organization scope filtering, and search
- Instance counts are tracked per template version; the most-instantiated template carries the popularity badge
- Template versions are immutable with author and timestamp attribution; instantiation records the exact template version used
- Outdated-template notifications list affected contracts and link to the template version diff
- Compliance tags (regulation, SCC revision) are structured metadata, filterable in the gallery

**Parallelism/Dependencies**: Extends 1.3 (#959). Notification delivery reuses 11.3 when available. Parallel within Epic 6.

**Technical Stack**: NextJS, PostgreSQL (`contract_templates` versioning columns), REST.

**Part of Epic: Contract Authoring & Lifecycle Enhancements**

---

#### 6.4 (#4250) — Negotiation Counter-Proposals & Thread Resolution

**Problem Statement**: Issue 1.4 (#960) defines comment / propose / approve, but `negotiate.html` renders a **Counter-propose** action on revisions, comment threads with a resolve/archive lifecycle ("resolved by m.lee", "Discussion archived · 4 messages"), a Comments-vs-Revisions right-rail with per-revision Accept, and a header Compare-versions entry point — the negotiation state machine is thinner than the screen.

**Solution/Scope**: Add a **counter-proposal** path: a party responding to a proposed revision submits an alternative revision linked to the original, superseding it in the revisions inbox; approvals reset per the existing 1.4 rules. Add a **thread lifecycle** (open → resolved → archived) with resolver attribution; unresolved-thread counts surface in the header and in 6.1's validation panel. Ship the **revisions inbox** (right-rail tab listing pending revisions with per-item Accept / Counter-propose) and a **compare-versions** view for any two contract versions.

**Acceptance Criteria**:
- Counter-proposals link to and supersede the revision they answer; the negotiation history renders the proposal chain
- Threads support resolve (with attribution) and archive; unresolved counts appear in the header ("4 open comments · 2 proposed revisions")
- Revisions inbox lists pending revisions with accept and counter-propose actions per item
- Compare-versions renders a term-level diff between any two versions using the negotiation diff colour convention
- All counter-proposal and resolution actions emit 4.1 events

**Parallelism/Dependencies**: Extends 1.4 (#960); feeds unresolved-comment state to 6.1. Parallel within Epic 6.

**Technical Stack**: NextJS, Radix Popover/Tabs, REST, contract version diffing.

**Part of Epic: Contract Authoring & Lifecycle Enhancements**

---

#### 6.5 (#4251) — Signing Integrity & Activation Tracker

**Problem Statement**: Issue 1.5 (#961) is deliberately non-cryptographic click-to-sign, yet `sign.html` surfaces a SHA-256 document hash in the read-only header, the acknowledgment text, and a Document-hash column in the signature trail — plus an activation-progress stepper, a pre-signing draft-PDF download, and signer title/role capture that 1.5 omits.

**Solution/Scope**: Bind each signature to the **SHA-256 hash of the exact contract version signed**: the hash renders on the signing page, is embedded in the acknowledgment text, and is stored per signature (`contract_signatures.document_hash`), making "which version did they sign" cryptographically answerable without full PKI. Add the **activation-progress tracker** (Approved → counterparty signed → your turn → auto-activate), **Download draft PDF** before signing, **signer title/role** capture, and the rendered **signature preview** glyph.

**Acceptance Criteria**:
- Document hash is computed over the canonical serialized contract version and recorded immutably per signature
- A signature whose stored hash does not match the recomputed version hash is flagged in the signature trail
- Activation tracker reflects live party state and shows the auto-activation step
- Draft PDF is downloadable pre-signing; signed PDF (existing 1.5) embeds the document hash
- Signature trail table includes Party, Signer, Role/Title, Captured at, IP, and Document hash columns, with an "awaiting" row state for unsigned parties

**Parallelism/Dependencies**: Extends 1.5 (#961); hash chaining aligns with 9.1's conventions. Provider hand-off (DocuSign et al.) is 11.4, not this issue. Parallel within Epic 6.

**Technical Stack**: SHA-256 canonical hashing, PDF generation, NextJS.

**Part of Epic: Contract Authoring & Lifecycle Enhancements**

---

#### 6.6 (#4252) — Internal (Team-to-Team) Contract Mode

**Problem Statement**: The dashboard mockup shows `Acme Internal SLA · Customer 360` with an `∞ rolling` term and `internal` in the value column, and the template gallery has an "Internal SLA · no billing" template — but the roadmap models every contract as a cross-organization provider↔consumer agreement with billing.

**Solution/Scope**: Make internal contracts a first-class mode: both parties resolve to teams within the same tenant, billing is disabled (metering optional, for chargeback visibility only), the term supports **rolling/indefinite** (`∞`) with review checkpoints instead of hard expiry, signing collapses to team-lead acknowledgment, and SLA breaches route to internal notification/escalation rather than credits. Internal contracts share the same clause model (1.2/6.1), event log (4.1), and verification (Epic 5) so platform teams get deploy gating between internal services.

**Acceptance Criteria**:
- Contract creation offers internal mode; parties are teams of the current tenant with no counterparty organization required
- Rolling terms render as `∞ rolling` with configurable review-checkpoint reminders in place of expiration notifications
- Billing surfaces (invoices, payment, revenue share) are hidden/disabled for internal contracts; optional chargeback metering is view-only
- Breach consequences are restricted to notification/escalation types; credit consequences are rejected at validation
- Internal contracts participate fully in the event log, dashboard, and pact verification/deploy gating

**Parallelism/Dependencies**: Depends on 1.1 (#957) party model. Parallel within Epic 6.

**Technical Stack**: PostgreSQL party-role extension, NextJS, REST.

**Part of Epic: Contract Authoring & Lifecycle Enhancements**

---

## Epic 7 (#4253): Data Sharing Enforcement & Intelligence

Extensions to Epic 2 surfaced by `data-sharing.html`, `consent.html`, and `usage.html`: the mockups claim gateway-enforced sharing specs, PII-aware handling, aggregate-expression grants, lineage-backed recalls, quota economics, and renewal intelligence that issues 2.1–2.5 do not cover.

### Summary Table

| #   | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|-----|-------|---------|--------|----------|-----|------------|------------------|
| 7.1 (#4254) | PII Classification & Pseudonymisation | Auto-tag PII properties; pseudonymise and purge-on-end handling requirements | `enhancement`, `contracts`, `rest` | Yes | N | M | apiome-rest, apiome-ui, apiome-db |
| 7.2 (#4255) | Aggregate Query Definition Builder | Define permitted aggregate expressions under aggregate-only access | `enhancement`, `contracts` | Yes | N | M | apiome-ui, apiome-rest |
| 7.3 (#4256) | Runtime Gateway Enforcement of Sharing Specs | Block non-conforming access at request time, not just monitor after the fact | `enhancement`, `contracts`, `rest` | No | N | L | apiome-rest, apiome-db |
| 7.4 (#4257) | Data Lineage & Verifiable Recall | Affected-record counts, cached-extract tracking, recall packages, re-send notices | `enhancement`, `contracts` | No | N | L | apiome-rest, apiome-ui, apiome-db |
| 7.5 (#4258) | Sharing Clause Refinements: Sync Cadence, Version Pinning & Bulk Configure | Refresh window & pull/push mode, pinned schema versions, picker search, bulk-apply | `enhancement`, `contracts` | Yes | N | S | apiome-ui, apiome-rest |
| 7.6 (#4259) | Usage Quotas, Overage Pricing & Cross-Contract Analytics | Quota windows with reset countdowns, configurable thresholds, overage rates, top-consumers view, CSV export | `enhancement`, `contracts`, `rest` | Yes | N | M | apiome-rest, apiome-ui, apiome-db |
| 7.7 (#4260) | Usage-Based Renewal Recommendations & Work Queue | Tier upsell/downgrade recommendations, quota-gated auto-renew, actionable renewal queue | `enhancement`, `contracts` | No | N | M | apiome-rest, apiome-ui |
| 7.8 (#4261) | Consent Operations Dashboard & Log Integrity | Consent KPI strip, filters, DSAR collection method, hash-chained consent log | `enhancement`, `contracts` | Yes | N | S | apiome-ui, apiome-rest |

### Detailed Issue Descriptions

#### 7.1 (#4254) — PII Classification & Pseudonymisation

**Problem Statement**: The schema picker in `data-sharing.html` auto-tags `email`, `name`, `phone`, and `address` with amber `PII` chips and offers "Pseudonymise PII fields" and "Mandatory purge on contract end" handling requirements — but 2.1 (#964) enumerates only encryption, no-export, and retention, with no classification capability behind the tags.

**Solution/Scope**: A classification service tags schema properties as PII (name/pattern heuristics with manual override, persisted per schema version). Extend the handling-requirements vocabulary with `pseudonymise` (PII fields hashed/tokenised before delivery) and `purge_on_end` (data-destruction obligation on contract termination, generating a recall-style confirmation workflow via 2.5). Classification feeds GDPR reporting (4.3) and DSAR fulfilment (9.4).

**Acceptance Criteria**:
- Properties are auto-classified with confidence and manually overridable; overrides are audited
- `pseudonymise` and `purge_on_end` are storable handling requirements exported in the machine-readable spec
- Selecting a PII-tagged property without any protective handling requirement raises a validation warning
- Purge-on-end generates a deletion-confirmation obligation at contract termination, tracked like a 2.5 recall
- Classification is queryable per schema version for compliance reports

**Parallelism/Dependencies**: Extends 2.1 (#964); feeds 4.3, 9.4, and 2.5. Parallel with 7.2/7.5.

**Technical Stack**: Classification heuristics service, PostgreSQL, REST.

**Part of Epic: Data Sharing Enforcement & Intelligence**

---

#### 7.2 (#4255) — Aggregate Query Definition Builder

**Problem Statement**: 2.1 grants an "aggregate-only" access level, but the EventLog card in `data-sharing.html` defines the actual permitted expressions — `count(*) by event_type`, `avg(latency_ms) by hour`, `p95(latency_ms) by endpoint` — and no issue describes authoring, validating, or enforcing an aggregate-expression grant.

**Solution/Scope**: A builder for aggregate grants attached to aggregate-only clauses: each grant specifies an aggregation function (`count`, `sum`, `avg`, `min`, `max`, percentiles), the measure property, permitted group-by dimensions, and a minimum group size (k-anonymity floor) so aggregates cannot be narrowed to individuals. Grants export in the machine-readable spec and are the enforcement basis for 7.3 at the gateway.

**Acceptance Criteria**:
- Grants capture function, measure, group-by dimensions, and minimum group size
- Only properties included in the sharing clause are referenceable in grants
- Grants serialize into the machine-readable spec consumed by runtime enforcement
- A validation preview shows a sample of what the counterparty may compute
- Editing grants creates a new contract version per 2.1's versioning rule

**Parallelism/Dependencies**: Extends 2.1 (#964); enforcement lands in 7.3. Parallel with 7.1/7.5.

**Technical Stack**: NextJS builder UI, JSON grant schema, REST.

**Part of Epic: Data Sharing Enforcement & Intelligence**

---

#### 7.3 (#4256) — Runtime Gateway Enforcement of Sharing Specs

**Problem Statement**: The machine-readable spec panel in `data-sharing.html` is headed "enforced at the gateway", but the roadmap only monitors after the fact (2.4) and checks pacts at publish time (5.2) — nothing actually blocks a request that exceeds a clause's access level, properties, or quotas.

**Solution/Scope**: An enforcement layer in the API request path that resolves the caller's contract + clause, then allows, filters, or rejects: access-level checks (a write against a read-only clause is rejected with a clause reference), property filtering (fields outside `included_properties` are stripped from responses), aggregate-grant checks (7.2), and hard-quota rejection when 7.6 quotas are marked blocking. Enforcement decisions emit 4.1 events; enforcement is fail-closed for contracts that opt in, with a monitor-only rollout mode.

```
  request ──▶ resolve contract/clause ──▶ access-level check ──▶ reject (403 + clause ref)
                                            │ pass
                                            ├──▶ property filter ──▶ response minus excluded fields
                                            ├──▶ aggregate grant check (7.2)
                                            └──▶ quota check (7.6, blocking mode) ──▶ 429 + retry-after
```

**Acceptance Criteria**:
- Requests violating access level are rejected with the violated clause reference in the error body
- Response payloads are filtered to the clause's included properties
- Blocking quotas return 429 with the quota window reset time; monitor-only mode logs without blocking
- Enforcement decisions (allow-filtered, reject) are recorded as 4.1 events and feed 2.4 dashboards
- Enforcement adds < 5 ms p95 overhead to the request path

**Parallelism/Dependencies**: Depends on 2.1 spec export, 7.2 grants, 7.6 quota model; feeds 2.4 monitoring. Sequenced after 7.2.

**Technical Stack**: Request middleware in apiome-rest, spec cache, REST error contracts.

**Part of Epic: Data Sharing Enforcement & Intelligence**

---

#### 7.4 (#4257) — Data Lineage & Verifiable Recall

**Problem Statement**: The recall banner in `consent.html` quantifies "~3 412 records · 2 cached extracts" and offers "View recall package" and "Re-send notice" — but 2.5 (#968) has no record counting, no tracking of downstream copies/extracts, and no recall artifact; recall compliance is currently take-their-word-for-it.

**Solution/Scope**: Track delivery lineage per sharing clause: each export/bulk delivery records a **extract manifest** (record count, filter, timestamp, destination) so a recall can enumerate affected records and outstanding cached extracts. Generate a downloadable **recall package** (recall notice, affected-scope manifest, consent history, deletion-confirmation checklist) and add an operator **re-send notice** action with delivery history. Deletion confirmations check off individual extracts rather than the recall as a whole.

**Acceptance Criteria**:
- Every bulk export/delivery under a sharing clause records an extract manifest
- Recall notices enumerate affected record counts and outstanding extracts from lineage data
- Recall package is downloadable and archived as dispute-grade evidence (4.2)
- Re-send notice is available on active recalls with full delivery history
- Deletion confirmation tracks per-extract acknowledgment; a recall closes only when all extracts are confirmed

**Parallelism/Dependencies**: Extends 2.5 (#968); consumes 2.4 usage events; evidence integrates with 4.2. Sequenced after 2.4.

**Technical Stack**: Extract-manifest tables, ZIP package generation, REST.

**Part of Epic: Data Sharing Enforcement & Intelligence**

---

#### 7.5 (#4258) — Sharing Clause Refinements: Sync Cadence, Version Pinning & Bulk Configure

**Problem Statement**: `data-sharing.html` shows a "Refresh window · 15 min · pull" control, a "Published v4.2" schema version on each card, a "Filter classes…" picker search, and a "Configure all →" bulk action — none of which exist in 2.1's picker or clause model.

**Solution/Scope**: Add per-shared-schema **sync cadence** (refresh interval + pull/push delivery mode); **pin the exact published schema version** a clause references (today 2.1 only requires "a published state"), so verification (5.x) and disputes attribute against the version actually agreed; add picker **search/filtering** and **bulk-apply** of access levels and handling requirements across selected elements.

**Acceptance Criteria**:
- Sync cadence (interval, pull/push) persists per shared schema and exports in the machine-readable spec
- Clauses record the pinned schema version; counterparty schema publishes do not silently change the agreed shape
- A newer published version surfaces as an "update available" prompt that requires a contract amendment to adopt
- Picker supports free-text class filtering; bulk configure applies settings to all selected elements in one action

**Parallelism/Dependencies**: Extends 2.1 (#964). Version pinning strengthens 5.3 attribution. Parallel with 7.1/7.2.

**Technical Stack**: NextJS picker, PostgreSQL clause columns, REST.

**Part of Epic: Data Sharing Enforcement & Intelligence**

---

#### 7.6 (#4259) — Usage Quotas, Overage Pricing & Cross-Contract Analytics

**Problem Statement**: `usage.html` renders quota meters with "of 6.0M / month quota · 8 d remaining in window", an "alert threshold @ 90%" (2.4's AC hard-codes 80%), an overage line "+2 over · overage @ $50 / export", a cross-contract "Top consumers" leaderboard, an "Export usage CSV" button, and 7d/30d/90d/YTD range toggles — quota-period semantics, overage economics, and portfolio views that 2.4 (#967) lacks.

**Solution/Scope**: Define **quota windows** (period, reset schedule, remaining-days countdown) on usage limits; make alert thresholds **configurable per clause** (default 90%, reconciling the 2.4/mockup discrepancy); add **overage pricing** (per-unit rate applied to usage beyond quota, with blocking vs. billable modes) that emits billable events into the 3.1 metering pipeline; add a **cross-contract usage view** (top-consumers leaderboard, portfolio meters); and add **usage CSV export** plus time-range toggles and SLA-metric context tiles (p95 latency, error rate from 1.2 clause data) on the telemetry page.

**Acceptance Criteria**:
- Quota meters show window, reset countdown, and configurable warning threshold; threshold changes are versioned per clause
- Overage units are priced per the clause's overage rate and appear as 3.2 invoice line items (or are blocked by 7.3 when the quota is blocking)
- Top-consumers view ranks contracts by consumption with over-quota flags
- Usage CSV export respects the active filters and range toggle
- The 2.4 detailed access-log table remains available alongside the aggregate meters

**Parallelism/Dependencies**: Extends 2.4 (#967); overage events feed 3.1/3.2; blocking mode depends on 7.3. Parallel with 7.5.

**Technical Stack**: Metering aggregation, PostgreSQL, NextJS charts, CSV streaming.

**Part of Epic: Data Sharing Enforcement & Intelligence**

---

#### 7.7 (#4260) — Usage-Based Renewal Recommendations & Work Queue

**Problem Statement**: The renewal queue in `usage.html` recommends "Renew @ tier 2 (+15% usage trend)", "Upsell to Enterprise (avg 7 exports / mo)", and "consider downgrade tier", gates auto-renew with a "review · over quota" state, and offers Approve / Negotiate / Schedule actions — while 2.3 (#966) only auto-renews identical terms and sends notifications.

**Solution/Scope**: A recommendation engine that analyses usage trends against the contract's tier and produces a renewal recommendation (renew as-is, upsell tier, downgrade tier) with the supporting trend figures; **quota-compliance gating** that flips over-quota contracts from auto-renew to review-required; and an operator **renewal work queue** with per-row actions — Approve (renew with recommended terms), Negotiate (open a 1.4 negotiation seeded with the recommended amendment), Schedule (defer the decision).

**Acceptance Criteria**:
- Recommendations cite the usage evidence (trend %, per-period averages) that produced them
- Over-quota contracts cannot silently auto-renew; they enter review-required with both parties notified
- Approve renews with the selected terms; Negotiate opens a pre-seeded 1.4 revision; Schedule sets a follow-up date
- Queue rows show the countdown, auto-renew mode, recommendation, and quota state in one line
- All recommendation-driven renewals are recorded as 4.1 events with the recommendation attached

**Parallelism/Dependencies**: Extends 2.3 (#966); consumes 7.6 usage data and 1.4 negotiation. Sequenced after 7.6. Tenant-wide renewal policies live in 11.2.

**Technical Stack**: Trend analysis job, REST, NextJS queue UI.

**Part of Epic: Data Sharing Enforcement & Intelligence**

---

#### 7.8 (#4261) — Consent Operations Dashboard & Log Integrity

**Problem Statement**: `consent.html` opens with four KPI cards (aggregate status "3 of 4 clauses", active grants +2 this month, expiring · 30 d, active recalls), filters the table by status and date, records a "data subject request" collection method, and footers the table with "SHA-256 · 9b3f…71ac · log immutable since 2024-09-01" — a KPI surface, filter set, method value, and integrity proof absent from 2.2 (#965).

**Solution/Scope**: Add the consent **KPI strip** (aggregate clause coverage, active-grant count with monthly delta, expiring-within-30d, active recalls with per-notice countdown bars and an active/acknowledged rollup); **status and date-range filters** on the consent table; **`data_subject_request`** as a collection-method value; and **hash-chain the consent log** (each entry hashes its predecessor; the current head renders in the footer and verifies through the 9.1 integrity verifier).

**Acceptance Criteria**:
- KPI strip reflects live consent state; recall cards show deadline progress and remaining days
- Consent table filters by status and date range
- `data_subject_request` is accepted and reported as a collection method
- Consent-log entries are hash-chained; the verifier detects any gap or mutation
- Consent KPIs and integrity status are exportable for 4.3 compliance reports

**Parallelism/Dependencies**: Extends 2.2 (#965)/2.5 (#968); chain verification shares 9.1 infrastructure. Parallel within Epic 7.

**Technical Stack**: SHA-256 chaining, NextJS KPI components, REST.

**Part of Epic: Data Sharing Enforcement & Intelligence**

---

## Epic 8 (#4262): Billing Operations & Financial Integrations

The `billing.html` and `invoice.html` mockups expose the largest single gap in the roadmap: Epic 3 meters usage and generates invoices, but nothing authors the pricing those systems consume, runs the billing cycle as an observable job, reconciles to accounting systems, or handles line-item-level disputes and tax metadata.

### Summary Table

| #   | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|-----|-------|---------|--------|----------|-----|------------|------------------|
| 8.1 (#4263) | Pricing Model Builder | Author flat-fee, usage-tiered, and per-seat pricing with tier tables, platform fees, currency | `enhancement`, `contracts`, `mvp`, `rest` | Yes | Y | M | apiome-ui, apiome-rest, apiome-db |
| 8.2 (#4264) | Billing Run Orchestration & Observability | Tenant-wide billing cycle runner with step-level results, retries, durations, and logs | `enhancement`, `contracts`, `rest` | No | N | L | apiome-rest, apiome-db, apiome-ui |
| 8.3 (#4265) | ERP & Accounting Reconciliation | NetSuite/QuickBooks GL posting and reconciliation with per-adapter sync status | `enhancement`, `contracts` | Yes | N | L | apiome-rest, apiome-db |
| 8.4 (#4266) | Expanded Payment & Payout Rails | Adyen, Coinbase, Wise adapters; non-Stripe payout targets; projected payouts per cycle | `enhancement`, `contracts` | Yes | N | M | apiome-rest |
| 8.5 (#4267) | Invoice Line-Item Disputes, Evidence & Tax Metadata | Per-line dispute flags, line→evidence drill-down, VAT/EIN/PO fields, tax jurisdiction, activity feed | `enhancement`, `contracts`, `rest` | No | N | M | apiome-ui, apiome-rest, apiome-db |
| 8.6 (#4268) | Billing KPIs & Revenue Analytics | MRR with MoM trend, revenue-share owed, failed-charge tracking on the billing dashboard | `enhancement`, `contracts` | Yes | N | S | apiome-ui, apiome-rest |

### Detailed Issue Descriptions

#### 8.1 (#4263) — Pricing Model Builder

**Problem Statement**: 3.1 (#970) and 3.2 (#971) both *consume* "contract pricing tiers", but no issue defines where pricing is authored — `billing.html` mocks the missing editor: a Flat fee / Usage tiered / Per-seat toggle, an editable tier table (`0–100k · $0.0010/call`), a platform fee field, and a currency selector. Invoices cannot be generated without this.

**Solution/Scope**: A per-contract pricing model editor supporting **flat fee** (fixed recurring amount), **usage-tiered** (ordered tier table of usage ranges × unit prices per metered metric), and **per-seat** (seat count × seat price) models, each optionally combined with a recurring **platform fee** and a contract **currency**. Includes a live "calculated this period" preview against current 3.1 metering. Pricing versions are effective-dated: changes apply to future billing periods only and require counterparty approval like any term change (1.4).

**Acceptance Criteria**:
- All three model types round-trip: editor → API → invoice line-item calculation
- Tier tables validate contiguous, non-overlapping ranges; unit prices support 4-decimal precision
- Platform fee and currency persist per contract; currency drives all downstream invoice rendering
- Live preview computes the current period's charge from actual metering within 5% of the eventual invoice (matching 3.1's estimate AC)
- Pricing changes are effective-dated, versioned, and gated on counterparty approval

**Parallelism/Dependencies**: Feeds 3.2 (#971) invoice generation; preview consumes 3.1 (#970). MVP — invoicing is blocked without it. Parallel with 8.3/8.4.

**Technical Stack**: NextJS editor, PostgreSQL JSONB pricing schema, REST.

**Part of Epic: Billing Operations & Financial Integrations**

---

#### 8.2 (#4264) — Billing Run Orchestration & Observability

**Problem Statement**: 3.2 says invoices are "generated automatically at period end", but `billing.html` shows what that actually requires: a "Run billing cycle" action and a "Last billing run" table with six steps — Aggregate usage → Apply tier pricing → Compute splits → Push to Stripe → Charge customers → Reconcile NetSuite — each with result, record count, duration, and pending retries. No issue owns this orchestration.

**Solution/Scope**: A tenant-wide billing-run job with explicit, observable steps and per-step results, record counts, durations, retry state, and a full run log. Runs trigger on schedule (period end) or manually; steps are idempotent and independently retryable so a Stripe outage doesn't re-aggregate usage. The run surface lives on the billing hub with drill-down to the full log.

```
  billing run ──▶ 1 aggregate usage ──▶ 2 apply pricing ──▶ 3 compute splits
                     │                       │                   │
                     ▼                       ▼                   ▼
                4 push invoices ──▶ 5 charge customers ──▶ 6 reconcile ERP
                (each step: result · records · duration · retries · log)
```

**Acceptance Criteria**:
- Billing runs execute the step pipeline with per-step status, record counts, and durations persisted
- Failed steps retry with backoff; a step can be manually re-run without repeating completed steps
- "Run billing cycle" triggers an ad-hoc run guarded against overlapping executions
- Full run log is viewable and exportable; run completion/failure emits 4.1 events
- Partial failures leave the run in a resumable state with pending-retry counts surfaced

**Parallelism/Dependencies**: Orchestrates 3.1/3.2/3.3/3.4 and 8.3. Sequenced after 8.1 and 3.2.

**Technical Stack**: Job queue with step checkpoints, PostgreSQL run tables, NextJS run viewer.

**Part of Epic: Billing Operations & Financial Integrations**

---

#### 8.3 (#4265) — ERP & Accounting Reconciliation

**Problem Statement**: The billing hub is titled "Stripe ↔ NetSuite reconciliation" and lists `NetSuite · GL sync · 5 min · synced` and `QuickBooks · paused · scoped to EU` as rails, with billing-run step 6 posting "88 GL entries" — but 3.3 (#972) covers payment gateways only; accounting-system integration has no issue.

**Solution/Scope**: An accounting-adapter layer, parallel to 3.3's payment abstraction, that posts invoices, payments, credits, and revenue-share distributions to external ledgers (NetSuite first, QuickBooks second) and reconciles: per-adapter sync status (`live / synced / paused / scoped`), sync cadence, posted-entry counts, and a discrepancy report when Apiome totals and GL totals diverge. Adapters are region-scopeable (e.g. QuickBooks for EU entities only).

**Acceptance Criteria**:
- Invoices, payments, credits, and distributions post to NetSuite as GL entries with idempotent external IDs
- Adapter status (live/synced/paused), cadence, and last-sync render on the billing hub rails panel
- Reconciliation compares Apiome and GL balances per period and surfaces discrepancies with drill-down
- Adapters are scopeable by region/entity; paused adapters queue entries for later posting
- QuickBooks adapter reuses the abstraction without core-logic changes (mirrors 3.3's gateway AC)

**Parallelism/Dependencies**: Consumes 3.2 invoices and 3.4 distributions; runs as 8.2's reconcile step. Parallel with 8.1/8.4.

**Technical Stack**: NetSuite/QuickBooks APIs, adapter abstraction, reconciliation job.

**Part of Epic: Billing Operations & Financial Integrations**

---

#### 8.4 (#4266) — Expanded Payment & Payout Rails

**Problem Statement**: The rails panel offers an "Add adapter" row listing Adyen, Coinbase, and Wise, and the revenue-share table pays Initech via "NetSuite vendor" while others use Stripe Connect — rails and payout channels beyond 3.3's Stripe/PayPal/wire scope, and a non-Stripe payout target 3.4 (#973) doesn't model.

**Solution/Scope**: Implement additional adapters on 3.3's abstraction — **Adyen** (cards/local methods), **Wise** (cross-border/FX payouts), **Coinbase** (crypto settlement, feature-flagged) — and extend 3.4's settlement model with **per-party payout channels** (Stripe Connect, NetSuite vendor payment, Wise transfer) plus **projected payouts for the current cycle** shown alongside actuals.

**Acceptance Criteria**:
- Each new adapter implements the 3.3 abstraction with no core billing changes
- Revenue-share parties configure a payout channel; settlements route per channel with per-channel status
- Projected current-cycle payouts render next to settled amounts in the revenue-share panel
- Crypto settlement is feature-flagged per tenant and disabled by default
- Failed payouts surface with retry and manual-settlement fallback

**Parallelism/Dependencies**: Depends on 3.3 (#972) abstraction and 3.4 (#973) distributions; NetSuite vendor payouts depend on 8.3. Parallel with 8.3.

**Technical Stack**: Adyen/Wise/Coinbase SDKs, payout-channel model, REST.

**Part of Epic: Billing Operations & Financial Integrations**

---

#### 8.5 (#4267) — Invoice Line-Item Disputes, Evidence & Tax Metadata

**Problem Statement**: `invoice.html` flags line 004 as `disputed by Hooli` ("counter-party claims 2.8M") with click-to-expand evidence per row, renders VAT/EIN, PO number, and remit-to blocks, computes `Tax (CA 8.625%)`, bills an overage line (`2 over · $50/each`), and shows a per-invoice activity feed — none of which 3.2 (#971) or 4.2 (#977) specify.

**Solution/Scope**: **Line-item dispute flagging** (a party disputes a specific line with their claimed figure; the flag renders inline and can escalate to a full 4.2/9.6 dispute scoped to that line); **line→evidence drill-down** (each usage-derived line expands to its metering records and clause reference); **party tax/PO metadata** on invoices (VAT/EIN, PO number, remit-to — sourced from 11.1 counterparty records); a **tax jurisdiction resolver** (rate by seller/buyer jurisdiction with an override table); **overage line items** (from 7.6); an explicit **credits subtotal row**; a **Re-issue & send** action; a `Disputed` invoice status; and a **per-invoice activity feed** (generated → sent to AP → dispute opened → …) derived from 4.1 events.

**Acceptance Criteria**:
- A line item can be disputed with the counterparty's claimed quantity/amount; disputed lines render inline and link to the dispute case
- Every usage-derived line expands to its metering evidence and clause reference
- Invoices carry VAT/EIN, PO, and remit-to blocks populated from counterparty records
- Tax lines resolve jurisdiction and rate, itemised on the invoice and PDF
- Invoice status set includes `Disputed`; re-issue creates a corrected revision linked to the original
- Per-invoice activity feed renders the invoice's 4.1 event slice chronologically

**Parallelism/Dependencies**: Extends 3.2 (#971); dispute escalation integrates 4.2/9.6; metadata depends on 11.1; overage lines depend on 7.6. Sequenced after 3.2.

**Technical Stack**: PostgreSQL invoice-line extensions, tax-rate resolver, NextJS, PDF rendering.

**Part of Epic: Billing Operations & Financial Integrations**

---

#### 8.6 (#4268) — Billing KPIs & Revenue Analytics

**Problem Statement**: 3.5 (#974) specifies outstanding / collected-this-month / overdue cards only, while the billing hub renders MRR with a month-over-month trend, "Revenue share owed", and a failed-charges KPI (`card_declined`), and the contract dashboard needs per-contract MRR (6.2) — revenue analytics has no owner.

**Solution/Scope**: A revenue-analytics service computing **MRR per contract and per tenant** (with MoM deltas), **revenue-share owed** (unsettled distribution balances from 3.4), and **failed-charge tracking** (count, reasons, retry state from 3.3). Exposes the KPI cards on the billing dashboard and the per-contract value column consumed by 6.2.

**Acceptance Criteria**:
- MRR is computed per contract (normalising non-monthly billing periods) and aggregates per tenant with MoM trend
- Revenue-share owed reflects unsettled 3.4 distributions in real time
- Failed charges surface with gateway reason codes and link to retry/manual-payment flows
- A per-contract financial summary endpoint serves the 6.2 dashboard value column
- KPI figures reconcile with invoice/settlement totals for the same period

**Parallelism/Dependencies**: Extends 3.5 (#974); consumes 3.3/3.4; feeds 6.2. Parallel with 8.5.

**Technical Stack**: Aggregation queries, REST summary endpoints, NextJS KPI cards.

**Part of Epic: Billing Operations & Financial Integrations**

---

## Epic 9 (#4269): Compliance, Audit & Dispute Operations

`history.html`, `compliance.html`, and `disputes.html` render trust machinery well beyond Epic 4's text: a per-event hash chain with a gap-detecting verifier, multi-backend anchoring, a GRC control-mapping engine with findings and a posture score, DSAR fulfilment, an auditor vault, a full mediation/settlement console, and tenant-wide encrypted data portability.

### Summary Table

| #   | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|-----|-------|---------|--------|----------|-----|------------|------------------|
| 9.1 (#4270) | Per-Event Hash Chaining & Integrity Verifier | Chain every event to its predecessor; windowed verifier UI with gap detection, facets, full-text search | `enhancement`, `contracts`, `rest` | Yes | N | L | apiome-rest, apiome-db, apiome-ui |
| 9.2 (#4271) | Multi-Adapter Tamper-Evidence Anchoring | OpenTimestamps and S3 Object-Lock WORM backends beside Ethereum; schedule presets; cost surfacing | `enhancement`, `contracts` | Yes | N | M | apiome-rest |
| 9.3 (#4272) | GRC Framework Control Mapping & Posture Score | SOC 2 / GDPR / CCPA / ISO 27001 / HIPAA control coverage, findings management, posture score | `enhancement`, `contracts` | Yes | N | L | apiome-rest, apiome-db, apiome-ui |
| 9.4 (#4273) | DSAR Fulfilment Workflow | Intake, track, and register GDPR Art. 15/17/20 data-subject requests | `enhancement`, `contracts`, `rest` | Yes | N | M | apiome-rest, apiome-ui, apiome-db |
| 9.5 (#4274) | Auditor Evidence Vault & Signed Reports | Cryptographically signed reports, expanded report types, time-boxed auditor access packages | `enhancement`, `contracts` | No | N | M | apiome-rest, apiome-ui |
| 9.6 (#4275) | Mediation & Settlement Workflow | Mediator role and console, response SLAs, 5-stage lifecycle, settlement offers with credit issuance | `enhancement`, `contracts` | No | N | L | apiome-rest, apiome-ui, apiome-db |
| 9.7 (#4276) | Tenant Data Portability Export | Whole-tenant multi-entity export in Parquet with tenant-KMS encryption and scheduling | `enhancement`, `contracts`, `rest` | Yes | N | M | apiome-rest |

### Detailed Issue Descriptions

#### 9.1 (#4270) — Per-Event Hash Chaining & Integrity Verifier

**Problem Statement**: 4.1 (#976) guarantees append-only + sequence numbers and 4.4 (#979) anchors periodic Merkle roots, but `history.html` shows a per-event `Hash` column, a `chain head: 3a8e…f102`, "chain integrity verified · 0 gaps", a windowed Chain-integrity-verifier panel with a raw-Merkle-tree viewer, and CI-driven verification (`gh-actions/integrity`) — a continuous tamper-evidence mechanism neither issue provides.

**Solution/Scope**: Hash-chain the event log: each event stores `hash = H(prev_hash ‖ canonical_payload)`; the chain head is surfaced on the history screen. Ship the **verifier UI** (From/To window → events/anchors/gaps counts, verification duration, re-verify, raw Merkle tree view), **gap detection** (sequence continuity + hash-link validation), a **CI verification hook** (external job recomputes the chain and reports, recorded with actor attribution), plus **event-type facet chips with live counts** and **full-text timeline search** on the history screen. The consent log (7.8) and signature hashes (6.5) use the same primitives.

```
  e₁ ──H──▶ e₂ ──H──▶ e₃ ──H──▶ … ──▶ chain head 3a8e…f102
   │          │          │
   └──────────┴──────────┴──▶ Merkle root ──▶ anchor batch (4.4 / 9.2)
  verifier: recompute window ──▶ events · anchors · gaps ──▶ valid / tampered
```

**Acceptance Criteria**:
- Every event records the hash of its predecessor; the chain head is queryable and rendered
- Verifier validates any window, reporting event count, anchor coverage, and gaps; tampering or gaps fail loudly
- Raw Merkle tree for any anchor batch is viewable; verification runs are themselves logged with actor
- External/CI verification is supported via a documented endpoint and reference workflow
- History screen adds full-text search and event-type facet chips with counts alongside 4.1's structured filters

**Parallelism/Dependencies**: Extends 4.1 (#976); anchoring batches feed 4.4/9.2; shared with 7.8 and 6.5. Parallel with 9.3/9.4.

**Technical Stack**: SHA-256 chaining, Merkle trees, PostgreSQL, NextJS verifier panel.

**Part of Epic: Compliance, Audit & Dispute Operations**

---

#### 9.2 (#4271) — Multi-Adapter Tamper-Evidence Anchoring

**Problem Statement**: 4.4 (#979) anchors to "Ethereum (or a configurable chain)", but `compliance.html` lists **OpenTimestamps** and **S3 WORM** as sibling anchoring targets with independent enable/pause states and schedule presets (`Hourly / Every 8h / Daily / Manual`) — tenants that can't touch a public chain have no roadmap path to tamper evidence.

**Solution/Scope**: Generalize anchoring behind an adapter interface with three backends: **Ethereum L1** (existing 4.4), **OpenTimestamps** (free, Bitcoin-attested), and **S3 Object-Lock WORM** (compliance-mode immutable objects). Each adapter enables/pauses independently with its own schedule preset; anchor records show backend, cost, block height / OTS proof / object version, and an explorer/proof link. Verification (9.1) accepts proofs from any enabled backend.

**Acceptance Criteria**:
- The same Merkle root can anchor to multiple backends concurrently, each with independent schedules
- OTS proofs and S3 WORM object versions verify through the 9.1 verifier like Ethereum anchors
- Anchor records show per-backend cost (gas estimate for Ethereum, storage for S3, zero for OTS)
- Pausing a backend queues batches without blocking the others
- Adapter addition requires no changes to event-log or verifier core

**Parallelism/Dependencies**: Extends 4.4 (#979); verification via 9.1. Parallel with 9.1.

**Technical Stack**: OpenTimestamps client, S3 Object Lock, Ethereum RPC, adapter abstraction.

**Part of Epic: Compliance, Audit & Dispute Operations**

---

#### 9.3 (#4272) — GRC Framework Control Mapping & Posture Score

**Problem Statement**: 4.3 (#978) generates reports, but `compliance.html` runs a GRC program: a `96/100` posture score trending "+3 pts this month", an open-findings tracker (`1 medium · 1 low`, `ISO 27001 · A.8.16 monitoring`), and a frameworks panel scoring **SOC 2 Type II 98% (142/145 controls automated)**, **GDPR 96%**, **CCPA 94%**, **ISO 27001 88%**, and **HIPAA scoped · BAA template ready** — control mapping, findings, and scoring have no issue.

**Solution/Scope**: A control-mapping engine: a catalog of platform controls (event-log immutability, consent tracking, encryption handling, access restrictions, verification gates) mapped to framework requirements (SOC 2 trust criteria, GDPR articles, CCPA sections, ISO 27001 annex controls, HIPAA safeguards). Each mapping has an automated evidence check where possible; coverage percentages roll up per framework and into a tenant **posture score** with trend. **Findings** (failed or unmapped controls) carry severity, owner, and remediation state. Framework packs are versioned data, addable without code changes.

**Acceptance Criteria**:
- Control catalog maps to at least SOC 2, GDPR, CCPA, and ISO 27001 requirement sets, with HIPAA scoped
- Automated checks evaluate mapped controls on schedule; coverage % = passing automated + attested manual controls
- Posture score aggregates framework coverage with severity weighting and renders trend over time
- Findings track severity, owner, remediation state, and link to the failing control and its evidence
- 4.3 reports can embed framework coverage and findings sections

**Parallelism/Dependencies**: Extends 4.3 (#978); consumes signals from 4.1/9.1, 2.2, 7.1, and Epic 5 gates. Parallel with 9.1/9.4.

**Technical Stack**: Framework requirement packs (versioned data), check scheduler, NextJS GRC dashboard.

**Part of Epic: Compliance, Audit & Dispute Operations**

---

#### 9.4 (#4273) — DSAR Fulfilment Workflow

**Problem Statement**: `compliance.html` lists a "DSAR fulfilment register · GDPR Art. 15" report and `consent.html` records a "data subject request" method, but no issue implements receiving, tracking, or fulfilling data-subject requests — consent tracking (2.2) manages grants, not subject rights.

**Solution/Scope**: A DSAR workflow covering **access** (Art. 15 — compile the subject's data across shared schemas using 7.1 PII classification), **erasure** (Art. 17 — trigger deletion obligations across contracts holding the subject's data, reusing 2.5 recall machinery), and **portability** (Art. 20 — machine-readable subject export). Requests have intake (form/API), identity verification, a statutory-deadline clock (30 days with extension tracking), per-contract fulfilment subtasks, and a **register** feeding the 4.3 report.

**Acceptance Criteria**:
- DSAR intake captures request type, subject identity, and verification evidence
- Deadline clock tracks the statutory window with escalation before expiry
- Access/portability requests compile subject data across contracts using PII classification
- Erasure requests generate per-contract deletion obligations tracked to confirmation
- The DSAR register lists all requests with status and timing, exportable via 4.3

**Parallelism/Dependencies**: Depends on 7.1 (classification) and 2.5 (recall machinery); feeds 4.3/9.3. Parallel with 9.3.

**Technical Stack**: Workflow tables, deadline scheduler, REST intake API, NextJS register.

**Part of Epic: Compliance, Audit & Dispute Operations**

---

#### 9.5 (#4274) — Auditor Evidence Vault & Signed Reports

**Problem Statement**: `compliance.html` shows reports with a `Signed` status ("cryptographically signed"), an "Annual SOC 2 evidence pack · Auditor pkg · Open vault" row, and report types (SOC 2 CC7/CC8, CCPA data-sharing inventory, DSAR register, contract-integrity) beyond 4.3's four — report signing, auditor access, and the expanded catalog have no issue.

**Solution/Scope**: **Sign generated reports** (detached signature over the artifact, verifiable offline; status set `Generating / Signed / Auditor pkg`); expand the 4.3 report catalog with SOC 2 evidence packs, CCPA data-sharing inventory, DSAR register (9.4), and contract-integrity (9.1 verification results); add **JSON output** beside PDF/CSV; and ship an **auditor vault** — a time-boxed, read-only external portal where an auditor receives a scoped evidence package (reports, anchor proofs, control evidence from 9.3) with access logging.

**Acceptance Criteria**:
- Reports are signed at generation; signatures verify offline against a published tenant key
- Report catalog includes SOC 2 evidence pack, CCPA inventory, DSAR register, and contract-integrity types
- JSON is available as an output format for all report types
- Auditor vault grants are time-boxed, read-only, scoped to named packages, and fully access-logged
- Vault access events are recorded in the 4.1/9.1 chain

**Parallelism/Dependencies**: Extends 4.3 (#978); consumes 9.1/9.3/9.4 outputs. Sequenced after 9.3.

**Technical Stack**: Artifact signing (Ed25519/KMS), scoped-access portal, REST.

**Part of Epic: Compliance, Audit & Dispute Operations**

---

#### 9.6 (#4275) — Mediation & Settlement Workflow

**Problem Statement**: The README calls `disputes.html` a "mediator console", and the screen shows a `Mediator · unassigned · auto-assign T+5d` party row, "day 4 of 14" mediation clocks, response SLAs ("respond by 2026-04-25 12:00 UTC"), a five-stage stepper (filed → acknowledged → evidence → resolved → closed), a compose-response panel with evidence/clause/hash insertion, settlement options (full credit −$160 / partial −$80 / uphold $0), a quantified disputed amount (`400k calls × $0.0004`), and cross-source metering reconciliation ("within 0.006% across 3 independent sources") — 4.2 (#977) models none of this beyond open→resolve.

**Solution/Scope**: Extend disputes with: the **five-stage lifecycle** and richer statuses (`awaiting evidence`, `in mediation`, `awaiting counterparty`, `resolved-credit`, `resolved-upheld`); a **mediator role** (neutral third party, assignable manually or auto-assigned after a configurable window, with a scoped console view); **response SLAs and mediation clocks** with escalation on expiry; **in-dispute messaging** (threaded responses with insertable evidence packs, clause references, and chain hashes; drafts + "submit & advance"); a **quantified disputed amount** derived from the disputed line/clause; **automatic metering reconciliation** in the evidence pack (compare Apiome metering, gateway logs, and the counterparty's claimed figure, reporting the discrepancy %); and **settlement offers** whose accepted credits flow to 3.2 as invoice credit line items.

```
  filed ──▶ acknowledged ──▶ evidence ──▶ resolved ──▶ closed
              │ SLA clock      │ mediator auto-assign T+5d
              ▼                ▼
        respond-by deadline   settlement offer ──▶ accepted ──▶ credit → invoice (3.2)
                                             └──▶ declined ──▶ continue mediation / uphold
```

**Acceptance Criteria**:
- Disputes progress through the five stages with per-stage timestamps and the richer status vocabulary
- Mediator can be assigned manually or auto-assigned after the configured window; mediator sees a scoped console
- Response SLAs render countdowns and escalate on expiry
- Messages support inserting evidence packs, clause references, and chain hashes; submissions advance the stage
- Evidence packs include cross-source metering reconciliation with discrepancy percentage
- Accepted settlements issue credits that appear on the next (or a corrected) invoice with links back to the dispute

**Parallelism/Dependencies**: Extends 4.2 (#977); credits integrate with 3.2 (#971); line-item disputes arrive via 8.5; evidence uses 9.1 hashes. Sequenced after 4.2.

**Technical Stack**: Dispute state machine, mediation scheduler, NextJS console, REST.

**Part of Epic: Compliance, Audit & Dispute Operations**

---

#### 9.7 (#4276) — Tenant Data Portability Export

**Problem Statement**: 4.5 (#980) exports the *audit trail* in JSON Lines/CSV/SARIF, but the compliance screen's "Data export & portability" panel exports **contracts, consent log, invoices, audit chain, disputes, and templates** in **Parquet**, encrypted with a tenant **KMS key** (`arn:aws:kms…`) — whole-tenant portability is a different, unspecified capability.

**Solution/Scope**: A multi-entity export job covering all contract-domain entities (contracts + versions, consent log, invoices + payments, audit chain, disputes, templates), with per-entity selection, **Parquet** (and JSON Lines) output, **envelope encryption with a tenant-supplied KMS key**, one-time and scheduled runs, and delivery via download or S3 (reusing 4.5's delivery layer). Exports include chain-head hashes so recipients can verify integrity offline via 9.1 semantics.

**Acceptance Criteria**:
- Export selects any subset of the six entity groups and completes as an async job with progress
- Parquet output preserves typed columns; JSON Lines remains available for all entities
- Artifacts are envelope-encrypted with the configured tenant KMS key; unencrypted export requires explicit opt-in
- Scheduled exports run recurringly with delivery to S3 or download links
- Export manifests embed chain-head hashes enabling offline integrity verification

**Parallelism/Dependencies**: Extends 4.5 (#980); KMS configuration lives in 11.2; integrity hashes from 9.1. Parallel with 9.5.

**Technical Stack**: Parquet writers, KMS envelope encryption, job queue, S3 delivery.

**Part of Epic: Compliance, Audit & Dispute Operations**

---

## Epic 10 (#4277): Pact Operations & Release Intelligence

Operational depth for Epic 5 surfaced by `verification.html`, `matrix.html`, and `can-i-deploy.html`: on-demand and bulk verification, stale-pact remediation, an environment/deployed-version model with predictive gating, and cross-signal contract health.

### Summary Table

| #   | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|-----|-------|---------|--------|----------|-----|------------|------------------|
| 10.1 (#4278) | On-Demand & Bulk Verification Operations | Manual re-run, verify-all-stale, raw/downloadable logs with expected-vs-actual diffs, build+commit capture, run history, matrix search & rollups | `enhancement`, `contracts`, `pact`, `rest` | Yes | N | M | apiome-rest, apiome-ui, apiome-cli |
| 10.2 (#4279) | Stale-Pact Remediation & Verification Scheduling | Re-publish request workflow for stale pacts; per-tenant/contract cadence and threshold settings | `enhancement`, `contracts`, `pact` | Yes | N | M | apiome-rest, apiome-ui |
| 10.3 (#4280) | Environment Topology & Deploy Simulator | Deployed-versions dashboard, staging look-ahead with predicted-clear, named gate policies, gate history, CLI snippet | `enhancement`, `contracts`, `pact` | No | N | L | apiome-rest, apiome-ui, apiome-cli |
| 10.4 (#4281) | Contract Health Rollup & Verification Analytics | Fuse pact, SLA, and consent signals per contract; cross-signal dispute evidence; pass-rate and duration trends | `enhancement`, `contracts`, `pact` | No | N | M | apiome-rest, apiome-ui |

### Detailed Issue Descriptions

#### 10.1 (#4278) — On-Demand & Bulk Verification Operations

**Problem Statement**: 5.3 triggers verification on schema publish, pact publish, and nightly schedule only, and 5.4 defines a read-only grid — but `verification.html` has a manual "Re-run verification" button, a "Raw log" view, Copy/Download on the replay terminal, expected-vs-actual JSON body diffs, provider build + commit capture (`Build v3.2.0 · f3c7a91`), per-run trigger-provenance labels and durations, and `matrix.html` has "Verify all stale", a free-text pair filter, and a summary rollup (`18 pacts · 14 verified · 2 failing · 1 stale · 1 new`).

**Solution/Scope**: Add **operator-initiated verification** (single pair re-run; bulk verify-all-stale from the matrix) with concurrency guards; persist **trigger provenance** (schema publish / pact publish / nightly / manual / stale re-check) and **run duration** per run, shown in a recent-runs history panel with a KPI strip (contracted interactions · passing · failing · pass-rate % · last verified); capture the **provider build version and git commit** per run for attribution; provide **raw-log retrieval** and **copy/download** of replay output including structured expected-vs-actual body diffs; and upgrade the matrix with the **summary rollup counts**, **free-text pair search**, **counterparty grouping**, and a **filterable list view with hide-empty rows/columns** for large, sparse tenants.

**Acceptance Criteria**:
- Re-run (single) and verify-all-stale (bulk) are available in the UI and CLI, guarded against overlapping runs per pair
- Runs persist trigger provenance, duration, and provider build/commit; the runs panel and verdicts display them
- Raw logs are retrievable per run; replay output is copyable/downloadable with expected/actual diffs intact
- Matrix shows rollup counts and supports free-text search, counterparty grouping, and a list view that hides empty rows/columns
- Positive access-level confirmations (e.g. "aggregate-only clause honoured") render per consumer result

**Parallelism/Dependencies**: Extends 5.3/5.4; CLI additions ride 5.6. Parallel with 10.2.

**Technical Stack**: Worker queue, log storage, NextJS, apiome-cli.

**Part of Epic: Pact Operations & Release Intelligence**

---

#### 10.2 (#4279) — Stale-Pact Remediation & Verification Scheduling

**Problem Statement**: Staleness is only a matrix colour in 5.4, but `verification.html` run `#409` shows a workflow — "stale pact · re-publish requested" — and both screens reference a verification cadence ("on publish + nightly") and a configurable stale threshold with no settings surface anywhere.

**Solution/Scope**: A **stale-pact remediation loop**: when a pact exceeds the stale threshold, the system sends a re-publish request to the consumer party (notification + webhook via 11.3/5.6), tracks the request state (requested → acknowledged → re-published / expired), and escalates unanswered requests — mirroring 2.3's renewal-reminder pattern. Plus a **verification settings surface** (per-tenant defaults, per-contract overrides): cadence (on-publish, nightly, hourly, manual-only), stale threshold, and concurrency limits, giving 5.4's "configurable per tenant" threshold an actual screen.

**Acceptance Criteria**:
- Stale pacts automatically generate re-publish requests with tracked state and escalation on expiry
- Re-publish requests notify the consumer party via notification and webhook with the pact and contract references
- Verification cadence and stale threshold are configurable per tenant with per-contract overrides
- Stale-state transitions and re-publish requests emit 4.1 events
- The matrix stale cells link to the open re-publish request when one exists

**Parallelism/Dependencies**: Extends 5.3/5.4; delivery via 5.6/11.3; settings surface coordinates with 11.2. Parallel with 10.1.

**Technical Stack**: Scheduler, notification/webhook fan-out, settings tables.

**Part of Epic: Pact Operations & Release Intelligence**

---

#### 10.3 (#4280) — Environment Topology & Deploy Simulator

**Problem Statement**: 5.5's environment model AC is one line ("tracks which consumer versions are deployed where"), yet `can-i-deploy.html` reads a **staging** consumer version, detects it no longer uses the removed field, and predicts "once it reaches production this pair goes green" — plus a named, clause-bound **gate policy** descriptor (`contracts + pacts + consent · required by clause DS-2.6`), a pinned **matrix snapshot** timestamp, an in-UI **CLI snippet** button, a manual **Re-check**, and a **Gate history** link, none of which are specified.

**Solution/Scope**: Build the environment model into a visible **deployed-versions dashboard** (which pacticipant versions run in which environment, recorded via CLI/API on deploy — analogous to Pact Broker environments); extend the gate with a **simulator** that evaluates pending (staging) versions and answers what-if questions ("what does deploying X unblock/break?") including the predicted-clear look-ahead; make gates evaluate against a **pinned matrix snapshot** (timestamp shown, re-check re-pins); define **named gate policies** (which signal classes compose the gate — pacts, clause gates, consent — bound to a clause and rendered in the verdict banner); and add the **CLI snippet** copy affordance and a **gate history** view of past verdicts.

```
  environments: production ── consumer v4.2.1 (reads sku)   ⇒ gate: BLOCKED
                staging    ── consumer v4.3.0 (no sku)      ⇒ simulator: clears after promote
  gate(provider@v, env) = f(pact verdicts @ snapshot, clause gates, consent) per gate policy
```

**Acceptance Criteria**:
- Deploy recording (CLI/API) maintains per-environment pacticipant versions shown on a topology dashboard
- Simulator evaluates hypothetical promotions and reports which gate verdicts change, including predicted-clear guidance in unblock steps
- Gate verdicts pin and display the matrix snapshot they evaluated; Re-check re-evaluates against a fresh snapshot
- Gate policies are named, clause-bound, and rendered in the verdict banner; policy changes are contract events
- Gate history lists prior verdicts per pacticipant/environment; the UI offers a copyable CLI invocation for the current check

**Parallelism/Dependencies**: Extends 5.5/5.6; consumes 5.4 verdict data. Sequenced after 5.5.

**Technical Stack**: Environment/version tables, gate evaluator, NextJS, apiome-cli.

**Part of Epic: Pact Operations & Release Intelligence**

---

#### 10.4 (#4281) — Contract Health Rollup & Verification Analytics

**Problem Statement**: The matrix's failing-pairs panel links a pact failure to "the active uptime breach on `C7_c08d` · dispute evidence attached" — correlating signals across pact verification, SLA breaches, and disputes that the roadmap treats as separate silos; and run durations/pass rates are displayed but never trended.

**Solution/Scope**: A per-contract **health rollup** fusing verification strikes (5.3), SLA breach state (1.2/2.4), consent status (2.2/2.5), and open disputes (4.2) into one health signal with drill-down; **cross-signal correlation** that links a failing pact pair to concurrent breaches on the same contract and auto-attaches the combined evidence to an open dispute case; and **verification analytics** — pass-rate, flakiness (verdict churn), and mean verification duration trends per consumer/provider over time. Health feeds the 6.2 dashboard compliance context.

**Acceptance Criteria**:
- Health rollup computes per contract from pact, SLA, consent, and dispute signals with component drill-down
- A pact failure on a contract with an active SLA breach links both and can auto-attach combined evidence to an open dispute
- Trends render pass-rate, flakiness, and duration per pair over selectable windows
- Health state changes emit 4.1 events and surface on the contract dashboard

**Parallelism/Dependencies**: Consumes 5.3/5.4, 2.4, 2.2/2.5, 4.2; feeds 6.2. Sequenced after 10.1.

**Technical Stack**: Aggregation service, time-series queries, NextJS.

**Part of Epic: Pact Operations & Release Intelligence**

---

## Epic 11 (#4282): Platform Services & Enterprise Administration

Cross-cutting capabilities every other epic leans on, drawn directly from the mockup README's "Out of scope (not included)" list plus counterparty data rendered inline on every screen. These unblock 8.5 (tax metadata), 7.7 (renewal policies), 9.7 (KMS keys), 6.3 (template notifications), and 10.2 (re-publish nudges).

### Summary Table

| #   | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|-----|-------|---------|--------|----------|-----|------------|------------------|
| 11.1 (#4283) | Counterparty CRM | System of record for counterparties: profiles, contacts, AP/AR addresses, tax IDs, payment defaults | `enhancement`, `contracts`, `rest` | Yes | N | M | apiome-rest, apiome-db, apiome-ui |
| 11.2 (#4284) | Tenant Contract Policy Administration | Org-wide defaults: signing rules, retention, KMS keys, renewal policies, verification cadence, anchoring schedules | `enhancement`, `contracts` | Yes | N | M | apiome-ui, apiome-rest, apiome-db |
| 11.3 (#4285) | Contract Event Webhooks & Notification Center | Subscription config for contract lifecycle events with HMAC delivery and a notification preference center | `enhancement`, `contracts`, `rest` | Yes | N | M | apiome-rest, apiome-ui |
| 11.4 (#4286) | E-Signature Provider Integrations | DocuSign / Adobe Sign hand-off and PKI signing as alternatives to self-hosted click-to-sign | `enhancement`, `contracts` | Yes | N | M | apiome-rest, apiome-ui |
| 11.5 (#4287) | Smart-Contract Clause Execution & Metric Oracles (Exploratory) | On-chain enforcement of machine-readable clauses fed by metric oracles | `enhancement`, `contracts` | Yes | N | L | apiome-rest |

### Detailed Issue Descriptions

#### 11.1 (#4283) — Counterparty CRM

**Problem Statement**: Counterparty identity is rendered inline on every screen — colour-coded avatars (Hooli purple, Globex emerald, …), `dpo@hooli.com` as a revocation contact, VAT/EIN and PO blocks on invoices, "awaiting Wonka" signature rows — with no system of record; the README explicitly parks "counterparty profiles, contacts, AP/AR addresses, tax IDs" as out of scope.

**Solution/Scope**: A counterparty registry per tenant: organization profile (legal name, avatar colour, jurisdictions), **contacts by role** (signer, DPO, AP/AR, technical, dispute), **billing metadata** (AP/AR addresses, VAT/EIN/tax IDs, default PO handling, remit-to), and **payment/payout defaults** (feeding 3.3/8.4). Contracts reference counterparty records instead of duplicating party metadata; invoices (8.5), signing (1.5), recalls (2.5), and disputes (9.6) resolve their contact and tax data from the registry. Includes the stable avatar-colour convention from the mockup design language.

**Acceptance Criteria**:
- Counterparty records hold profile, role-based contacts, billing/tax metadata, and payment defaults
- Contract party references resolve to counterparty records; existing inline `party_metadata` migrates
- Invoices pull VAT/EIN/PO/remit-to from the registry; recall and dispute notices route to the role-appropriate contact
- Avatar colour is stable per counterparty across all screens
- Counterparty edits are audited; merging duplicate records preserves contract references

**Parallelism/Dependencies**: Unblocks 8.5; consumed by 1.5/2.5/9.6. Parallel with 11.2/11.3.

**Technical Stack**: PostgreSQL counterparty tables, migration from `party_metadata`, REST, NextJS.

**Part of Epic: Platform Services & Enterprise Administration**

---

#### 11.2 (#4284) — Tenant Contract Policy Administration

**Problem Statement**: The README parks "org-wide defaults for signing rules, retention, KMS keys" as out of scope, yet the mockups dangle entry points everywhere: "Renewal policies" on `usage.html`, "Configure schedules" on `compliance.html`, "Configure all →" on `data-sharing.html`, the KMS ARN in the export panel, and 5.4's "configurable per tenant" stale threshold — with no settings surface owning any of it.

**Solution/Scope**: A tenant administration area for contract-domain policy: **signing rules** (who may sign, required roles, hash binding on/off), **retention defaults** (event/usage/consent retention windows), **KMS key configuration** (for 9.7 exports and encrypted artifacts), **renewal policies** (default renewal mode, notification lead times, quota-gating defaults for 7.7), **verification defaults** (cadence, stale threshold for 10.2), and **anchoring schedules** (backend enablement and presets for 9.2). Contract-level settings inherit from tenant policy with explicit override tracking.

**Acceptance Criteria**:
- Tenant policies cover signing, retention, KMS, renewal, verification, and anchoring domains
- New contracts and templates inherit tenant defaults; overrides are visible and audited
- KMS key configuration validates key access before acceptance and is consumed by 9.7
- Policy changes emit 4.1 events and apply prospectively
- Policy administration is permission-gated to tenant administrators

**Parallelism/Dependencies**: Consumed by 6.5, 7.7, 9.2, 9.7, 10.2. Parallel with 11.1/11.3.

**Technical Stack**: Settings tables with inheritance, NextJS admin screens, REST.

**Part of Epic: Platform Services & Enterprise Administration**

---

#### 11.3 (#4285) — Contract Event Webhooks & Notification Center

**Problem Statement**: 4.5 delivers audit exports and 5.6 delivers pact/gate webhooks, but general contract lifecycle events — signed, activated, expiring, consent revoked, recall issued, usage threshold crossed, renewal due, invoice issued, dispute opened — have no subscription surface; the README notes webhooks appear only as "synced to audit log" footers.

**Solution/Scope**: A webhook/notification configuration screen where each party subscribes endpoints (or notification channels) to contract-event classes, with per-subscription event filters, HMAC signing, retry with dead-lettering, and delivery logs — built on the same delivery layer as 4.5/5.6 so pact events and lifecycle events share infrastructure. Includes a per-user **notification preference center** (email/in-app per event class) replacing the ad-hoc notification mentions scattered through 1.4, 2.3, 2.5, and 3.3.

**Acceptance Criteria**:
- Subscriptions target event classes with optional per-contract filters; payloads include contract ID, clause references, and evidence URLs (parity with 5.6)
- Deliveries are HMAC-signed with retry/backoff and a dead-letter queue; delivery logs are viewable per subscription
- Notification preference center controls email/in-app delivery per event class per user
- All existing roadmap notification triggers (renewal reminders, recall notices, payment failures) route through this layer
- Subscription changes are audited as 4.1 events

**Parallelism/Dependencies**: Reuses 4.5 (#980) delivery; supersedes scattered notification logic; consumed by 6.3, 10.2. Parallel with 11.1/11.2.

**Technical Stack**: Webhook workers, HMAC signing, dead-letter queue, NextJS config UI.

**Part of Epic: Platform Services & Enterprise Administration**

---

#### 11.4 (#4286) — E-Signature Provider Integrations

**Problem Statement**: 1.5 (#961) is deliberately self-hosted click-to-sign ("enterprise tier may add PKI signing"), and the README excludes provider hand-off — but enterprise counterparties frequently mandate DocuSign or Adobe Sign, making the absence a deal blocker rather than a nice-to-have.

**Solution/Scope**: A signing-provider abstraction with **DocuSign** and **Adobe Sign** adapters: initiating signature hands the signed-document envelope to the provider, tracks envelope status via provider webhooks, and records the completed signature (with provider evidence ID and certificate) in the existing `contract_signatures` trail — so 1.5's activation logic is unchanged regardless of the signing channel. Optional **PKI signing** (tenant certificate) for the self-hosted path, aligning with 6.5's hash binding.

**Acceptance Criteria**:
- Contracts can designate a signing channel: self-hosted (default), DocuSign, or Adobe Sign
- Provider envelopes are created from the signed PDF; status webhooks update signature state in near-real time
- Completed provider signatures record provider evidence IDs and land in the same immutable signature trail
- Activation semantics (all required parties signed) are channel-agnostic
- Provider outage falls back gracefully with re-initiation, never double-signing

**Parallelism/Dependencies**: Extends 1.5 (#961); complements 6.5. Parallel within Epic 11.

**Technical Stack**: DocuSign/Adobe Sign APIs, provider webhook handlers, adapter abstraction.

**Part of Epic: Platform Services & Enterprise Administration**

---

#### 11.5 (#4287) — Smart-Contract Clause Execution & Metric Oracles (Exploratory)

**Problem Statement**: The README bounds the cryptographic surface at audit anchoring (4.4/9.2), but the product thesis — machine-readable, enforceable agreements — points one step further: clauses whose consequences execute automatically on-chain, fed by attested metric inputs, for counterparties that don't trust each other's meters.

**Solution/Scope**: Exploratory track: compile a constrained subset of clause types (uptime credit tiers, usage overage) to on-chain escrow/settlement logic; feed metrics via **oracles** that publish signed, anchored metering attestations (building on 9.1 chain hashes as the attestation source); execute consequences (credit release from escrow) automatically at period close. Explicitly gated behind a design review — this issue produces a prototype and an adoption/risk assessment, not GA functionality.

**Acceptance Criteria**:
- A design document maps which clause types can compile to on-chain execution and which cannot
- Prototype executes a tiered uptime-credit clause on a testnet from oracle-attested metrics
- Oracle attestations are verifiable against the 9.1 event chain
- Risk assessment covers key custody, gas economics, dispute interaction (9.6), and regulatory posture
- Go/no-go recommendation with a phased adoption path

**Parallelism/Dependencies**: Builds on 9.1/9.2; interacts with 9.6. Fully parallel; lowest priority in the epic.

**Technical Stack**: Solidity/testnet prototype, oracle attestation service, design documentation.

**Part of Epic: Platform Services & Enterprise Administration**

---

## Parallel Work Guide

**Epic 1 — Contract Builder & Templates**:
Issues 1.1 (Data Model), 1.2 (SLA Editor), 1.3 (Template Library), and 1.6 (Dashboard) can be developed in parallel as they operate on independent UI pages. Issue 1.4 (Negotiation Workflow) depends on 1.1 for the contract data model and versioning. Issue 1.5 (Signing & Activation) depends on 1.4 for the approval state machine.

**Epic 2 — Data Sharing & Consent Management**:
Issues 2.1 (Schema-Based Contracts) and 2.2 (Consent Tracking) can be developed in parallel as they handle independent data models. Issue 2.3 (Expiration & Renewal) depends on 2.2 for consent expiration integration. Issue 2.4 (Data Usage Monitoring) depends on 2.1 for shared schema definitions. Issue 2.5 (Consent Revocation) depends on 2.2 and 2.4.

**Epic 3 — Billing & Revenue Integration**:
Issues 3.1 (Usage Metering) and 3.3 (Payment Gateway) can be developed in parallel. Issue 3.2 (Invoice Generation) depends on 3.1 for metering data. Issue 3.4 (Revenue Sharing) depends on 3.2 for invoice amounts. Issue 3.5 (Billing Dashboard) depends on 3.2 and 3.3.

**Epic 4 — Audit Trail & Compliance**:
Issues 4.1 (Event Log), 4.3 (Compliance Reporting), 4.4 (Blockchain Anchoring), and 4.5 (Audit Export) can be developed in parallel as they address independent capabilities. Issue 4.2 (Dispute Resolution) depends on 4.1 for event data assembly.

**Epic 5 — Contract Testing & Deploy Gating (Pact)**:
Issues 5.1 (Pact Data Model) and 5.2 (Consumer Capture) can be developed in parallel once 2.1 lands. Issue 5.3 (Provider Verification) depends on both and on 1.2 for clause binding. Issues 5.4 (Matrix) and 5.5 (Can-I-Deploy) depend on 5.3 for verdict data and can proceed in parallel with each other. Issue 5.6 (CI Integration) depends on 5.5 and reuses 4.5's webhook delivery.

**Epic 6 — Contract Authoring & Lifecycle Enhancements**:
All six issues extend already-filed Epic 1 issues and are mutually parallel. 6.1 (Clause Catalog) should land before 7.6's overage pricing consumes tiered consequences. 6.2 (Dashboard Analytics) degrades gracefully until 8.6 supplies revenue figures. 6.6 (Internal Contracts) only needs 1.1.

**Epic 7 — Data Sharing Enforcement & Intelligence**:
Issues 7.1 (PII), 7.2 (Aggregate Grants), 7.5 (Clause Refinements), and 7.8 (Consent Ops) are parallel. 7.3 (Gateway Enforcement) depends on 7.2 and the 7.6 quota model. 7.4 (Lineage & Recall) depends on 2.4 usage events. 7.7 (Renewal Recommendations) depends on 7.6 usage analytics.

**Epic 8 — Billing Operations & Financial Integrations**:
8.1 (Pricing Builder) is the MVP gate — 3.2 invoicing is blocked without it — and is parallel with 8.3 (ERP) and 8.4 (Rails). 8.2 (Billing Run) orchestrates the others and comes after 8.1 + 3.2. 8.5 (Invoice Enhancements) needs 3.2, 11.1, and 7.6. 8.6 (KPIs) is parallel with 8.5.

**Epic 9 — Compliance, Audit & Dispute Operations**:
9.1 (Hash Chaining) should land early — 7.8, 6.5, 9.2, and 9.7 all reuse its primitives. 9.2 (Multi-Adapter Anchoring), 9.3 (GRC), and 9.4 (DSAR, after 7.1) are parallel. 9.5 (Auditor Vault) follows 9.3. 9.6 (Mediation) follows 4.2 and pairs with 8.5's line-item disputes. 9.7 (Portability) needs 9.1 and 11.2's KMS config.

**Epic 10 — Pact Operations & Release Intelligence**:
10.1 (Verification Ops) and 10.2 (Stale Remediation) are parallel once 5.3/5.4 land. 10.3 (Environment Topology & Simulator) follows 5.5. 10.4 (Health Rollup) follows 10.1 and consumes signals from Epics 2, 4, and 5.

**Epic 11 — Platform Services & Enterprise Administration**:
All five issues are mutually parallel and should start early relative to their consumers: 11.1 (Counterparty CRM) unblocks 8.5; 11.2 (Tenant Policy) unblocks 7.7, 9.7, and 10.2; 11.3 (Webhooks) unblocks 6.3 and 10.2 notifications. 11.4 (E-Signature) extends 1.5 independently. 11.5 (Smart Contracts) is exploratory and last.

**Cross-Epic Parallelism**: Epic 1 (Contract Builder) and Epic 4 (Audit Trail) can begin simultaneously—the event log (4.1) should be integrated early as other epics emit events. Epic 2 (Data Sharing) depends on Epic 1 for the contract data model. Epic 3 (Billing) depends on Epic 2 for usage data from data sharing contracts. Epic 5 (Contract Testing) depends on Epic 2 for data-sharing clauses and on 1.2 for SLA clause binding, but shares broker infrastructure with the Testing & QA roadmap's Epic 6 (#1914) — coordinate to avoid duplicating pact storage. Among the gap-analysis epics, Epic 11 is the platform substrate (start 11.1–11.3 early), 9.1 is the shared integrity primitive, and 8.1 is on the MVP critical path; Epics 6, 7, and 10 extend their parent epics and can trail them issue-by-issue. Within those constraints, UI work across all epics can proceed in parallel.

---

## Work To Be Done (Ordered)

1. **Foundation (parallel)**: 1.1 Contract Data Model · 4.1 Immutable Event Log — everything else emits events
2. **Builder MVP (parallel)**: 1.2 SLA Editor · 1.3 Template Library · 1.6 Dashboard
3. **Agreement flow**: 1.4 Negotiation → 1.5 Signing & Activation
4. **Data sharing (parallel)**: 2.1 Schema-Based Contracts · 2.2 Consent Tracking
5. **Lifecycle**: 2.3 Expiration & Renewal → 2.4 Usage Monitoring → 2.5 Revocation & Recall
6. **Pact MVP (parallel)**: 5.1 Pact Data Model & Contract Binding · 5.2 Consumer Pact Capture
7. **Verification**: 5.3 Provider Verification & SLA Clause Binding
8. **Billing (parallel)**: 8.1 Pricing Model Builder · 3.1 Usage Metering · 3.3 Payment Gateway, then 3.2 Invoices → 3.4 Revenue Sharing → 3.5 Billing Dashboard
9. **Gating (parallel)**: 5.4 Compatibility Matrix · 5.5 Can-I-Deploy Gate, then 5.6 CI Integration & Gate Events
10. **Compliance (parallel)**: 4.2 Disputes · 4.3 Compliance Reporting · 4.4 Blockchain Anchoring · 4.5 Audit Export
11. **Platform substrate (parallel)**: 11.1 Counterparty CRM · 11.2 Tenant Policy Administration · 11.3 Contract Event Webhooks · 9.1 Hash Chaining & Integrity Verifier — shared services the remaining phases consume
12. **Authoring depth (parallel)**: 6.1 Clause Catalog & Tiers · 6.3 Template Governance · 6.4 Negotiation Enhancements · 6.5 Signing Integrity · 6.6 Internal Contracts, then 6.2 Dashboard Analytics (after 8.6)
13. **Sharing enforcement**: 7.1 PII Classification · 7.2 Aggregate Grants · 7.5 Clause Refinements · 7.8 Consent Ops (parallel), then 7.6 Quotas & Overage → 7.3 Gateway Enforcement → 7.4 Lineage & Recall → 7.7 Renewal Recommendations
14. **Billing operations**: 8.3 ERP Reconciliation · 8.4 Payment Rails · 8.6 Revenue KPIs (parallel), then 8.2 Billing Run Orchestration → 8.5 Invoice Disputes & Tax Metadata
15. **Trust operations**: 9.2 Multi-Adapter Anchoring · 9.3 GRC Control Mapping · 9.4 DSAR (parallel), then 9.5 Auditor Vault · 9.6 Mediation & Settlement · 9.7 Data Portability
16. **Release intelligence**: 10.1 Verification Ops · 10.2 Stale-Pact Remediation (parallel), then 10.3 Environment Topology & Simulator → 10.4 Contract Health Rollup
17. **Enterprise signing & exploration**: 11.4 E-Signature Providers · 11.5 Smart-Contract Execution (exploratory)
