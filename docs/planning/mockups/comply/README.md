# Comply mockups

Static, browser-openable design mockups for **Objectified Comply** — regulatory compliance
mapping and certification built directly into the schema design layer.

## Open

Either open the files directly:

```
open objectified-ui/public/mockups/comply/index.html
```

Or, with the Next.js dev server running, browse to:

```
http://localhost:3000/mockups/comply/index.html
```

## Feature overview

Map `classes`, `class_properties`, and API paths to GDPR, HIPAA, PCI-DSS, SOC 2, and
ISO 27001 controls. Tag individual fields as PII, PHI, or PCI. Auto-generate auditor-ready
evidence packages. Define date-bounded audit windows and pin the exact schema `versions` that
were in scope — bridging the engineering schema layer directly to risk management and legal teams.

**DB hooks:** `classes` · `class_properties` · `versions` · `users` · `tenant_feature_flags`  
**Target buyer:** Finance, Healthcare, Government  
**Enterprise value:** ⭐⭐⭐⭐⭐

## Files

| File                     | Screen                                                    | Issues       |
| ------------------------ | --------------------------------------------------------- | ------------ |
| `index.html`             | Mockup hub — links to all screens                         | —            |
| `dashboard.html`         | Compliance Dashboard — framework scores, alerts, activity | 1.1          |
| `field-tagger.html`      | Field Tagger — tag `class_properties` as PII/PHI/PCI     | 1.2 · 1.3    |
| `data-map.html`          | Data Map — heatmap of sensitive data density by class     | 1.4 · 1.5    |
| `framework-mapper.html`  | Framework Mapper — attach controls to classes/API paths   | 2.1 · 2.2 · 2.3 |
| `gap-analysis.html`      | Gap Analysis — unmapped controls and untagged fields      | 2.4 · 2.5    |
| `evidence-report.html`   | Evidence Report — configure and preview export package    | 3.1 · 3.2 · 3.3 |
| `audit-window.html`      | Audit Windows — date windows, version scope, freeze       | 4.1 · 4.2 · 4.3 |
| `sidebar.js`             | Shared sidebar builder used by all detail pages           | —            |

## Design system

Mockups follow the Objectified Studio design system, using a **teal** accent
(distinguishing Comply from indigo-accented Studio features) to signal trust and
compliance:

- **Typography**: Inter (400/500/600/700), JetBrains Mono for code, version strings, and timestamps
- **Accent**: teal-500 / 600 (gradient `from-teal-500 to-emerald-500` in the app-bar logo)
- **Gray scale**: slate (matching production `grayColor="slate"`)
- **Layout**: 260 px gradient sidebar, 48 px top platform bar, panel cards
  (`bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700`)
- **Icons**: Lucide (CDN), matching the live `lucide-react` icon set
- **Theme**: class-based dark mode toggle, persisted to `localStorage` under `comply-mockup-theme`.
  Honors `prefers-color-scheme` on first load.

## Data classification tags

| Tag       | Color  | Regulatory scope                    |
| --------- | ------ | ----------------------------------- |
| PII       | rose   | GDPR, CCPA, and similar             |
| PHI       | blue   | HIPAA §164.312                      |
| PCI       | amber  | PCI-DSS Requirements 3 and 4        |
| Sensitive | gray   | Internal classification (no mandate)|

## What's intentionally faked

- All compliance scores, field counts, and control mappings are hard-coded
- Filters, search inputs, table sort, tab switching, and checkboxes are visual only
- The "Generate Evidence Package" button and "Freeze Evidence" button do nothing
- The theme toggle is the only piece of working JS (plus Lucide icon hydration and sidebar build)
- The Auto-suggest Tags button is static

## Out of scope (not included in MVP mockups)

- CCPA / LGPD framework support
- Custom framework builder (bring-your-own control library)
- Automated scan / LLM-assisted field classification
- Remediation workflow (ticketing / JIRA integration)
- Auditor portal (external reviewer access)
- Mobile-responsive layout
