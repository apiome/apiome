# MCP protocol conformance & agent readiness (CLX-3.1, #4855)

The MCP **surface lint** (`mcp_lint`, `mcp_score`) answers *"is each advertised capability
well-formed and well-described?"*. It cannot answer the two questions an agent host actually has to
answer before trusting a server:

1. **Did the server behave like an MCP server?** — did it negotiate a protocol version honestly,
   echo the ids of the requests it answered, page sanely, and serve only the capabilities it
   declared?
2. **Can an agent actually use these tools?** — are descriptions substantive, parameters
   constrained, destructive operations declared, results bounded?

The **conformance engine** (`mcp_conformance`) answers both, and is what this document describes.

---

## Why it is a separate engine

Conformance carries its own rule registry, its own score, and its own fingerprint. It is
deliberately **not** more rule packs bolted into `mcp_lint`, for two reasons that are not
stylistic:

* **The surface score must not move.** `mcp_score.score_mcp_surface` runs *every* rule in the
  shared registry and hashes the result into a persisted `report_fingerprint`. Adding a dozen rules
  there would silently change the score, grade, and fingerprint of every MCP snapshot already
  stored — a retroactive regrade of history.
* **The surface engine cannot see the wire.** Its rules take a `DiscoverySurface` and nothing else.
  Protocol behaviour is only observable in the JSON-RPC exchanges.

The conformance report's key set is a **superset** of the lint report's, so every existing consumer
— the evidence normalizer, the axis model, the SARIF/JUnit gate serializer — reads it unchanged.

---

## The determinism / evidence split

This is the contract the whole feature rests on.

| | Surface-derived rules | Transcript-derived rules |
|---|---|---|
| Reads | the persisted `DiscoverySurface` | the redacted `ProtocolTranscript` |
| Guarantee | **deterministic**, recomputable offline from the database | **observational** live evidence |
| When unavailable | n/a — the surface always exists | the rule is **skipped and reported**, never assumed to pass |

A rule that needs a transcript and has none appears in the report's `skippedRules`. It is
**unverified, not passing.** An absent scan never reads as clean — that principle is enforced in
three places: the report's `skippedRules`, the evidence run's `coverage.state = "partial"`, and the
protocol axis's `coverage`.

---

## The protocol transcript

`mcp_protocol_transcript` records the JSON-RPC exchanges that **ordinary discovery already
performs** — the `initialize` handshake and the paginated `*/list` calls. A `TranscriptRecorder` is
attached to the transport, which calls it from the single chokepoint every request passes through.
It adds **no network traffic of its own.**

Two invariants are enforced by the type, not by convention:

**Passive only.** `PASSIVE_METHODS` is an allow-list of the read-only discovery methods.
`TranscriptRecorder.record()` raises `PassiveMethodError` on anything else — `tools/call` is not on
the list and *cannot* be recorded. The acceptance criterion "passive checks never invoke arbitrary
business tools" is therefore a property of the code, not a promise.

**Redacted at capture.** Nothing verbatim from the wire is retained:

| Wire data | What is stored |
|---|---|
| request `params` | the key **names** only — no values |
| `result` objects | top-level key names + an item **count** — no items |
| opaque `nextCursor` | a SHA-256 digest (equality survives; content does not) |
| error messages | scrubbed of credential-shaped substrings, length-bounded |

Transcripts persist to `apiome.mcp_protocol_transcripts` (migration **V171**), one immutable row per
snapshot. There is intentionally **no backfill**: fabricating a transcript for a session nobody
observed is the exact failure this design prevents.

---

## What is deliberately *not* a rule

**The MCP client is already a strict protocol enforcer.** These textbook violations each make it
abort discovery *before* a surface exists:

| Defect | Guard |
|---|---|
| malformed envelope / bad `jsonrpc` | `StreamableHttpTransport._parse_json_rpc` → `McpProtocolError` |
| cursor cycle / page-limit overrun | `discovery.paginate` → `McpPaginationError` |
| list method answering with an error | `discovery.paginate` → `McpDiscoveryError` |

A snapshot exhibiting one is never persisted, so a rule for it could never fire — it would sit in
the catalog reporting "pass" forever. Relaxing the client so these *could* be linted would be a bad
trade: it would admit malformed servers in order to describe them. They surface as a **failed
discovery job** instead.

What remains lintable is what the client tolerates but an agent still suffers from: capability
negotiation that doesn't match what was served, a silent protocol downgrade, wasteful or malformed
pagination, a response id that was never echoed, and an error code squatting on reserved space.

---

## Rules

Every rule cites the **MCP specification revision** it derives from (`2025-06-18`) and a resolvable
**source reference**, so a finding always traces back to a normative statement rather than an
opinion. Fetch the catalog with `GET /v1/mcp/conformance/rules`.

### `protocol` — did the server behave like an MCP server?

