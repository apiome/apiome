# MCP trust baselines, drift, and shadowing (CLX-3.4, #4858)

A point-in-time score cannot detect a **rug pull**. Tool descriptions, schemas, source releases, and
endpoint identity can all change after an operator approved a server, and a stale green badge will
keep vouching for the new, worse offering. This feature pins a **baseline** — the trust manifest an
administrator explicitly approved — so every later rediscovery/release is diffed against *what was
actually blessed*, not merely against the previous snapshot.

It reuses existing evidence rather than re-discovering anything (AC5): the capability/schema portion
of a manifest is the existing `surface_fingerprint`; the source portion is `mcp_endpoint_sources` /
`mcp_source_sboms`; the surface diff and severity come from the canonical `diff_surfaces` /
`classify_change` engines.

## The trust manifest (`app.mcp_trust_manifest`)

A **trust manifest** composes, into one comparable fingerprint, everything that makes a server
trustworthy at a snapshot:

| Component | Source | Notes |
|-----------|--------|-------|
| identity | `mcp_endpoint_versions` | server name/title/version, negotiated protocol version |
| transport | `mcp_endpoints.transport` + `transport_metadata` | kind always kept; volatile timing fields dropped so a slow connection is not "drift" |
| capabilities / tool-resource-prompt metadata / normalized schemas | `surface_fingerprint` | **reused whole**, not recomputed |
| policy-relevant permissions | tool `annotations` | authority hints (`readOnlyHint` / `destructiveHint` / `openWorldHint` / `idempotentHint`) projected out so an escalation is separately classifiable |
| source digest | `mcp_endpoint_sources.digest` + `mcp_source_sboms.sbom_fingerprint` | a swapped-out release behind an unchanged URL is visible |

`build_trust_manifest(...)` composes it; `TrustManifest.fingerprint()` folds it to one SHA-256, and
`component_fingerprints()` gives one per facet so a diff can name which facet moved.

## Drift classification (AC1 / AC4)

`diff_trust_manifests(...)` diffs an approved baseline against the current snapshot and classifies
**every material change** into exactly one bucket, each carrying an **old→new evidence reference**:

- **normal_change** — a benign, expected change: a new capability, a description tweak, a routine
  version bump, a new source link.
- **quality_regression** — the offering got worse without losing coverage or authority: a breaking
  schema edit, a lost output schema, a dependency inventory that disappeared.
- **security_regression** — authority or provenance regressed: a tool became destructive/open-world,
  a read-only tool is no longer read-only, a pinned source digest became unverified, the transport
  changed underneath a stable URL.
- **coverage_loss** — something covered is gone: a tool/resource/prompt was removed, or a source link
  was retired with nothing replacing it. Coverage loss is how a rug pull *hides*.

A `DriftGate` then decides **pass / warn / blocked** over the baseline's **configured risk deltas**
(default: `security_regression` + `coverage_loss`). Blocking is only *enforced* when
`APIOME_MCP_TRUST_DRIFT_GATE_ENABLED` is on; otherwise the same drift is computed and reported, but
the gate is advisory.

## Shadowing (AC3)

`detect_shadowed_names(...)` groups tool/resource/prompt names exposed by **more than one enabled
endpoint** in a tenant's host scope — *tool shadowing* (OWASP MCP09), where an agent routing by name
can be steered to the wrong server. A collision whose endpoints all share a host is flagged
`same_host` (the strongest signal); a cross-host collision is advisory.

## REST

| Method & path | Purpose |
|---------------|---------|
| `POST /v1/mcp/{tenant}/endpoints/{id}/trust-baseline` | Approve a baseline. Body: `rationale` (required), `version_id` (optional; default latest), `gating_categories` (optional). Writes a governance policy event and supersedes the prior baseline. |
| `GET /v1/mcp/{tenant}/endpoints/{id}/trust-baseline` | The active baseline and approval history. |
| `GET /v1/mcp/{tenant}/endpoints/{id}/trust-drift` | Diff the current snapshot against the approved baseline. `?notify=true` fans out a push-webhook alert on a regression (gated by the notify kill switch). |
| `GET /v1/mcp/{tenant}/data-quality/shadowing` | Shadowed names across the enabled host scope. |

## CLI

```
apiome mcp trust-baseline-approve <endpoint-id> --rationale "Approved for prod." [--version <id>] [--gate security_regression --gate coverage_loss]
apiome mcp trust-baseline-show <endpoint-id>
apiome mcp trust-drift <endpoint-id> [--notify]
apiome mcp shadowing
```

## Configuration

| Setting | Default | Effect |
|---------|---------|--------|
| `APIOME_MCP_TRUST_DRIFT_GATE_ENABLED` | `false` | When on, a `blocked` drift gate is *enforced*; otherwise advisory. Viewing drift never depends on this flag. |
| `APIOME_MCP_TRUST_DRIFT_NOTIFY_ENABLED` | `false` | The notification kill switch. When off, no drift alert is fanned out regardless of severity. |

## Persistence

`mcp_trust_baselines` (migration `V174`) stores one row per approval: the approved snapshot, the
composed manifest fingerprint and **full manifest envelope** (so the old side of a diff is always
reconstructable, AC1), the administrator **rationale** (AC2), and the **gating categories**. A partial
unique index keeps exactly one live baseline per endpoint; approving a new one soft-supersedes the
prior. The approval is also recorded to `registry_audit` as a policy event.
