# MCP source, supply-chain, and trust-posture scans (CLX-3.2, #4856)

The third MCP scan engine, alongside the surface lint (`app.mcp_lint` — *is each advertised
capability well-formed?*) and the conformance engine (`app.mcp_conformance` — *did the server
behave like an MCP server?*). This one answers a question neither can reach: **what is the server
made of?** — its repository, its dependencies, the secrets in its config, the shell commands its
manifest runs.

It is a **separate engine** for the same non-stylistic reason the conformance engine is: the
surface score is hashed into a persisted `report_fingerprint`, so adding rules to it would
retroactively regrade every stored snapshot. Trust posture carries its own registry, score, and
fingerprint, and leaves the other two reports byte-identical.

## The two honesty guarantees

The whole design turns on two properties, and both are enforced *structurally* — as facts about the
code, not habits of the callers.

### 1. Nothing static is "exploitable"

Acceptance criterion: the catalog must render risk, evidence, and remediation *without asserting a
finding is exploitable* unless a dynamic probe proved it.

That is a data-model property, not a UI one. Every finding carries an `exploitability` field. The
only constructor a rule may use — `make_finding` — hard-codes it to `static_signal`; there is no
argument through which a rule could claim otherwise. The `proven` value is reachable only through
`make_proven_finding`, which *requires* `ProbeEvidence`, and **no probe exists yet** (that is
CLX-3.3, #4857). So `proven_count` is 0 on every report this engine can produce, and every finding
renders as **"Signal — not proven exploitable"**. A `grep` for `EXPLOITABILITY_PROVEN` finding only
its definition and its one guarded constructor is the proof.

### 2. An unscanned thing is never a clean thing

A rule declares the evidence it needs (`requires`: `surface` / `source` / `sbom` /
`vulnerabilities` / `probe`). When that evidence is absent — no source linked, no SBOM attached,
vulnerability lookup off — the rule is **skipped and reported** in `skipped_rules` (with a reason),
and the evidence run is recorded as `partial` coverage. It is never evaluated against an assumption,
and its silence never reads as a pass. This reuses the exact mechanism CLX-3.1 built for absent
protocol transcripts.

## Evidence lanes (finding origin)

Every finding declares an `origin`, so a reviewer can always tell what standard of proof it rests
on:

| origin | reads | example rule |
| --- | --- | --- |
| `metadata` | the advertised surface | `metadata.hidden-instruction` |
| `source` | the linked artifact's config/code | `source.hardcoded-provider-credential` |
| `dependency` | the artifact's dependency inventory | `dependency.known-vulnerability` |
| `protocol` | observed protocol behaviour (reserved) | — |

The `metadata` lane needs only the stored snapshot, so it runs for **every** catalogued endpoint
and is fully recomputable offline. The `source` and `dependency` lanes need a linked source, so
they are skipped-and-reported for an endpoint that has none.

## Source associations

A source is linked explicitly — never inferred from a URL that happens to look like a repository.
`POST /v1/mcp/{tenant}/endpoints/{id}/sources`:

```json
{ "source_kind": "git", "reference": "https://github.com/acme/srv", "revision": "<40-hex-commit>" }
```

Two independent axes are recorded and never collapsed:

- **`provenance`** — *how the association is known*: `operator_declared` (weakest),
  `registry_published`, `discovery_advertised`, `attested`.
- **`verification_state`** — *how strongly the artifact is pinned*: `unverified` (a moving branch
  or tag — findings are **not reproducible** and are confidence-downgraded to `medium`),
  `digest_pinned` (a commit sha / image digest / exact version — reproducible), `attested`.

Pin strength is *derived* from whether the reference actually carries a digest; a caller cannot
assert `digest_pinned` for a floating branch. The V172 CHECK
`mcp_endpoint_sources_pinned_needs_digest_check` makes the alternative unstorable.

## SBOM — coordinates only

`POST .../sources/{sid}/sbom` attaches a CycloneDX or SPDX document. It is read for component
**coordinates only** — name / purl / version / license. No source, file content, or manifest text
is extracted or stored; `app.mcp_sbom.SbomComponent` and the `apiome.mcp_source_sboms` table have no
field for it. `origin` distinguishes an authoritative `operator_supplied` SBOM from a best-effort
`manifest_derived` one.

## Vulnerability lookup — off by default, coordinates only

The one networked lane. When `mcp_vulnerability_scan_enabled` is set (default **false**), OSV is
queried with **package coordinates only** — a list of purls, nothing else. `query_payload_for_audit`
exposes the exact request body so the no-exfiltration guarantee is testable, not merely asserted.
When disabled or unreachable, the result is `not_run` / `unavailable` with a reason — never an empty
vulnerability list ("we never asked" and "the answer was zero" must not render the same).

## Profiles and gating

| profile | origins | runs without a source? |
| --- | --- | --- |
| `mcp-trust-posture` (default) | all | yes (source/dep rules skipped) |
| `mcp-metadata-posture` | metadata, protocol | yes — CI-gateable today |
| `mcp-supply-chain` | source, dependency | no — all skipped without a source |

`GET .../versions/{vid}/trust-posture?profile=&failOn=&minScore=&requireFullCoverage=&format=`
runs and gates. `failOn` fails on a severity or worse; `minScore` sets a floor;
`requireFullCoverage` fails the gate when *any* rule was skipped — the way a team says "do not tell
me this server is clean when you never looked at its source". `format=sarif|junit` returns the CI
artifact. `GET /v1/mcp/trust-posture/rules` publishes the rule catalog, the profiles, and the OWASP
MCP risk catalog.

## OWASP MCP Top 10

Every rule maps to one or more OWASP MCP risks (`app.mcp_owasp`), and the report's `owasp_coverage`
names the risks the evaluated rules do **not** cover — so an unmentioned risk is a visible gap, not
an implied absence.

## The supply-chain axis

The engine fills the `supply_chain` axis (`app.axis_score`), reserved since CLX-1.2 and always
*not assessed* until a scanner existed. The axis takes the posture report's own score and grade, is
`partial`-covered when any rule was skipped, and — like every axis — contributes nothing to the
composite when unassessed. It is now gateable through the existing policy `axis_gates` with no new
gate code, exactly as CLX-3.1 did for `protocol`.

## CLI

```
apiome mcp source link <endpoint> --kind git --reference <url> --revision <commit>
apiome mcp source list <endpoint>
apiome mcp source retire <endpoint> <source-id>
apiome mcp trust-posture <endpoint> --profile mcp-trust-posture --fail-on error
apiome mcp trust-posture-rules
```
