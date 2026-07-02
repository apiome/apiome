# Apiome: Monetization & Business - Feature Roadmap

> Platform monetization engine that manages tiered subscriptions, tracks usage-based billing metrics, integrates with Stripe for payment processing, and provides self-service plan management—enabling sustainable SaaS revenue from schema design tooling.
>
> **Revenue Model**: Self-referential—this product IS the monetization layer
>
> **Tech Stack**: NextJS App Router, Radix UI primitives, Stripe.js, Stripe API, REST/OpenAPI 3.1, PostgreSQL, Redis (usage counters)
>
> **Last Updated**: April 2, 2026

---

## MVP Definition

- Pricing plan data model with Free, Pro, Team, and Enterprise tiers and feature entitlements
- Feature gating engine that enforces plan limits (project count, schema visibility, team size)
- Self-service plan selection with upgrade/downgrade flows and proration
- Trial period management with automatic conversion and expiration handling
- Usage metering pipeline capturing API calls, schema count, storage, and team size
- Quota enforcement with soft limits, hard limits, and grace periods
- Stripe subscription integration with recurring billing and webhook handling
- Payment method management with card and ACH support via Stripe.js
- Self-service billing portal with invoice history and plan changes

---

## Epic 1: Pricing Tiers & Plan Management

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 1.1 (#1337) | Plan Data Model & CRUD API | Core pricing plan entity with tier definitions and feature entitlements | `ai-generated`, `enhancement`, `monetization`, `mvp`, `rest` | Yes |
| 1.2 (#1357) | Feature Gating Engine | Runtime enforcement of plan limits across the platform | `ai-generated`, `enhancement`, `monetization`, `mvp` | Yes |
| 1.3 (#1368) | Plan Selection & Upgrade/Downgrade Flows | Self-service tier changes with proration and immediate activation | `ai-generated`, `enhancement`, `monetization`, `mvp`, `rest` | No |
| 1.4 (#1379) | Trial Period Management | Time-limited free access to paid features with conversion tracking | `ai-generated`, `enhancement`, `monetization`, `rest` | Yes |

### Detailed Issue Descriptions

---

#### 1.1 (#1337) — Plan Data Model & CRUD API

The plan data model defines the pricing tiers that drive all monetization behavior. Each plan entity contains a name, slug, display order, monthly and annual price (in cents to avoid floating-point issues), a feature entitlements object, usage quotas, and a visibility flag (public plans appear on the pricing page; private plans are for enterprise or legacy). The four launch tiers—Free, Pro ($29/month), Team ($99/month), and Enterprise (custom)—are seeded as default plans.

Feature entitlements are stored as a JSONB column mapping feature keys to their allowed values. For example, `max_projects: 3` for Free, `max_projects: -1` (unlimited) for Pro, `private_schemas: false` for Free, `sso_enabled: true` for Enterprise. This structure lets the feature gating engine (1.2) perform fast lookups without joining multiple tables. Each plan also declares a `usage_quotas` JSONB object specifying monthly limits for API calls, schema count, and storage bytes.

```
┌──────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   plans      │     │  subscriptions   │     │  organizations   │
├──────────────┤     ├──────────────────┤     ├──────────────────┤
│ id           │◄────│ plan_id          │     │ id               │
│ name         │     │ organization_id  │────▶│ name             │
│ slug         │     │ status           │     │ slug             │
│ price_monthly│     │ current_period_  │     │ owner_id         │
│ price_annual │     │   start          │     └──────────────────┘
│ entitlements │     │ current_period_  │
│ usage_quotas │     │   end            │
│ trial_days   │     │ stripe_sub_id    │
│ is_public    │     │ trial_ends_at    │
│ display_order│     └──────────────────┘
└──────────────┘
```

REST endpoints follow standard CRUD: `POST /api/v1/plans` (create plan, admin only), `GET /api/v1/plans` (list public plans), `GET /api/v1/plans/{id}` (detail with entitlements), `PUT /api/v1/plans/{id}` (update plan), and `DELETE /api/v1/plans/{id}` (soft-delete only). An additional endpoint `GET /api/v1/plans/compare` returns a matrix of all public plans with their entitlements side-by-side for the pricing page. The OpenAPI 3.1 spec defines `Plan`, `PlanEntitlements`, and `UsageQuotas` schemas with strict typing.

The admin management page at `/app/admin/plans` renders a Radix `Table` of all plans with inline editing via Radix `Dialog`. Each plan row shows name, price, subscriber count, and status. Creating or editing a plan opens a form with Radix `TextField` for name and price, a JSON editor for entitlements, and Radix `Switch` for visibility toggle.

**Acceptance Criteria**

- Plan entity stores name, slug, monthly/annual price, entitlements, usage quotas, and visibility
- Four default plans (Free, Pro, Team, Enterprise) are seeded on first deployment
- Entitlements are stored as typed JSONB with feature keys mapping to allowed values
- `GET /api/v1/plans/compare` returns a side-by-side comparison matrix for the pricing page
- Plan deletion is soft-delete only; active subscriptions prevent deletion
- Admin UI at `/app/admin/plans` supports CRUD with Radix `Table` and `Dialog` components
- OpenAPI 3.1 spec is published and kept in sync with the implementation

**Part of Epic: Pricing Tiers & Plan Management**

---

#### 1.2 (#1357) — Feature Gating Engine

The feature gating engine is the runtime enforcement layer that checks every permission-sensitive action against the organization's current plan entitlements. When a user attempts to create a fourth project on the Free tier (limit: 3), the engine rejects the action with a clear upgrade prompt. When a Free-tier user tries to make a schema private, the engine blocks it and surfaces the Pro tier as the unlock path.

The engine exposes a server-side utility `checkEntitlement(orgId, featureKey, requestedValue?)` that resolves the organization's active subscription, loads the plan's entitlements (cached in Redis with a 5-minute TTL), and evaluates the check. For boolean features (`private_schemas`, `sso_enabled`), the check is a simple lookup. For numeric features (`max_projects`, `max_team_members`), the engine counts the current usage and compares it against the limit. The function returns `{ allowed: boolean, limit: number | null, current: number | null, upgradePlanSlug: string | null }`.

On the frontend, a `<GatedFeature featureKey="private_schemas">` React component wraps any feature that requires plan verification. If the feature is not available on the current plan, the component renders a Radix `Tooltip` explaining the restriction and a call-to-action linking to the upgrade page. This prevents users from encountering hard errors—they see a contextual upsell instead.

The gating engine also supports a `checkQuota(orgId, metric)` function for usage-based limits. This integrates with the usage metering pipeline (2.1) to compare current-period consumption against plan quotas. Quota checks return `{ allowed: boolean, limit: number, consumed: number, remaining: number }`.

**Acceptance Criteria**

- `checkEntitlement` resolves plan limits in < 10ms using Redis-cached entitlements
- Boolean features (private schemas, SSO) are gated with clear upgrade prompts
- Numeric features (project count, team size) compare current usage against plan ceiling
- `<GatedFeature>` component renders contextual upsell UI with Radix `Tooltip` when blocked
- `checkQuota` integrates with usage counters for API call and storage limits
- Entitlement cache invalidates within 60 seconds of a plan change or subscription update
- Free-tier hard limits cannot be bypassed through API calls or direct database manipulation

**Part of Epic: Pricing Tiers & Plan Management**

---

#### 1.3 (#1368) — Plan Selection & Upgrade/Downgrade Flows

Plan changes are the revenue growth engine. This issue builds the self-service upgrade and downgrade flows that let organizations change their subscription tier without contacting sales. Upgrades take effect immediately with prorated charges for the remainder of the billing period. Downgrades take effect at the end of the current billing period to avoid mid-cycle feature loss.

The pricing page at `/app/pricing` displays all public plans in a comparison grid using Radix `Card` components. Each card shows the plan name, price, feature list with check/cross indicators, and a CTA button ("Current Plan", "Upgrade", "Downgrade", or "Contact Sales" for Enterprise). The comparison grid highlights the recommended plan based on the organization's current usage patterns.

When upgrading, the flow collects or confirms a payment method (delegating to issue 3.2), shows a proration preview from the Stripe API (`GET /api/v1/subscriptions/preview-change?targetPlanId={id}`), and confirms the change. The backend calls `PUT /api/v1/subscriptions/{orgId}` with the target plan, which updates the Stripe subscription with proration and immediately updates the local entitlements cache.

Downgrading presents a retention dialog using Radix `AlertDialog` that explains which features will be lost, offers a discount or extended trial as a retention incentive, and requires explicit confirmation. If the organization exceeds the target plan's limits (e.g., 10 projects but downgrading to Free with a 3-project limit), the dialog lists the assets that must be archived or deleted before the downgrade can proceed.

**Acceptance Criteria**

- Pricing page renders a plan comparison grid with feature-by-feature breakdown
- Upgrades take effect immediately with prorated charges shown before confirmation
- Downgrades take effect at period end; features remain available until then
- Downgrade flow warns about features and assets that exceed the target plan's limits
- Retention dialog offers discount or trial extension before confirming downgrade
- `PUT /api/v1/subscriptions/{orgId}` synchronizes the change with Stripe and invalidates caches
- Enterprise tier shows "Contact Sales" instead of self-service upgrade

**Part of Epic: Pricing Tiers & Plan Management**

---

#### 1.4 (#1379) — Trial Period Management

Trials are the primary conversion mechanism from Free to paid tiers. This issue builds the trial lifecycle: initiation, feature unlock, countdown notifications, and automatic conversion or expiration. When an organization on the Free tier starts a trial, they gain full access to Pro-tier features for a configurable duration (default: 14 days) without providing a payment method upfront.

Trial state is tracked on the subscription record with `trial_ends_at` and `trial_plan_id` fields. During the trial, `checkEntitlement` resolves against the trial plan's entitlements rather than the base plan. A daily job checks for expiring trials and sends notification emails at 7 days, 3 days, and 1 day before expiration. At expiration, organizations with a payment method on file are automatically converted to a paid subscription. Organizations without a payment method revert to Free-tier entitlements.

The trial experience surfaces a persistent banner at the top of the application using a Radix `Callout` component showing "Trial: N days remaining" with a link to add a payment method and convert. The trial status endpoint `GET /api/v1/subscriptions/{orgId}/trial` returns `{ active: boolean, plan: string, daysRemaining: number, endsAt: string }`.

Backend endpoints include `POST /api/v1/subscriptions/{orgId}/start-trial` (initiate trial), `POST /api/v1/subscriptions/{orgId}/convert-trial` (early conversion), and the expiration job runs via a scheduled worker. Trials are limited to one per organization per plan tier to prevent abuse. The admin panel at `/app/admin/trials` shows active trials with conversion rates using Radix `Table` and `Badge` components.

**Acceptance Criteria**

- Trial grants full access to the trial plan's features for the configured duration
- Notification emails fire at 7, 3, and 1 day before trial expiration
- Automatic conversion activates paid subscription when payment method is on file
- Organizations without payment method revert to Free-tier at trial expiration
- Persistent trial banner shows days remaining with conversion CTA
- One trial per organization per plan tier; re-trials are blocked
- Admin panel displays active trials, conversion rate, and churn-at-expiry metrics

**Part of Epic: Pricing Tiers & Plan Management**

---

## Epic 2: Usage Metering & Overage Billing

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 2.1 (#1399) | Usage Event Ingestion Pipeline | Capture and stream billable usage events to Redis counters | `ai-generated`, `enhancement`, `monetization`, `mvp`, `rest` | Yes |
| 2.2 (#1413) | Usage Aggregation & Quota Enforcement | Roll up counters into billing-period totals and enforce hard limits | `ai-generated`, `enhancement`, `monetization`, `mvp` | No |
| 2.3 (#1425) | Overage Calculation Engine | Compute overage charges when usage exceeds plan quotas | `ai-generated`, `enhancement`, `monetization`, `rest` | No |
| 2.4 (#1435) | Usage Dashboard & Alerts | Self-service usage visibility with threshold notifications | `ai-generated`, `enhancement`, `monetization`, `mvp` | Yes |

### Detailed Issue Descriptions

---

#### 2.1 (#1399) — Usage Event Ingestion Pipeline

Every billable action on the platform emits a usage event. This issue builds the ingestion pipeline that captures events from API middleware, schema operations, and storage mutations, then feeds them into Redis counters for real-time quota enforcement and PostgreSQL for durable billing records.

The pipeline uses a lightweight middleware layer that intercepts API requests and emits events to a Redis stream keyed by `usage:{orgId}:{metric}:{period}`. Four metrics are tracked: `api_calls` (incremented per REST API request), `schema_count` (gauged on schema create/delete), `storage_bytes` (gauged on schema capture size changes), and `team_members` (gauged on member invite/remove). Stream events include `organization_id`, `metric`, `delta`, `timestamp`, and `request_metadata` (endpoint, method, response status).

```
┌────────────┐     ┌────────────┐     ┌────────────┐     ┌────────────┐
│  API       │     │  Metering  │     │   Redis    │     │  Aggregation│
│  Request   │────▶│  Middleware │────▶│   Stream   │────▶│  Worker    │
└────────────┘     └────────────┘     └────────────┘     └────────────┘
                                            │                    │
                                            │  INCR counter      │  INSERT
                                            ▼                    ▼
                                      ┌────────────┐     ┌────────────┐
                                      │   Redis    │     │ PostgreSQL │
                                      │   Counter  │     │ usage_     │
                                      │ (real-time)│     │ records    │
                                      └────────────┘     └────────────┘
```

A background aggregation worker consumes the Redis stream every 60 seconds, batches events, and writes durable `usage_records` rows to PostgreSQL partitioned by month. The Redis counters provide real-time reads for quota enforcement (2.2) while PostgreSQL serves as the source of truth for billing calculations. REST endpoints include `GET /api/v1/usage/{orgId}/current` (real-time counters from Redis) and `GET /api/v1/usage/{orgId}/history?from={iso}&to={iso}` (durable records from PostgreSQL).

The middleware adds < 2ms p99 latency to API requests by performing fire-and-forget writes to the Redis stream. If Redis is temporarily unavailable, events are buffered in memory with a 1,000-event cap and flushed when the connection recovers.

**Acceptance Criteria**

- API calls, schema count, storage bytes, and team member count are tracked as usage metrics
- Redis stream ingestion adds < 2ms p99 latency to API request processing
- Aggregation worker flushes events to PostgreSQL within 60 seconds of occurrence
- `GET /api/v1/usage/{orgId}/current` returns real-time counters from Redis
- Events are buffered in memory during Redis outages with a configurable cap
- Usage records in PostgreSQL are partitioned by month for efficient querying
- OpenAPI 3.1 spec defines `UsageEvent` and `UsageRecord` schemas

**Part of Epic: Usage Metering & Overage Billing**

---

#### 2.2 (#1413) — Usage Aggregation & Quota Enforcement

Raw usage events are only useful when aggregated into billing-period totals and enforced against plan quotas. This issue builds the aggregation layer that computes period-to-date consumption and the enforcement layer that blocks actions when hard limits are reached.

Quota enforcement runs synchronously in the request path via the `checkQuota(orgId, metric)` function introduced in 1.2. For `api_calls`, the function reads the Redis counter for the current billing period and compares against the plan's monthly quota. For `schema_count` and `team_members`, the function queries the current count from the database. For `storage_bytes`, the function reads a Redis gauge that is updated on every storage mutation.

Enforcement operates at two thresholds: a soft limit (80% of quota) that triggers a warning header (`X-Quota-Warning`) on API responses, and a hard limit (100%) that rejects the request with 429 Too Many Requests. The 429 response includes a `Retry-After` header set to the beginning of the next billing period and a `type` URI (`/errors/quota-exceeded`) distinguishing it from rate limiting. A configurable grace period (default: 10% overage) allows organizations to slightly exceed their quota while the upgrade flow is in progress.

The aggregation endpoint `GET /api/v1/usage/{orgId}/summary` returns a per-metric breakdown: `{ metric, limit, consumed, remaining, percentUsed, projectedEndOfPeriod }`. The projection uses linear extrapolation from current usage rate to estimate whether the organization will exhaust their quota before the period ends.

**Acceptance Criteria**

- Quota enforcement runs synchronously and blocks requests at the hard limit with 429
- Soft limit (80%) triggers `X-Quota-Warning` header on responses without blocking
- Grace period allows configurable overage percentage before hard block
- 429 response includes `Retry-After` header set to next billing period start
- Usage summary endpoint returns consumed, remaining, and projected end-of-period values
- Enforcement is bypassed for Enterprise-tier organizations with unlimited quotas
- Quota state is consistent across API gateway instances via shared Redis counters

**Part of Epic: Usage Metering & Overage Billing**

---

#### 2.3 (#1425) — Overage Calculation Engine

When organizations exceed their plan quotas (within the grace window or with overage billing enabled), the platform must calculate and charge overage fees. This issue builds the calculation engine that computes per-metric overage amounts based on configurable rates and adds them as line items to the organization's next invoice.

Overage rates are defined per plan in the `usage_quotas` JSONB column: `{ api_calls: { limit: 50000, overage_rate_cents: 5, overage_unit: 1000 }, storage_bytes: { limit: 5368709120, overage_rate_cents: 100, overage_unit: 1073741824 } }`. The engine reads period-end usage from PostgreSQL, subtracts the plan's included quota, and calculates `overageAmount = ceil(excess / overage_unit) * overage_rate_cents`. Overage charges are stored in an `overage_charges` table linked to the billing period and subscription.

The calculation runs as part of the billing cycle close-out job, after the aggregation worker has flushed all events for the completed period. An endpoint `GET /api/v1/usage/{orgId}/overage-estimate` provides a real-time projection of overage charges based on current consumption, letting organizations decide whether to upgrade their plan or accept the overage fees.

The admin panel at `/app/admin/overage` displays a Radix `Table` of organizations with active overage charges, sortable by amount. Each row links to the detailed usage breakdown for that billing period.

**Acceptance Criteria**

- Overage charges are calculated per metric using configurable rates and unit sizes
- Charges are computed at billing period close from durable PostgreSQL usage records
- `GET /api/v1/usage/{orgId}/overage-estimate` projects current-period overage in real time
- Overage line items appear on the next invoice with metric name, excess quantity, and rate
- Plans with overage billing disabled hard-block at the quota ceiling instead
- Overage calculation is idempotent; re-running for the same period produces identical charges
- Admin panel shows organizations with overage sorted by charge amount

**Part of Epic: Usage Metering & Overage Billing**

---

#### 2.4 (#1435) — Usage Dashboard & Alerts

Organizations need visibility into their consumption to avoid surprise charges and make informed upgrade decisions. This issue builds the self-service usage dashboard and configurable threshold alerts that notify organizations as they approach or exceed their plan quotas.

The dashboard page at `/app/settings/usage` renders four metric cards—API Calls, Schemas, Storage, Team Members—each showing a Radix `Progress` bar with current consumption vs. plan limit, numeric values, and a trend indicator (arrow up/down compared to the prior period). Below the cards, a time-series chart shows daily API call volume for the current billing period. A Radix `Select` switches between metrics, and Radix `Tabs` switch between current period and historical views.

```
┌─────────────────────────────────────────────────────────────────┐
│  Usage Overview              Billing Period: Mar 2 – Apr 1      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  API Calls          Schemas          Storage       Team         │
│  ██████████░░  3/3  ████░░░░  2.1 GB  ██████░░     │
│  38,450 / 50,000    of Unlimited      of 5 GB     4 / 10       │
│  ▲ 12% vs last      —                ▲ 8%        —            │
│                                                                 │
│  Daily API Calls                                                │
│  2000 ┤          ╭─╮                                            │
│       │       ╭──╯ ╰──╮  ╭──╮                                  │
│  1500 ┤    ╭──╯       ╰──╯  ╰──╮                               │
│       │ ╭──╯                    ╰──                             │
│  1000 ┤─╯                                                      │
│       │                                                         │
│   500 ┤                                                         │
│       ┤────┬────┬────┬────┬────┬────┬────┬                     │
│       Mar 2  Mar 6  Mar 10 Mar 14 Mar 18 Mar 22 Mar 26         │
│                                                                 │
│  [Current Period]  [History]                                    │
└─────────────────────────────────────────────────────────────────┘
```

Alert thresholds are configurable per organization via `PUT /api/v1/usage/{orgId}/alerts` with fields for `metric`, `threshold_percent` (default: 80, 95), and `channels` (email, webhook). Alerts fire once per threshold per billing period—hitting 80% sends one email, not one per request. The alert payload includes current usage, limit, projected exhaustion date, and a direct link to the upgrade page.

**Acceptance Criteria**

- Dashboard displays four metric cards with progress bars, numeric values, and trend indicators
- Time-series chart shows daily usage for the selected metric within the billing period
- Historical view shows usage across past billing periods for trend analysis
- Alert thresholds fire at configurable percentages (default: 80% and 95%)
- Alerts are deduplicated—one notification per threshold per billing period per metric
- Alert channels support email and webhook with JSON payload
- Dashboard loads within 2 seconds using Redis counters for current-period data

**Part of Epic: Usage Metering & Overage Billing**

---

## Epic 3: Payment Integration & Subscription Management

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 3.1 (#1455) | Stripe Subscription Integration | Core Stripe API integration for recurring subscription billing | `ai-generated`, `enhancement`, `monetization`, `mvp`, `rest` | Yes |
| 3.2 (#1466) | Payment Method Management | Self-service card and ACH management via Stripe.js | `ai-generated`, `enhancement`, `monetization`, `mvp`, `rest` | Yes |
| 3.3 (#1474) | Invoice Generation & History | Automated invoice creation with PDF export and payment tracking | `ai-generated`, `enhancement`, `monetization`, `rest` | No |
| 3.4 (#1479) | Subscription Lifecycle & Self-Service Portal | Consumer-facing portal for billing, invoices, and plan management | `ai-generated`, `enhancement`, `monetization`, `mvp` | No |
| 3.5 (#1486) | Billing Admin Dashboard | Internal admin view for revenue, subscriptions, and billing operations | `ai-generated`, `enhancement`, `monetization` | No |

### Detailed Issue Descriptions

---

#### 3.1 (#1455) — Stripe Subscription Integration

Stripe is the payment backbone. This issue integrates the Stripe Subscriptions API to create, update, cancel, and reconcile recurring subscriptions tied to Apiome pricing plans. Each plan (1.1) maps to a Stripe Product and Price. When an organization subscribes or changes plans, the backend creates or updates the Stripe subscription and synchronizes the state locally.

The integration layer wraps the Stripe API behind a `StripeService` that handles: customer creation (one Stripe customer per organization), subscription creation with the correct Price ID, subscription updates for plan changes with proration, cancellation (immediate or at period end), and webhook processing. The webhook handler at `POST /api/v1/billing/webhooks/stripe` processes `invoice.paid`, `invoice.payment_failed`, `customer.subscription.updated`, `customer.subscription.deleted`, and `payment_intent.succeeded` events.

```
┌─────────────┐     ┌────────────────┐     ┌─────────────┐
│  Apiome │     │  Stripe API    │     │  Stripe     │
│  Backend     │────▶│  (Customers,   │────▶│  Dashboard  │
│              │     │   Subscriptions│     │             │
│              │◀────│   Invoices)    │     │             │
│  webhook     │     └────────────────┘     └─────────────┘
│  handler     │◀─── webhook events
└─────────────┘
```

The local `subscriptions` table mirrors Stripe state with `stripe_subscription_id`, `stripe_customer_id`, `status` (active, past_due, canceled, trialing, unpaid), `current_period_start`, `current_period_end`, and `cancel_at_period_end`. A reconciliation job runs daily, comparing local records against Stripe's API to catch any drift from missed webhooks.

Idempotency is enforced on all Stripe API calls using `Idempotency-Key` headers derived from `{orgId}:{action}:{timestamp}`. Failed webhook deliveries are retried by Stripe; the handler is idempotent by checking event IDs against a `processed_events` table before applying state changes.

**Acceptance Criteria**

- Plan creation syncs to Stripe as a Product/Price pair; plan updates create new Prices
- Subscription creation, update, and cancellation reflect in both Stripe and local database
- Webhook handler processes `invoice.paid`, `invoice.payment_failed`, and subscription lifecycle events
- All Stripe API calls include idempotency keys to prevent duplicate charges
- Daily reconciliation job detects and resolves drift between local and Stripe state
- Webhook handler deduplicates events using a `processed_events` table
- Stripe test mode is used in development; live keys are loaded from environment variables

**Part of Epic: Payment Integration & Subscription Management**

---

#### 3.2 (#1466) — Payment Method Management

Organizations need to add, update, and remove payment methods without friction. This issue builds the payment method management UI using Stripe.js and Stripe Elements, ensuring PCI compliance by never sending raw card data through Apiome servers.

The payment method page at `/app/settings/billing/payment-methods` embeds a Stripe `PaymentElement` for adding new cards or bank accounts. The flow creates a Stripe SetupIntent on the backend (`POST /api/v1/billing/setup-intent`), passes the client secret to the frontend, and lets Stripe.js handle the sensitive data collection. On successful setup, the payment method is attached to the Stripe customer and the default payment method is updated.

Existing payment methods are listed in a Radix `Table` showing card brand, last four digits, expiration date, and a default indicator using Radix `Badge`. Actions include "Set as Default" and "Remove" (with a Radix `AlertDialog` confirming removal). Removing the last payment method is blocked if the organization has an active paid subscription—they must downgrade first.

Backend endpoints include `POST /api/v1/billing/setup-intent` (create SetupIntent), `GET /api/v1/billing/payment-methods` (list attached methods), `PUT /api/v1/billing/payment-methods/{id}/default` (set default), and `DELETE /api/v1/billing/payment-methods/{id}` (detach). The backend never stores raw card numbers—only Stripe payment method IDs and metadata (brand, last4, expiry).

**Acceptance Criteria**

- Stripe `PaymentElement` handles card/ACH data collection without raw data touching the server
- SetupIntent flow ensures PCI compliance by tokenizing payment data client-side
- Payment method list displays brand, last four digits, expiration, and default status
- Default payment method can be changed; the new default applies to the active subscription
- Removing the last payment method is blocked when a paid subscription is active
- Adding a payment method during trial triggers the conversion-ready state for trial management (1.4)

**Part of Epic: Payment Integration & Subscription Management**

---

#### 3.3 (#1474) — Invoice Generation & History

Stripe handles charge creation, but organizations need a complete invoice record within the Apiome platform for accounting, expense reporting, and tax documentation. This issue synchronizes Stripe invoices to local storage and adds overage line items, PDF generation, and downloadable invoice history.

When Stripe fires an `invoice.paid` webhook, the handler creates a local `invoices` record with `stripe_invoice_id`, `organization_id`, `period_start`, `period_end`, `subtotal`, `tax`, `total`, `status`, `line_items` (JSONB), and `paid_at`. Overage charges from the calculation engine (2.3) are added as supplementary line items on the next Stripe invoice via the Stripe Invoice Items API before the invoice finalizes.

The invoice detail page at `/app/settings/billing/invoices/[invoiceId]` renders a formatted invoice with organization details, line items (subscription charge, overage by metric, credits), subtotal, tax, and total. A "Download PDF" button generates a PDF via a server-side renderer and streams it to the browser. The invoice list at `/app/settings/billing/invoices` uses Radix `Table` with columns for invoice number, date, amount, status, and a download action.

REST endpoints include `GET /api/v1/billing/invoices` (paginated list), `GET /api/v1/billing/invoices/{id}` (detail), and `GET /api/v1/billing/invoices/{id}/pdf` (PDF download). Invoices are immutable once finalized—corrections produce credit notes rather than modifying the original.

**Acceptance Criteria**

- Stripe `invoice.paid` webhook creates a local invoice record with all line items
- Overage charges from the metering engine appear as line items on the Stripe invoice
- Invoice detail page renders all fields: number, dates, line items, subtotal, tax, total
- PDF generation produces a professional invoice document downloadable from the UI
- Invoice list supports filtering by date range and status with cursor pagination
- Invoices are immutable after finalization; corrections use credit notes
- Historical invoices are retained indefinitely for compliance

**Part of Epic: Payment Integration & Subscription Management**

---

#### 3.4 (#1479) — Subscription Lifecycle & Self-Service Portal

The self-service billing portal consolidates all subscription management into a single page where organizations can view their current plan, change plans, manage payment methods, and review invoices. This is the primary touchpoint for all billing interactions and must be polished enough that organizations never need to contact support for routine billing tasks.

The portal page at `/app/settings/billing` is organized into sections using Radix `Tabs`: "Plan" (current plan details with upgrade/downgrade CTA), "Usage" (link to usage dashboard 2.4), "Payment Methods" (embedded from 3.2), and "Invoices" (embedded from 3.3). The Plan tab shows the current plan name, price, renewal date, and a summary of entitlements with current utilization percentages.

Subscription lifecycle events are surfaced as banners: past-due invoices show a red Radix `Callout` with a "Retry Payment" button, upcoming renewals show an informational banner 7 days before billing, and plan changes pending at period end show a yellow notice. The portal handles edge cases: organizations with past-due invoices cannot upgrade (must resolve payment first), canceled subscriptions show a "Reactivate" option before the period ends, and organizations mid-trial see their trial status and conversion CTA.

Backend endpoints include `GET /api/v1/subscriptions/{orgId}` (current subscription state), `POST /api/v1/subscriptions/{orgId}/reactivate` (undo cancellation before period end), and `POST /api/v1/subscriptions/{orgId}/retry-payment` (retry failed payment via Stripe). The subscription state machine enforces valid transitions: active → canceled, past_due → active (on payment), trialing → active (on conversion).

**Acceptance Criteria**

- Billing portal consolidates plan, usage, payment methods, and invoices in a tabbed layout
- Current plan section shows name, price, renewal date, and entitlement utilization
- Past-due invoices surface a red banner with retry-payment functionality
- Canceled subscriptions offer reactivation before the billing period ends
- Subscription state machine enforces valid transitions and rejects invalid ones
- Portal renders correctly for all subscription states: active, trialing, past_due, canceled
- No billing action requires contacting support; all routine tasks are self-service

**Part of Epic: Payment Integration & Subscription Management**

---

#### 3.5 (#1486) — Billing Admin Dashboard

Platform administrators need operational visibility into revenue, subscription health, and billing exceptions. This issue builds the internal admin dashboard that surfaces key business metrics and provides tools for manual billing interventions.

The admin dashboard at `/app/admin/billing` renders three Radix `Tabs`: "Revenue" (MRR, ARR, revenue by plan, growth rate), "Subscriptions" (active count by plan, churn rate, trial conversion rate), and "Exceptions" (failed payments, past-due accounts, refund requests). The Revenue tab shows a time-series chart of monthly recurring revenue with a breakdown by plan tier. Summary cards at the top display current MRR, month-over-month growth, and total active subscriptions.

```
┌─────────────────────────────────────────────────────────────────┐
│  Billing Admin                                                  │
│  [Revenue]  [Subscriptions]  [Exceptions]                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  MRR: $14,350      Growth: +8.2%       Active: 487             │
│                                                                 │
│  Monthly Recurring Revenue                                      │
│  $15k ┤                                          ╭──           │
│       │                                    ╭─────╯             │
│  $12k ┤                              ╭─────╯                   │
│       │                        ╭─────╯                          │
│  $9k  ┤                  ╭─────╯                                │
│       │            ╭─────╯                                      │
│  $6k  ┤      ╭─────╯                                           │
│       │╭─────╯                                                  │
│  $3k  ┤╯                                                       │
│       ┤────┬────┬────┬────┬────┬────┬────┬────┬────┬────       │
│       Jun  Jul  Aug  Sep  Oct  Nov  Dec  Jan  Feb  Mar          │
│                                                                 │
│  Revenue by Plan                                                │
│  ████████████████████████  Pro: $8,410 (58%)                   │
│  ████████████████          Team: $4,950 (34%)                  │
│  █████                     Enterprise: $990 (7%)               │
└─────────────────────────────────────────────────────────────────┘
```

The Exceptions tab lists failed payment attempts, organizations with past-due balances over 7 days, and pending refund requests. Admins can issue manual credits via `POST /api/v1/billing/credits` (applying a credit to the organization's Stripe balance), extend trials via `POST /api/v1/subscriptions/{orgId}/extend-trial`, or force-cancel a subscription. All admin actions are logged to an audit trail.

Backend endpoints include `GET /api/v1/admin/billing/metrics` (MRR, ARR, churn, conversion), `GET /api/v1/admin/billing/exceptions` (failed payments, past-due list), and `POST /api/v1/billing/credits` (issue credit). Metrics are pre-computed hourly and cached in Redis for fast dashboard loading.

**Acceptance Criteria**

- Revenue tab displays MRR, ARR, month-over-month growth, and revenue breakdown by plan
- Subscriptions tab shows active count by plan, churn rate, and trial-to-paid conversion rate
- Exceptions tab lists failed payments, past-due accounts, and refund requests
- Admins can issue credits, extend trials, and force-cancel subscriptions from the dashboard
- All admin billing actions are logged to an immutable audit trail
- Metrics are pre-computed and cached; dashboard loads within 1 second
- Dashboard data is accessible via REST API for integration with external BI tools

**Part of Epic: Payment Integration & Subscription Management**

---

## Parallel Work Guide

**Epic 1 — Pricing Tiers & Plan Management**:
Issues 1.1 (Plan Data Model), 1.2 (Feature Gating), and 1.4 (Trial Management) can be developed in parallel as they address independent concerns—data model, runtime enforcement, and trial lifecycle. Issue 1.3 (Upgrade/Downgrade Flows) depends on 1.1 for the plan data model and 1.2 for the entitlement checks that validate downgrades.

**Epic 2 — Usage Metering & Overage Billing**:
Issues 2.1 (Ingestion Pipeline) and 2.4 (Usage Dashboard) can be started in parallel—the dashboard can be stubbed with mock data while the pipeline is built. Issue 2.2 (Aggregation & Enforcement) depends on 2.1 for the Redis counters and stream infrastructure. Issue 2.3 (Overage Calculation) depends on 2.2 for period-end usage totals.

**Epic 3 — Payment Integration & Subscription Management**:
Issues 3.1 (Stripe Integration) and 3.2 (Payment Methods) can be developed in parallel as they use independent Stripe APIs (Subscriptions vs. SetupIntents). Issue 3.3 (Invoice Generation) depends on 3.1 for webhook handling and 2.3 for overage line items. Issue 3.4 (Self-Service Portal) depends on 3.1, 3.2, and 3.3 as it composes all billing UI. Issue 3.5 (Admin Dashboard) depends on 3.1 for subscription data and 3.3 for invoice/revenue data.

**Cross-Epic Parallelism**: Epic 1 (Pricing & Plans) and Epic 3 (Payment Integration) can begin simultaneously—plan data model (1.1) and Stripe integration (3.1) share no dependencies. Epic 2 (Usage Metering) can start in parallel with both but produces outputs consumed by Epic 3 (overage charges feed into invoices). The feature gating engine (1.2) should be integrated early as all other platform features depend on it for plan enforcement. Within those constraints, all frontend UI work (pricing page, billing portal, admin dashboards) can proceed in parallel once the backend APIs are stubbed.
