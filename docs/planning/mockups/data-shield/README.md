# Apiome Shield · Mockup pack

Static HTML/Tailwind mockups for the **Shield** product — Apiome's API
security & runtime protection plane. Driven by the feature definitions in
[`docs/FUTURE_FEATURE_ROADMAP_SHIELD.md`](../../../../docs/FUTURE_FEATURE_ROADMAP_SHIELD.md).

These pages are 100% client-side (Tailwind via CDN, Lucide icons) so they can
be opened directly from disk or served from any static host. There are **no
build steps** and no shared bundles — each page is self-contained on purpose so
you can copy individual files into design reviews, decks, or video walk-throughs
without dragging dependencies along.

```
data-shield/
├── index.html              ← landing / mockup hub (start here)
├── dashboard.html          ← Shield Overview · KPIs, posture trend, hot list
│
├── scanner.html            ← Vulnerability scanner · OWASP API Top 10 + injection findings
├── sensitive-data.html     ← Sensitive data exposure · PII, mass assignment, over-exposure
├── auth-gaps.html          ← Authentication & authorization posture · BOLA / BFLA / CORS
├── scans.html              ← Scan schedules, runs, MTTR, generated reports
│
├── firewall.html           ← API firewall · OWASP rules, rate-limit policies, decision pipeline
├── bots.html               ← Bot detection & DDoS protection · classification, signatures, queue
├── events.html             ← Live SOC console · real-time event stream, top offenders, geo map
│
├── anomalies.html          ← ML anomaly detection · per-consumer profiles, score panel, model card
├── threat-feeds.html       ← External feeds (AbuseIPDB / GreyNoise / OTX) + attack-pattern library
├── alerts.html             ← Alerts & escalation chains · rules, P1/P2 severity, suppressions
├── investigations.html     ← Case workbench · timeline, evidence, notes, one-click response
│
├── vault.html              ← Encrypted key vault · rotation, KMS, tamper-evident audit log
├── leaks.html              ← Credential leak detection · GitHub / Pastebin / dark-web sources
├── compliance.html         ← Compliance posture · SOC 2 / PCI DSS / GDPR control mapping
└── policies.html           ← Zero-trust policies · simulator, Rego excerpt, identity-aware rules
```

## Mapping to the roadmap

| Roadmap epic                              | Pages                                                  |
| ----------------------------------------- | ------------------------------------------------------ |
| Vulnerability Scanner                     | `scanner.html`, `sensitive-data.html`, `auth-gaps.html`, `scans.html` |
| Runtime Protection Engine                 | `firewall.html`, `bots.html`, `events.html`            |
| Threat Intelligence & Anomaly Detection   | `anomalies.html`, `threat-feeds.html`, `alerts.html`, `investigations.html` |
| Secrets & Compliance Management           | `vault.html`, `leaks.html`, `compliance.html`, `policies.html` |
| Cross-cutting overview                    | `dashboard.html`, `index.html`                         |

Open `index.html` for a clickable map of all 16 surfaces.

## Design language

The Shield surfaces inherit the Apiome shell from the other mockup packs
(`/connect`, `/automation`, `/architect`, …) but layer on a few Shield-specific
conventions so you can tell them apart at a glance:

| Element              | Choice                                                                 |
| -------------------- | ---------------------------------------------------------------------- |
| Brand mark           | Lucide `shield-half` in an indigo→rose gradient tile (top-left)         |
| Primary accent       | `indigo-500` (links, active sidebar, primary buttons)                   |
| Critical signal      | `rose-500` (filled pills, pulsing dots for live attacks)                |
| Warning / drift      | `amber-500`                                                             |
| Healthy / pass       | `emerald-500`                                                           |
| Anomaly / ML         | `purple-500` / `fuchsia-500`                                            |
| Threat intel / feeds | `cyan-500`                                                              |
| Sidebar              | 280 px gradient panel, 5 grouped sections (Shield · Scanner · Runtime · Intelligence · Secrets & Compliance) |
| Topbar               | 48 px platform bar with breadcrumb + theme toggle + avatar              |
| Typography           | Inter (UI) · JetBrains Mono (`.mono` class for IDs, IPs, code)          |
| Dark mode            | Tailwind `class` strategy, persisted in `localStorage` (`shield-mockup-theme`) |

Every panel follows the same shell:

```html
<section class="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
  <div class="px-5 py-4 border-b … bg-gray-50 dark:bg-gray-900 flex items-center gap-3">
    <i data-lucide="…" class="w-5 h-5 text-indigo-500"></i>
    <h3 class="text-base font-semibold">Section title</h3>
  </div>
  <!-- content -->
</section>
```

Severity, status, and decision pills are consistent across all pages:

| Token       | Use                                          |
| ----------- | -------------------------------------------- |
| `Critical`  | rose-500 fill — needs immediate attention    |
| `High`      | orange-500 fill                              |
| `Medium`    | amber-500 fill                               |
| `Low`       | yellow-500 fill                              |
| `Info`      | gray-500 fill                                |
| `ALLOW`     | emerald (policy decisions)                   |
| `CHALLENGE` | amber (policy decisions)                     |
| `DENY`      | rose   (policy decisions)                    |

## Conventions

- **Synthetic data only.** All IPs, secrets, API keys, customer names, and
  metrics are fabricated. Anything that looks like an identifier is prefixed
  with `K4_` and rendered in mono so it never reads as a real token.
- **No JS frameworks.** A few lines of vanilla JS hydrate Lucide icons and
  toggle the theme. Charts are inline SVG. Tables are static HTML — there is
  no sorting, filtering, or pagination wired up.
- **Semantic links.** Sidebar items, "Investigate →" buttons, and the
  back-to-hub link in the topbar all point to real sibling files so the pack
  navigates as a single experience.
- **No build, no install.** Open any `.html` file directly, or serve the
  directory:

  ```bash
  cd apiome-ui/public/mockups/data-shield
  python3 -m http.server 8000
  # → http://localhost:8000/index.html
  ```

## Editing & extending

The pages are intentionally hand-tuned HTML — edit them directly. If you need
to add a new surface and want to keep the chrome consistent, the easiest path
is:

1. Copy an existing page that is structurally close (e.g. `alerts.html` for a
   list-heavy page, `compliance.html` for KPI + table, `investigations.html`
   for a workbench layout).
2. Update the topbar breadcrumb, the sidebar `active` state (border + indigo
   text), the page header (`<h2>` + subtitle + actions), and the `<main>` body.
3. Add the new entry to `index.html` in the matching epic section.
4. Add a row to the table in the **Mapping to the roadmap** section above.

Stay within the design tokens listed above (panel chrome, severity pills, mono
identifiers, indigo as the primary accent) and the new page will sit
naturally next to the rest of the pack.