| Rule | Severity | Needs transcript |
|---|---|---|
| `protocol.missing-protocol-version` | error | |
| `protocol.unsupported-protocol-version` | error | |
| `protocol.missing-server-name` | error | |
| `protocol.missing-server-version` | warning | |
| `protocol.undeclared-capability-listed` | error | |
| `protocol.declared-capability-empty` | info | |
| `protocol.unknown-capability-declared` | info | |
| `protocol.response-id-not-echoed` | error | ✓ |
| `protocol.error-code-non-standard` | warning | ✓ |
| `protocol.protocol-version-downgraded` | info | ✓ |
| `protocol.list-result-missing-items` | error | ✓ |
| `protocol.empty-page-with-next-cursor` | warning | ✓ |

### `readiness` — can an agent actually use these tools?

All surface-derived, hence all deterministic.

| Rule | Severity |
|---|---|
| `readiness.tool-description-too-brief` | warning |
| `readiness.tool-parameter-missing-description` | warning |
| `readiness.tool-unbounded-list` | warning |
| `readiness.tool-destructive-not-declared` | warning |
| `readiness.tool-parameter-unconstrained` | info |
| `readiness.tool-missing-output-schema` | info |
| `readiness.tool-missing-recovery-guidance` | info |
| `readiness.tool-missing-annotations` | info |
| `readiness.tool-name-unconventional` | info |
| `readiness.tool-naming-inconsistent` | info |

#### Relationship to ToolBench

The public tool-definition-quality literature — ToolBench's published evaluation categories, and
Anthropic's tool-authoring guidance — converges on the same short list of properties that make a
tool usable by a model. Those **concepts** are what this pack encodes.

What it deliberately does **not** do is reproduce any third-party score: nothing is copied,
imported, or numerically approximated, and there is no opaque composite hiding a judgement. Each
rule states its own threshold as a named constant (`MIN_TOOL_DESCRIPTION_CHARS`,
`BOUNDING_PARAMS`, `DESTRUCTIVE_TOKENS`, …) and its own rationale in its descriptor. A team that
disagrees with a threshold can see it, cite it, and gate around it — which is the point of
preferring transparent rules to a borrowed number.

---

## Profiles

A **profile** is a named, gateable selection of rules — the unit the CLI and API run.

| Profile | Categories | Use |
|---|---|---|
| `mcp-conformance` *(default)* | protocol + readiness | everything |
| `mcp-protocol` | protocol | a hard CI gate on protocol correctness |
| `mcp-agent-readiness` | readiness | tool-definition quality |

An unknown profile is **rejected**, never silently defaulted — a typo in CI must not quietly widen
or narrow what is being gated.

---

## API

### Run and gate a profile

```
GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/versions/{version_id}/conformance
    ?profile=mcp-conformance     # mcp-protocol | mcp-agent-readiness
    &failOn=error                # warning | info | none
    &minScore=80                 # optional score floor
    &format=json                 # sarif | junit
```

Read-only and side-effect free: the report is recomputed on each request from the persisted surface
and the snapshot's stored transcript. `gate.passed` says whether the run cleared `failOn` /
`minScore`, so a CI job can act on this single call. `format=sarif|junit` returns the CI artifact
through the same serializer the compatibility gate uses.

```json
{
  "profile": "mcp-conformance", "specVersion": "2025-06-18",
  "score": 84, "grade": "B",
  "findings": [ { "rule": "readiness.tool-unbounded-list", "severity": "warning", "path": "tools.search", "message": "…" } ],
  "skippedRules": ["protocol.response-id-not-echoed", "…"],
  "transcriptCaptured": false,
  "gate": { "passed": false, "failOn": "error", "minScore": null, "reasons": ["…"] }
}
```

> **Read `skippedRules`.** A non-empty list means those rules could not be evaluated — no transcript
> was captured for this snapshot. They are unverified, not passing.

### Rule catalog

```
GET /v1/mcp/conformance/rules?profile=mcp-protocol
```

Returns every rule with its `specVersion`, `specReference`, `rationale`, and `requiresTranscript`.

---

## CLI

```bash
# Run and gate; exits non-zero when the gate fails (including with --format sarif|junit).
apiome mcp conformance <endpoint-id> --profile mcp-protocol --fail-on error

# Emit a CI artifact; the gate is still evaluated and still fails the build.
apiome mcp conformance <endpoint-id> --format sarif > conformance.sarif

# Inspect the rules and the specification statements they cite.
apiome mcp conformance-rules --profile mcp-agent-readiness
```

---

## Evidence & the protocol axis

Discovery captures the transcript, runs conformance, and writes a **separate evidence run** under
scanner id `apiome.mcp-conformance` (distinct from `apiome.mcp-lint`). Both scanners are listed in
`expected_scanners_for_subject`, so a snapshot that has never been conformance-scanned renders as
`not_run` / coverage `none` rather than silently clean.

The conformance report also fills the **`protocol` axis** (CLX-1.2), which until now always read
*"No protocol-conformance scanner evidence yet"*. Because the axis is now assessed, conformance is
gateable through the **existing** policy machinery with no new gate code:

```json
{ "axis_gates": { "protocol": { "minGrade": "B" } } }
```

A report with skipped rules assesses the axis but marks its coverage `partial`, so a consumer can
distinguish a fully-observed pass from a partially-observed one.
