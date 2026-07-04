# Contracts mockups

Static, browser-openable design mockups for the
[Contracts feature roadmap](../../../../docs/FUTURE_FEATURE_ROADMAP_CONTRACTS.md).

These files cover the full roadmap surface area across all five epics:
Contract Builder &amp; Templates (Epic 1), Data Sharing &amp; Consent
Management (Epic 2), Billing &amp; Revenue Integration (Epic 3), Audit
Trail &amp; Compliance (Epic 4), and Contract Testing &amp; Deploy Gating —
Pact (Epic 5). They are visual references — no API calls, no auth, no
Docker runtime, no real Stripe charges, no on-chain anchoring, no real
pact broker.

## Open

Either open the files directly:

```
open apiome-ui/public/mockups/contracts/index.html
```

Or, with the Next.js dev server running, browse to:

```
http://localhost:3000/mockups/contracts/index.html
```

## Files

| File                  | Maps to roadmap issue                                                                              |
| --------------------- | -------------------------------------------------------------------------------------------------- |
| `index.html`          | Mockup hub linking to all screens, grouped by epic                                                 |
| `dashboard.html`      | 1.6 Contract Lifecycle Dashboard — table of contracts, lifecycle activity, renewal queue, KPIs    |
| `templates.html`      | 1.3 Contract Template Library — pre-built &amp; custom templates, clauses, placeholders, preview |
| `terms-editor.html`   | 1.2 SLA Definition Editor — visual clause builder with metric / window / breach configuration     |
| `negotiate.html`      | 1.4 Contract Negotiation Workflow — inline diffs, comment threads, multi-party approval bar       |
| `sign.html`           | 1.5 Contract Signing &amp; Activation — signature blocks, activation tracker, immutable trail     |
| `data-sharing.html`   | 2.1 Schema-Based Data Sharing Contracts — schema picker, access levels, machine-readable spec     |
| `consent.html`        | 2.2 Consent Management + 2.5 Data Recall &amp; Revocation — append-only log, recall workflow      |
| `usage.html`          | 2.3 Data Usage Telemetry + 2.4 Contract Renewal Management — quotas, time series, renewal queue   |
| `billing.html`        | 3.1, 3.3, 3.4, 3.5 Billing Hub — pricing model, revenue share, billing run, payment rails         |
| `invoice.html`        | 3.2 Invoice Generation — line items, drill-down to clauses, revenue split, dispute trigger        |
| `history.html`        | 4.1 Append-Only Event Log — chained events, anchor batches, integrity verifier                    |
| `compliance.html`     | 4.3 Compliance Reporting + 4.4 Public Anchoring + 4.5 Data Export &amp; Portability                 |
| `disputes.html`       | 4.2 Dispute Resolution Workflow — claim &amp; evidence pack pulled from chain, mediator console   |
| `verification.html`   | 5.2 + 5.3 Provider Verification — replay contracted interactions, terminal log, clause binding    |
| `matrix.html`         | 5.4 Compatibility Matrix — consumer × provider verdict grid, failing pairs, pact coverage         |
| `can-i-deploy.html`   | 5.5 + 5.6 Can-I-Deploy Gate — verdict banner, per-consumer gate checks, CI exit-code parity       |

## Design system

Every screen renders inside a **replica of the live `apiome-ui`
(objectified-ui) shell**, not a feature-specific chrome:

- **Top platform bar**: faithful copy of `app/components/ade/TopHeader.tsx` —
  Apiome wordmark + version badge (`v0.6.4 RC`), centered
  `Home · Control Panel · Designer · Paths` navigation with "Control Panel"
  active, the indigo-to-purple gradient tenant-switcher pill (pulsing dot +
  "Acme Corp" + chevron), and the avatar button. A `← Hub` link and the
  theme toggle are the only mockup-specific additions.
