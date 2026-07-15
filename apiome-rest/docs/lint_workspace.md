# Catalog-wide lint posture and remediation workspace (CLX-4.1, #4859)

The workspace turns per-revision lint reports into a persistent, tenant-wide triage surface
over the CLX-1.x substrate: evidence runs (V167), multi-axis evaluations (V168), and the
policy pack / waiver / decision store (V169). It adds no new evidence writers — it is a read
and governance layer.

Tenant scope: every request carries the tenant slug as the **required `tenant_slug` query
parameter** (these routers have no slug path segment; `validate_authentication` verifies the
caller's access to that tenant and the handlers scope by the resolved `tenant_id`). This is
the same contract the `/v1/lint/decisions` router uses. Project scope is the optional
`projectId` query parameter (catalog side only — MCP endpoints have no project).

## Subjects

One "subject" is either the **latest live revision of each live project** (`catalog_revision`)
or the **latest discovery snapshot of each live MCP endpoint** (`mcp_endpoint_version`).
Stale revisions never appear in the queue. Current findings for a subject are the merged
newest run **per scanner** (shared implementation with policy evaluation:
`app.lint_evidence.merged_findings_from_runs`), so a subject scanned by several tools shows
all of their latest findings, not just whichever scanner ran last.

## Endpoints

### `GET /v1/lint/workspace/findings`

The cross-catalog findings queue. Query parameters:

| Param | Values |
| --- | --- |
| `severity` | csv of `error`, `warning`, `info` |
| `state` | csv of `open`, `acknowledged`, `waiver_requested`, `waived`, `fixed`, `false_positive` (effective, evaluate-on-read) |
| `axis` | csv of `quality`, `protocol`, `security`, `supply_chain`, `supportability`, `compatibility` |
| `grade` | csv of composite grades `A`–`F` |
| `coverage` | `missing` \| `met` (subject's `required_coverage_met`) |
| `profile` | csv of execution profiles |
| `scanner` | csv of scanner ids (the "source" filter) |
| `subjectType` | `catalog_revision` \| `mcp_endpoint_version` |
| `projectId`, `ownerUserId`, `ruleId`, `category` | exact match |
| `new` | `true` restricts to regressions (see below) |
| `q` | free-text over rule, message, subject, location |
| `sort` | `severity` (default) \| `newest` \| `rule` \| `subject` |
| `limit` / `offset` | pagination (limit ≤ 200) |

Unknown values in closed vocabularies return `400`. The response carries `findings`, `count`,
`total`, and `facets` (value counts over the **filtered, pre-pagination** set for severity,
effective state, scanner, axis, and grade).

Each finding row links everything its detail needs: `versionRecordId`/`mcpVersionId` +
`projectId` (revision), `evidenceRunId` + `evidenceCreatedAt` (evidence run),
`latestPolicyEvaluationId` + `policyPassed` + `decision` (policy decision), and `location`
(source position). Remediation history is `GET /v1/lint/decisions/{decision_id}/events`.

**Regression (`isNew`)**: a finding is new when its fingerprint appears in its scanner's
newest run but not in that scanner's previous run; a scanner's first run counts entirely as
new. "All new unwaived security errors" is
`?new=true&severity=error&axis=security&state=open`.

### `GET /v1/lint/workspace/summary`

Tenant posture rollup: subject counts, composite grade distribution, per-axis
assessed/not-assessed tallies with average score and severity counts, the subjects missing
required coverage (from the latest policy evaluation's coverage gate when available, else the
default required axes not assessed), finding-state counts including `unwaivedErrors` /
`unwaivedSecurityErrors` / `newCount`, and waiver counts (`active`, `requested`,
`expiringSoon` — expiring within 14 days).

### `GET /v1/lint/workspace/trends?days=30`

Daily series that keeps **genuine remediation separate from policy and coverage change**:

* `remediatedFindings` — fingerprints that disappeared between consecutive runs of the same
  scanner AND whose decision is not `waived`/`false_positive`. A finding that vanished
  because it was waived is *not* remediation.
* `newFindings` — fingerprints that appeared (first in-window run counts wholly as new).
* `waiversGranted`, `waiversExpired`, `markedFalsePositive` — from the decision audit trail.
* `policyPackPublications` — `style_guide_policy_versions` created in the window.

Consumers must render these as distinct series and never sum remediation with policy
activity.

### `POST /v1/lint/workspace/decisions/bulk`

Body: `{ "items": [{ "sourceFingerprint", "projectId"?, "ruleId"? }] (1–200),
"set": { "state"?, "ownerUserId"?, "rationale"?, "linkedTicket"?, "expiresAt"?,
"policyVersionId"? } }` — at least one of `state` / `ownerUserId`.

* **Authorized** — the caller needs `lint_findings:edit`; per-item transitions that are
  approval-tier (see the state machine) additionally need `lint_findings:publish` and fail
  per item without it. Denials are written to the access audit ledger.
* **Audited** — every applied item goes through `upsert_lint_finding_decision`, which appends
  an immutable `lint_finding_decision_events` row inside the same transaction.
* **Reversible** — each per-item result carries `beforeState`, so a client can issue the
  exact inverse request (grouped by `beforeState`). Undoing an approval-tier change requires
  the same `publish` permission, by construction.

Per-item failures do not abort the batch; the response reports `appliedCount`,
`failedCount`, and per-item `ok`/`error`.

### Saved views — `GET/POST /v1/lint/workspace/views`, `PATCH/DELETE /v1/lint/workspace/views/{id}`

Per-user named filter bundles (`lint_workspace_saved_views`, V175), mirroring the MCP saved
searches: `name` (unique per tenant+user, 409 on duplicates), `filters` (the same vocabulary
as `GET /findings`, normalized on write — unknown keys dropped, unknown closed-vocabulary
values 422), `query` (free-text), `sort`, `isPinned`. Callers must be attributable users
(403 otherwise).

## Waiver state machine

`waiver_requested` (added by V175) splits waiver **request** from **review**. A requested
waiver still gates CI exactly like `open` (`SUPPRESSED_FOR_ERRORS` never includes it).

| From | To | Required `lint_findings` action | Fields |
| --- | --- | --- | --- |
| open / acknowledged / fixed / false_positive (or no row) | acknowledged, fixed, false_positive, open | `edit` | — |
| same | waiver_requested | `edit` | rationale |
| waiver_requested | waived (approve) | `publish` | rationale + expiresAt |
| waiver_requested | open (reject) | `publish` | — |
| waiver_requested | acknowledged (withdraw) | `edit` | — |
| any | waived (direct) | `publish` | rationale + expiresAt |
| waived | any other state (revoke / reopen) | `publish` | — |
| expired waiver | open | automatic at read time | — |

The same rules guard the single-decision route `POST /v1/lint/decisions` — bulk authorization
cannot be bypassed one decision at a time. Built-in roles: Owner/Admin hold
`lint_findings:publish`; Editor holds `view`/`edit`; Viewer holds `view` (V175 reseeds the
grids).

> Note for keyless legacy API keys: guarded decision mutations now require a resolvable
> acting user and answer `403` otherwise, consistent with every other guarded mutation.

## Implementation map

* Migration: `apiome-db/scripts/V175__lint_workspace_4859.sql`
* Service (pure): `apiome-rest/src/app/lint_workspace.py`
* Routes: `apiome-rest/src/app/lint_workspace_routes.py`
* Shared finding merge: `apiome-rest/src/app/lint_evidence.py`
  (`latest_runs_by_scanner`, `merged_findings_from_runs`)
* Finding→axis mapping: `apiome-rest/src/app/axis_score.py` (`axis_key_for_finding`)
* UI: `apiome-ui/src/app/ade/dashboard/lint-workspace/` +
  `apiome-ui/src/app/components/ade/dashboard/lint/workspace/` +
  `apiome-ui/src/app/utils/lint-workspace.ts`
