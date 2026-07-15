# CI, webhook, SARIF, and attestable lint outputs (CLX-4.2, #4860)

Governance runs before merge/release with machine-readable results and exact policy
provenance. The gate evaluates the pinned policy pack (CLX-1.3) over already-recorded lint
evidence (CLX-1.1) — it never re-executes scanners — and emits the verdict in CI-native
formats plus provider-neutral webhooks.

## Gate endpoints

```
GET /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/lint/gate
GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/versions/{version_id}/lint/gate
```

Auth: `validate_authentication` (API key), same as the sibling `lint/policy` routes.

| Query param | Meaning |
| --- | --- |
| `format` | `json` (default) \| `sarif` \| `junit` \| `markdown` \| `attestation`; the `Accept` header is honored when absent (`application/sarif+json`, `application/junit+xml`, `text/markdown`, `application/vnd.in-toto+json`) |
| `baselineRevisionId` / `baselineVersionId` | Optional baseline subject to diff regressions against (must belong to the same project / endpoint) |
| `newOnly` | `true` scopes the CI verdict's unwaived-errors gate to newly introduced findings |
| `policyVersionId` | Pin a historical policy pack instead of the latest |

**HTTP status is always 200** — the pass/fail verdict lives in the body (`gate.passed`).
The CLI owns the exit code, so CI exits non-zero only for **configured** policy failures
(the pack's `ciOutcomes` toggles), never for mere findings.

Every gate call persists a full, reproducible `lint_policy_evaluations` row (all current
findings, not just new ones), exactly like `GET …/lint/policy`.

### Regression semantics (`isNew` / `newFingerprints`)

Per scanner, shared with the CLX-4.1 workspace: a finding is new when its
`source_fingerprint` appears in that scanner's newest run but not in the comparison run —
the baseline subject's latest run for that scanner when a baseline is given, else the
scanner's own previous run. A scanner with no comparison run counts entirely as new.

### `newOnly` gating

Only the **unwaived-errors** gate is re-scoped to new findings (pre-existing debt does not
block a merge). Required-coverage and axis gates always evaluate the full head revision —
losing coverage is a property of the revision, not of any single finding. The response
carries both verdicts: `evaluation` (full, persisted) and `gate` (the CI verdict).

## JSON payload (format=json)

`LintGateResponse`: `subjectType/subjectId/projectId`, `baselineSubjectId`, `newOnly`,
`policy {policyVersionId, contentFingerprint, ciOutcomes}`, `evaluation {evaluationId,
passed, gateResults}`, `gate {passed, newOnly, gateResults}`, `counts {total, new,
unwaivedErrors, waived}`, `newFingerprints`, `findings[]` (envelope + `scannerId`,
`evidenceRunId`, `isNew`, `effectiveState`, `waived`, `decisionId`), `scanners[]`
(per-scanner provenance), `links {evidence, policy, workspace}`.

**Redaction guarantee:** every artifact carries ids and fingerprints only.
`config_fingerprint` is the redacted hash from CLX-1.1; `raw_artifact_ref`, raw
configuration, protected source, and credentials never appear in any output format.

## SARIF 2.1.0 mapping (format=sarif)

| SARIF | Source |
| --- | --- |
| `runs[0].tool.driver.name` | `apiome-lint-gate` |
| `runs[0].tool.driver.rules[].id` | **verbatim** scanner `rule_id` (never prefixed/rewritten) |
| `results[].ruleId` / `level` / `message` | envelope rule id, severity (`info`→`note`), message |
| `results[].locations[0].physicalLocation` | `location.path` + `startLine`/`startColumn` |
| `results[].fingerprints.primaryLocationLineHash` | `source_fingerprint` |
| `results[].properties.apiome` | `{policyState, waived, isNew, scannerId, sourceFingerprint, decisionId?}` |
| `results[].suppressions` | `[{kind: external, status: accepted, justification?}]` on waived / fixed / false-positive findings |
| `runs[0].properties.apiome` | subject + policy `{policyVersionId, contentFingerprint}` + per-scanner `{reportFingerprint, inputFingerprint, sourceFingerprint, configFingerprint, evidenceRunId}` + evaluation + links |
| `runs[0].automationDetails.id` | `apiome/lint-gate/{subjectId}` |

## JUnit (format=junit)

One `testcase` per finding: unwaived error/warning findings are `<failure>`s, waived /
fixed / false-positive findings are `<skipped>`, everything else passes. Provenance
fingerprints ride in the suite `<properties>` block (`apiome.scanner.<id>.reportFingerprint`
etc.). An empty report emits a single passing `no-findings` case.

## Markdown (format=markdown)

Human-readable gate summary for PR comments / CI job summaries: verdict, per-gate table
(configured on/off × pass/fail), counts, findings table, provenance fingerprints, links.

## Attestation (format=attestation)

An **in-toto Statement v1** wrapped in a **DSSE envelope**:

* `subject[]` — one entry per scanner: `{name: scannerId, digest:
  {"apiome-report-fingerprint": reportFingerprint}}` (report fingerprints are opaque Apiome
  content ids, hence the custom digest algorithm name).
* `predicateType` — `https://apiome.dev/attestations/lint-gate/v1`; the predicate carries
  subject/policy/scanner fingerprints, both evaluations, counts, and `generatedAt`.
* `signatures[]` — HMAC-SHA256 over the DSSE PAEv1 encoding
  (`DSSEv1 <len> application/vnd.in-toto+json <len> <payload>`) of the canonical-JSON
  payload (`sort_keys`, compact separators), keyed by
  `APIOME_LINT_ATTESTATION_SIGNING_SECRET`. Unset secret ⇒ `signatures: []` (well-formed
  but unverifiable).

Offline verification: `apiome lint verify-attestation --file gate.att --secret …` (or env
`APIOME_LINT_ATTESTATION_SECRET`) — recomputes the PAE HMAC with the stdlib only; no server
round-trip. Server and CLI implementations are lockstep mirrors
(`app.lint_attestation` / `apiome_cli.attestation`).

## Webhooks

Delivered over the existing push-webhook channels (`/v1/push-webhook-subscriptions`) with
the standard `X-Apiome-Signature` HMAC and retry/dead-letter handling; the event type is in
`X-Apiome-Event` and the payload's `event` key. Payloads carry ids/fingerprints only.

| Event | Fires when | Payload highlights |
| --- | --- | --- |
| `lint.scan.completed` | a NEW evidence run is recorded (`record_lint_evidence_run` insert; fingerprint-dedup re-scans stay silent) | `subjectType`, `versionRecordId`/`mcpVersionId`, `scannerId`, `outcome`, `profile`, `evidenceRunId`, `reportFingerprint`, `inputFingerprint`, `configFingerprint`, `findingCount` |
| `lint.regression.detected` | a **gate evaluation** finds new unwaived errors (never plain policy reads) | `subjectId`, `baselineSubjectId?`, `newFingerprints[]`, `count`, `policyVersionId`, `policyContentFingerprint`, `evaluationId?`, `links` |
| `lint.coverage.failed` | a gate evaluation fails required coverage AND the pack's `failOnRequiredCoverage` is on | `subjectId`, `missingAxes[]`, `requiredAxes[]`, `policyVersionId`, `evaluationId?`, `links` |
| `lint.waiver.expiring` | a granted waiver enters the warning window (`APIOME_LINT_WAIVER_EXPIRY_WARNING_HOURS`, default 72h) | `decisionId`, `sourceFingerprint`, `ruleId?`, `projectId?`, `expiresAt`, `rationale?`, `linkedTicket?`, `decisionHref` |

Waiver-expiry is **exactly-once per grant**: a 5-minute sweep claims rows atomically
(`expiry_notified_at` marker + `FOR UPDATE SKIP LOCKED`, V176), and re-granting a waiver
with a new expiry re-arms the marker.

## CLI

```bash
# CI gate: exit 1 iff a configured policy gate failed
apiome lint gate --project payments --version 1.4.0

# Gate only new violations against the last release, write SARIF for the code-scanning tab
apiome lint gate --project payments --version 1.4.0 \
  --base-version 1.3.0 --new-only --format sarif --output lint.sarif

# Signed evidence summary + offline verification
apiome lint gate --project payments --version 1.4.0 --format attestation -o gate.att
apiome lint verify-attestation --file gate.att --secret "$LINT_ATTESTATION_SECRET"

# Raw evidence runs behind the verdict
apiome lint evidence --project payments --version 1.4.0
```

`apiome lint gate` always fetches the JSON verdict; a non-json `--format` fetches that
artifact additionally and writes it to `--output` (or stdout, with the human verdict on
stderr so the artifact stays clean).

## Implementation map

* Gate service: `apiome-rest/src/app/lint_gate.py`
* Emitters: `apiome-rest/src/app/lint_gate_emit.py` (+ format tokens in `gate_report_emit.py`)
* Attestation: `apiome-rest/src/app/lint_attestation.py` / `apiome-cli/src/apiome_cli/attestation.py`
* Webhooks: `apiome-rest/src/app/lint_notifications.py`; scan hook in
  `Database.record_lint_evidence_run`; sweep `apiome-rest/src/app/lint_waiver_expiry_sweep.py`
* Routes: `lint_routes.py::lint_revision_gate`, `mcp_catalog_routes.py::get_mcp_endpoint_version_lint_gate`
* Migration: `apiome-db/scripts/V176__lint_ci_gate_4860.sql`
* CLI: `apiome-cli/src/apiome_cli/commands/lint.py` (`gate` / `evidence` / `verify-attestation`)