- **Side menu**: faithful copy of
  `app/components/ade/dashboard/DashboardSideNav.tsx` — the real sections
  (Dashboard; Account; Administration; Data Management; Access &amp; IAM;
  Specifications, including the amber `Preview` pills on Catalog and MCP
  Servers) rendered verbatim, followed by the three new sections this
  feature adds to the menu: **Contracts** (Contracts, Templates, Data
  Sharing, Consent, Usage &amp; Renewal), **Contract Testing** (Verification,
  Matrix, Can I Deploy — each carrying a `Pact` pill in the same style as
  the live `Preview` pill), and **Billing &amp; Audit** (Billing, Audit Log,
  Compliance, Disputes). Item, active-state, section-header, and divider
  markup match the production component exactly (10 % indigo fill + 1 px
  indigo border + right-side dot for the active item; `hr` dividers at
  `border-indigo-500/10`).
- **Typography**: Inter (400/500/600/700), JetBrains Mono for table IDs,
  contract numbers, hashes, clause references, currency amounts, timestamps,
  audit-chain hashes, pact run numbers, and CLI output
- **Accent**: indigo-500 / 600 (Radix `accentColor="indigo"`); the platform
  bar logo and the index-page hero use an indigo-to-emerald gradient to
  signal "contracts live at the intersection of governance &amp; revenue"
- **Gray scale**: slate (Radix `grayColor="slate"`)
- **Layout**: 280 px gradient sidebar, 48 px top platform bar, the dashboard
  layout's `bg-gradient-to-br from-slate-50 via-white to-slate-50` content
  backdrop, panel cards
  (`bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700`)
- **Icons**: Lucide (CDN), matching the live `lucide-react` icon set
- **Theme**: class-based dark mode toggle, persisted to `localStorage` under
  `contracts-mockup-theme`. Honors `prefers-color-scheme` on first load.

Per-contract working screens (`terms-editor.html`, `negotiate.html`,
`sign.html`) highlight **Contracts** in the menu; `invoice.html` highlights
**Billing** — mirroring the prefix-based `isActive` matching in the live
side nav.

## Contracts-specific visual language

Beyond the shared shell, the Contracts mockups introduce a few conventions
that the production build is expected to honor:

- **Counterparty avatars**: 6×6 (24 px) rounded-full coloured circle with
  the counterparty's initial. Stable colour-per-tenant: Hooli `purple`,
  Globex `emerald`, Wonka `amber`, Cyberdyne `cyan`, Massive Dynamic `blue`,
  Pied Piper `indigo`. Used in tables and signature blocks alike.
- **Lifecycle status pills**: traffic-light language consistent with the
  rest of the platform — `Draft` = gray, `In review` = blue, `Signed` =
  indigo, `Active` = emerald, `Suspended` = amber, `Disputed` = rose,
  `Expired` = gray, `Recalled` = rose. Each pill is paired with a
  1.5 × 1.5 px coloured dot.
- **Consent badges**: `Active` = emerald, `Expiring` = amber,
  `Revoked` = rose, `Recall sent` = rose-darker. Revocation rows are
  rendered as indented "corner-down-right" entries directly below the
  original grant they invalidate, never replacing it.
- **Diff colours (negotiation)**: emerald background = added text,
  rose background = removed text, amber underline = comment marker,
  indigo dot = pending revision. Mirrors the conflict diff convention
  used by `mockups/connect/conflicts.html`.
- **Approval status bar (negotiation, signing)**: horizontal stepper with
  one chip per signing party. Chip states: `Pending` = gray,
  `Reviewing` = indigo (pulsing dot), `Approved` = emerald,
  `Rejected` = rose, `Signed` = emerald with a `signature` icon.
- **Audit chain anchors**: `Anchored` rows show the publishing chain
  (`Eth` / `OTS` / `S3 WORM`) in a small mono pill plus block height.
  `Pending` rows show an amber `pending` chip until the next batch.
- **SLA breach severity**: `Warning` (≥ 90 % of threshold) = amber,
  `Breach` = rose. Each appears with a sparkline showing the metric
  trend leading up to the event.
