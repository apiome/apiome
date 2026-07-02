# Apiome Policy — Mockups

Static, browser-openable design mockups for the Apiome Policy feature —
an API governance policy-as-code engine analogous to ESLint for enterprise API design.

## Open

```bash
open apiome-ui/public/mockups/policy/index.html
```

Or, with the Next.js dev server running:

```
http://localhost:3000/mockups/policy/index.html
```

## Files

| File | Description |
| --- | --- |
| `index.html` | Mockup hub |
| `dashboard.html` | Org-wide policy compliance overview |
| `policy-editor.html` | Visual + YAML policy rule editor |
| `policy-library.html` | Policy packs library (Pro) |
| `ci-gate.html` | CI/CD gate configuration and run history |
| `violation-report.html` | Actionable per-run violation report |
| `approval-workflow.html` | Breaking change exception approval workflow |
| `audit-log.html` | Immutable audit trail (workflow_audit) |

## DB Hooks

| Hook | Used by |
| --- | --- |
| `versions` | Dashboard, CI Gate |
| `merge_sessions` | Approval Workflow |
| `merge_session_conflicts` | Approval Workflow |
| `workflow_audit` | Audit Log |
| `migration_plan_rules` | Policy Library, Policy Editor |

## Design System

Follows the same conventions as sibling mockups (`linting/`, `analytics/`):

- **Accent**: orange-500 / 600 (differentiates from linting's indigo)
- **Typography**: Inter 400/500/600/700 · JetBrains Mono for code
- **Icons**: Lucide (CDN)
- **Dark mode**: class-based, persisted to `localStorage` under `policy-mockup-theme`
- **Layout**: 260px sidebar · 48px top bar · panel cards

## Target Audience

Platform engineering teams and API Centers of Excellence managing API governance at scale.

**Enterprise Value**: ⭐⭐⭐⭐
