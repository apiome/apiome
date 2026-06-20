# Pact (contract testing) mockups

Static, browser-openable design mockups for the contract testing slice of the
[Testing & QA feature roadmap](../../../../docs/FUTURE_FEATURE_ROADMAP_TESTING.md)
— specifically **Epic 6 (#1914): Contract Testing & CI/CD Pipeline**.

These files visualise what a self-hosted Pact broker, consumer-driven contract
registration, provider verification, can-I-deploy gating, change webhooks, and
a publish quality gate would feel like inside the Objectified studio. They are
visual references — no API calls, no auth, no build step.

## Open

Either open the files directly:

```
open objectified-ui/public/mockups/pact/index.html
```

Or, with the Next.js dev server running, browse to:

```
http://localhost:3000/mockups/pact/index.html
```

## Files

| File                     | Maps to roadmap issue                                                  |
| ------------------------ | ---------------------------------------------------------------------- |
| `index.html`             | Mockup hub linking to all screens, grouped by epic phase               |
| `broker.html`            | 6.1 Pact Broker Hosting — broker dashboard, consumer × provider matrix |
| `consumer-contract.html` | 6.2 Consumer Contract Registration — single-contract drill-in          |
| `webhooks.html`          | 6.5 Webhook on Contract Change — per-event config, delivery log        |
| `verification.html`      | 6.3 Provider Verification Workflow — per-consumer pass/fail run output |
| `can-i-deploy.html`      | 6.4 Can-I-Deploy Integration — environment compatibility verdict       |
| `quality-gate.html`      | 6.8 Quality Gate for Publishing — composite block-publish rules        |

Issues 6.6 (Postman collection generation) and 6.7 (pre-built GitHub Actions
workflow) are excluded from the mockup set: 6.6 is a one-shot export action
that is best surfaced as a button on the existing API exporter screen, and 6.7
ships as a reference YAML file rather than an in-product UI.

## Design system

Mockups intentionally mirror the live `objectified-ui` shell and align with
the sibling `mockups/devex`, `mockups/linting`, `mockups/contracts`, and
`mockups/architect` sets:

- **Typography**: Inter (400/500/600/700), JetBrains Mono for IDs, contract
  paths, version strings, and CLI output
- **Accent**: indigo-500 / 600 (Radix `accentColor="indigo"`), with a purple
  gradient on the Pact wordmark to differentiate from sibling sets
- **Gray scale**: slate (Radix `grayColor="slate"`)
- **Layout**: 260 px gradient sidebar, 48 px top platform bar, panel cards
  (`bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700`)
- **Icons**: Lucide (CDN), matching the live `lucide-react` icon set
- **Theme**: class-based dark mode toggle, persisted to `localStorage` under
  `pact-mockup-theme`. Honors `prefers-color-scheme` on first load.

## Pact-specific visual language

Beyond the shared shell, the Pact mockups introduce a few conventions that the
production build is expected to honor:

- **Verification status colours**: emerald (verified / passing), rose
  (failing), amber (stale or pending re-publish), cyan (new pact awaiting
  first verification), slate (n/a — no contract between this pair). Used
  consistently across the broker matrix, the per-consumer verification
  summary, the can-I-deploy table, and the publish-gate rules list.
- **Compatibility matrix cells**: 28 px squares with a tinted background and
  matching 1 px border, scaling slightly on hover. The matrix is the primary
  navigation pattern for the broker — every cell links into the underlying
  contract or verification run.
- **Run number convention**: `#1247` style numeric IDs in mono, paired with
  the provider name and the candidate version (e.g. `#1247 user-api@v3.0.0-rc.2`).
- **Verification log**: terminal-styled black panel with per-line tinted
  borders — emerald for ✓, rose for ✗, transparent for informational lines.
  Mirrors the output you would see locally from `pact-verifier`.
- **Verdict banners**: large gradient hero blocks at the top of the
  can-I-deploy and publish-gate pages — the gradient direction makes the
  verdict instantly readable on a small screen or in a Slack preview.
- **Composite scoring**: the publish gate frames Pact, linting, and DevEx
  signals as a single weighted score with per-rule contributions, matching
  the gauge used in `mockups/linting/quality-score.html`.

## Conventions matched from production code

Shared layout tokens come from
`app/components/ade/dashboard/dashboardScreenClasses.ts` and
`app/components/ade/dashboard/DashboardSideNav.tsx`:

- Section headers in the sidebar use `text-[0.65rem]` uppercase with a 1×1
  indigo dot
- Panels use `bg-gray-50 dark:bg-gray-900` for header bars
- Active nav items use a 10 % indigo fill + 1 px border + indigo text + a
  small dot indicator
- Page headers follow the `<h2>` + lucide icon + subtitle pattern from
  `dashboard/page.tsx`
- Code blocks use `JetBrains Mono` at `11–12px / 1.5` line-height, matching
  the Designer canvas property sheet and the DevEx mockups

## What's intentionally faked

- All consumers, providers, versions, contracts, interactions, and
  verification runs are hard-coded
- The compatibility matrix is rendered as static HTML — the production
  version will fetch from `/broker/matrix?provider=…`
- The CLI snippets are real syntax but use placeholder URLs and tokens
- The webhook delivery log is invented; production will pull from the
  broker's `webhook_executions` table
- The terminal panel on `verification.html` is hand-formatted output, not a
  live stream
- The theme toggle is the only piece of working JS (plus Lucide icon
  hydration)

## Out of scope (not included)

These belong to adjacent epics on the same roadmap and were excluded from this
mockup set:

- 6.6 Generate Postman Collections from Schemas (export action, surfaces on
  the existing API exporter screen)
- 6.7 GitHub Actions CI Workflow (reference YAML deliverable, not a UI)
- Epic 7 Load Testing & Chaos Engineering (separate mockup set)
- Epic 8 Automated Testing Infrastructure (CI/CD plumbing, not in-product UI)