- **Revenue split bar**: single horizontal stacked bar showing percentage
  splits between revenue-share parties; party order matches the row order
  in the splits table.
- **Pact verification colours** (Epic 5): emerald = verified / passing,
  rose = failing, amber = stale (&gt; 72 h since last verification),
  cyan = new pact awaiting first verification, slate = no contract between
  the pair. Matches the convention established by `mockups/pact`.
- **Compatibility matrix cells**: 28 px rounded squares with tinted
  background + matching 1 px border, scaling slightly on hover; every cell
  links to the underlying verification run.
- **Verification log**: terminal-styled near-black panel with per-line
  tinted left borders — emerald for ✓, rose for ✗ — mirroring local
  `pact-verifier` output. Failing lines carry the violated contract clause
  reference (e.g. `DS-2.1`).
- **Verdict banner (can-i-deploy)**: full-width gradient hero — rose/orange
  for blocked, emerald for safe — so the verdict is readable at a glance;
  blockers and passed-check counts render as translucent chips inside the
  banner.
- **Clause binding**: pact signals map onto SLA clauses (strike counters,
  notice periods, deploy gates); gate verdicts and failed runs are recorded
  as immutable contract events (`verification.failed`,
  `deploy.gate.blocked`) in the same audit chain as Epic 4.
- **Currency**: always rendered in mono font, right-aligned in tables,
  with the contract's currency symbol prefixed. Negative amounts (credits)
  render rose; positive totals render bold; tax / fees render with a
  smaller secondary label underneath the amount.

## Conventions matched from production code

Shared layout tokens come from `app/components/ade/dashboard/dashboardScreenClasses.ts`
and `app/components/ade/dashboard/DashboardSideNav.tsx`:

- Section headers in the sidebar use `text-[0.65rem]` uppercase with a 1×1 indigo dot
- Panels use `bg-gray-50 dark:bg-gray-900` for header bars
- Active nav items use a 10 % indigo fill + 1 px border + indigo text + a small
  dot indicator
- Page headers follow the `<h2>` + lucide icon + subtitle pattern from
  `dashboard/page.tsx`
- Status pills mirror those in `mockups/automation/integrations.html`
- Table styling matches `mockups/connect/sync-logs.html` (sticky header,
  `text-[10px] uppercase tracking-wider` column labels, mono cells for IDs)

## What's intentionally faked

- All contracts, templates, clauses, signatures, consents, recalls, usage
  metrics, invoices, line items, splits, billing runs, anchor batches,
  reports, exports, and disputes are hard-coded
- All charts, sparklines, quota meters, and progress rings are static SVG
- The SLA editor "live JSON preview" is pre-computed; values do not update
  as the form is edited
- The negotiate / sign approval bars are static — no party can actually
  approve or sign in the mockup
- The audit-chain integrity verifier always returns "valid" and never
  performs real cryptographic work
- Stripe / NetSuite / QuickBooks badges are decorative; no real billing
  cycle ever runs
- The Ethereum anchor link points nowhere — etherscan transactions are
  hard-coded labels
- The "Generate &amp; encrypt" export button does not produce a download
- The theme toggle and Lucide icon hydration are the only working JS

## Out of scope (not included)

These belong to later phases of the roadmap and were excluded from the
mockup set in favour of the screens above:

- Tenant-level contract policy administration (org-wide defaults for
  signing rules, retention, KMS keys) — surfaces only as the "Configure
  schedules" CTA on `compliance.html`
- Counterparty CRM (counterparty profiles, contacts, AP/AR addresses,
  tax IDs) — counterparty data is rendered inline on each screen
- Webhooks &amp; outbound notifications for contract events — mentioned as
  "synced to audit log" footers but not surfaced as a configuration screen
- Smart-contract execution (on-chain enforcement of clauses, oracles for
  metric inputs) — out of MVP scope; the audit chain is the limit of the
  cryptographic surface in this mockup set
- E-signature provider integrations (DocuSign, Adobe Sign) — `sign.html`
  shows a self-hosted signing experience; provider hand-off is omitted
