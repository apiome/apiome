# Objectified: Contracts (SLA/API Agreements) - Feature Roadmap

> Smart contract generation and management for API agreements, SLAs, and data sharing between organizations. Contracts turns informal API partnerships into machine-readable, enforceable agreements with integrated billing, consent management, and an immutable audit trail—eliminating spreadsheet-based SLA tracking and manual invoice reconciliation.
>
> **Revenue Model**: Per-contract pricing, enterprise legal package
>
> **Tech Stack**: NextJS App Router, Radix UI primitives, REST/OpenAPI 3.1, PostgreSQL with JSONB contract storage, Stripe/payment gateway integration, optional blockchain anchoring
>
> **Last Updated**: April 2, 2026

---

## MVP Definition

- Contract builder with form-based SLA definition (uptime %, latency targets, rate limits)
- Template library with pre-built contract templates (API agreement, data sharing, DPA)
- Schema-based data sharing contract linking Objectified schemas to usage terms
- Basic consent tracking with expiration dates and renewal reminders
- Usage metering pipeline feeding contract compliance checks
- Invoice generation from metered usage with PDF export
- Immutable contract event log with timestamped state transitions
- Contract status dashboard showing active, expiring, and violated contracts

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
| 2.1 (#964) | Schema-Based Data Sharing Contracts | Link Objectified schemas to data sharing agreements | `enhancement`, `contracts`, `mvp`, `rest` | Yes |
| 2.2 (#965) | Consent Tracking Engine | Track and manage consent for data sharing with audit trail | `enhancement`, `contracts`, `mvp`, `rest` | Yes |
| 2.3 (#966) | Expiration & Renewal Management | Automated expiration handling and renewal workflows | `enhancement`, `contracts`, `mvp` | No |
| 2.4 (#967) | Data Usage Monitoring | Track actual data usage against sharing agreement terms | `enhancement`, `contracts`, `rest` | No |
| 2.5 (#968) | Consent Revocation & Data Recall | Handle consent withdrawal and downstream data cleanup | `enhancement`, `contracts` | No |

### Detailed Issue Descriptions

#### 2.1 (#964) — Schema-Based Data Sharing Contracts

Schema-Based Data Sharing Contracts bind Objectified schema definitions to legal data sharing agreements. Instead of describing shared data in prose, the contract directly references specific schema classes and properties, creating a machine-readable specification of exactly what data is shared, in what format, and with what constraints.

The data sharing editor at `/app/contracts/[id]/data-sharing` renders a schema picker that lets users browse their Objectified schemas and select specific classes and properties to include in the sharing agreement. Selected schema elements are displayed in a tree view with checkboxes for individual properties. For each included element, users can set access restrictions (read, write, aggregate-only) and data handling requirements (encryption-at-rest, no-export, retention-limit).

Backend endpoints include `POST /api/v1/contracts/{id}/data-sharing` (define shared schemas), `GET /api/v1/contracts/{id}/data-sharing` (retrieve shared schema definitions), and `PUT /api/v1/contracts/{id}/data-sharing` (update). The `contract_data_sharing` table links `contract_id` to `schema_capture_class_id` with JSONB columns for `included_properties`, `access_level`, and `handling_requirements`. Validation ensures referenced schemas exist and are in a published state.

**Acceptance Criteria**:
- Schema picker browses Objectified schemas and allows property-level selection
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

Payment Gateway Integration connects the invoicing system to external payment processors for automated payment collection. The initial integration targets Stripe, with the architecture designed to support additional gateways (PayPal, wire transfer) via a payment provider abstraction layer. Payment methods are stored securely with the gateway—only tokenized references are kept in Objectified.

The payment configuration page at `/app/contracts/[id]/billing/payment` allows the consumer party to add payment methods via Stripe's embedded payment element (Stripe.js). The provider party configures their Stripe connect account for receiving payments. Automatic payment collection attempts to charge the consumer's payment method when an invoice is issued, with configurable retry logic for failed payments.

Backend endpoints include `POST /api/v1/billing/payment-methods` (add via Stripe token), `GET /api/v1/billing/payment-methods` (list), `POST /api/v1/contracts/{id}/invoices/{invoiceId}/pay` (manual payment), and webhook handler at `/api/v1/billing/webhooks/stripe` for payment status updates. The `payment_transactions` table records `invoice_id`, `gateway`, `gateway_transaction_id`, `amount`, `currency`, `status`, and `processed_at`.

**Acceptance Criteria**:
- Stripe integration supports card and ACH payment methods via Stripe.js
- Payment methods are stored as tokenized references—no raw card data in Objectified
- Automatic payment collection fires when invoices are issued with configurable retry (3 attempts)
- Failed payments trigger notifications to both parties with a manual payment fallback
- Webhook handler processes Stripe events for payment confirmation and failure
- Payment provider abstraction layer supports adding new gateways without modifying core logic

**Part of Epic: Billing & Revenue Integration**

---

#### 3.4 (#973) — Revenue Sharing Calculator

The Revenue Sharing Calculator computes revenue splits for contracts involving multiple parties. Revenue sharing rules are defined per contract, specifying percentage or fixed-amount splits between provider, platform (Objectified), and optional intermediaries. The calculator applies these rules to each invoice, generating a distribution breakdown that shows how invoice proceeds are allocated.

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

## Parallel Work Guide

**Epic 1 — Contract Builder & Templates**:
Issues 1.1 (Data Model), 1.2 (SLA Editor), 1.3 (Template Library), and 1.6 (Dashboard) can be developed in parallel as they operate on independent UI pages. Issue 1.4 (Negotiation Workflow) depends on 1.1 for the contract data model and versioning. Issue 1.5 (Signing & Activation) depends on 1.4 for the approval state machine.

**Epic 2 — Data Sharing & Consent Management**:
Issues 2.1 (Schema-Based Contracts) and 2.2 (Consent Tracking) can be developed in parallel as they handle independent data models. Issue 2.3 (Expiration & Renewal) depends on 2.2 for consent expiration integration. Issue 2.4 (Data Usage Monitoring) depends on 2.1 for shared schema definitions. Issue 2.5 (Consent Revocation) depends on 2.2 and 2.4.

**Epic 3 — Billing & Revenue Integration**:
Issues 3.1 (Usage Metering) and 3.3 (Payment Gateway) can be developed in parallel. Issue 3.2 (Invoice Generation) depends on 3.1 for metering data. Issue 3.4 (Revenue Sharing) depends on 3.2 for invoice amounts. Issue 3.5 (Billing Dashboard) depends on 3.2 and 3.3.

**Epic 4 — Audit Trail & Compliance**:
Issues 4.1 (Event Log), 4.3 (Compliance Reporting), 4.4 (Blockchain Anchoring), and 4.5 (Audit Export) can be developed in parallel as they address independent capabilities. Issue 4.2 (Dispute Resolution) depends on 4.1 for event data assembly.

**Cross-Epic Parallelism**: Epic 1 (Contract Builder) and Epic 4 (Audit Trail) can begin simultaneously—the event log (4.1) should be integrated early as other epics emit events. Epic 2 (Data Sharing) depends on Epic 1 for the contract data model. Epic 3 (Billing) depends on Epic 2 for usage data from data sharing contracts. Within those constraints, UI work across all epics can proceed in parallel.
