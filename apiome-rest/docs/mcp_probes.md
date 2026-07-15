# Consent-gated, sandboxed MCP dynamic probes (CLX-3.3, #4857)

The three prior MCP scan engines are **static**. The surface lint (`app.mcp_lint`) reads what a
server *advertises*; the conformance engine (`app.mcp_conformance`) reads how it *behaved* during
ordinary discovery; the trust-posture engine (`app.mcp_trust_posture`) reads what it is *built from*.
Each was careful to render its findings as *signals* — CLX-3.2 in particular made it a data-model
fact that nothing it produces can read as `"exploitable"`, because a static reading cannot prove a
defect is reachable.

**This engine (`app.mcp_probe`) is the one that sends the server something and watches what it does.**
It is what lets a finding graduate from *suspected* to *observed* to *exploited-in-test*.

## The danger, and the shape that answers it

Probing a live server is dangerous in two directions, and the module's entire structure is the
response to both:

* **A probe can damage the system under test.** So the default profile is read-only and no profile
  may ever invoke a business tool with a side-effecting payload.
* **A probe can be attacked by the system under test.** A stdio MCP server is *arbitrary code we run
  on our own host*. So a stdio target may run only inside a disposable, least-privilege sandbox, and
  the engine refuses to hand one to a runner whose isolation is not provably locked down.

## The three tiers of proof

AC4: *"Findings distinguish suspected, observed, and exploited-in-test."* This is modelled as
first-class, ordered data (`app.mcp_probe.CLASSIFICATIONS`):

| tier | meaning | who produces it |
| --- | --- | --- |
| `suspected` | a static signal — a pattern that *indicates* risk | the static engines |
| `observed` | a probe *witnessed* the server do the risky thing (e.g. accept a malformed request a conformant server rejects) | passive & safe-active probes |
| `exploited-in-test` | a probe *demonstrated* the defect against a live server in isolation (a canary reflected, an unauthorized read succeeded) | safe-active & payload-fuzzing probes |

Only `exploited-in-test` becomes `ProbeEvidence` and can move the trust-posture report's
`proven_count` (see *the bridge* below). An `observed` finding is real, but it is not a demonstrated
exploit, and `ProbeFinding.to_probe_evidence` refuses to turn one into evidence.

## The three profiles

| profile | sends traffic? | consent | strongest tier | notes |
| --- | --- | --- | --- | --- |
| `passive` (default) | no | none | `observed` | Re-reads the captured transcript. Never touches a business tool because it never touches anything. The only profile that runs without recorded consent, and the only one unaffected by the kill switch. |
| `safe-active` | yes | required | `exploited-in-test` | Protocol-layer probes only (unknown-method handling, unauthenticated reads) — never a side-effecting business-tool call. |
| `payload-fuzzing` | yes | required **+ explicit approval** | `exploited-in-test` | Crafted hostile canary payloads to tool parameters. The most dangerous profile. |

`DEFAULT_PROFILE` is `passive` — a bare "probe this" cannot send traffic (AC1).

## Consent (AC2)

An active run may only proceed with a `ConsentRecord` that carries **all** of: an allowlisted target,
a declared ownership assertion, an acknowledging user, a dedicated (non-production) test identity,
and — for payload fuzzing — an explicit per-run approval. `ConsentRecord.validate` refuses the run if
any element is missing, and the whole record is copied verbatim into the audit trail, so the evidence
always answers *who authorized firing what at whom, under what limits, as which identity*.

The **allowlist** (`apiome.mcp_probe_targets`, V173) is where a target is enrolled: you may only fire
at a host someone explicitly declared they own or are authorized to test.

## Isolation (AC3)

`IsolationSpec` is the least-privilege sandbox contract a stdio target must run inside. Its defaults
are the *hardened* values, and `violations()` lists every guarantee a spec fails to provide:
read-only rootfs, `no_new_privileges`, all capabilities dropped, **no host socket**, restricted (or
disabled) egress, hard `pids`/memory/CPU/wall-clock limits, and disposability. `require_isolation`
turns any non-empty violation list into a refusal — so a stdio probe **cannot** run under a spec that
is not locked down. An http target contacts a remote host and needs restricted egress, not a local
sandbox.

The bytes-on-the-wire runner (Firecracker/gVisor/container) is **injected** as a `ProbeTransport`;
this module never touches a socket. That keeps the policy testable without real infrastructure and
lets the isolation runtime remain a deployment decision.

## Kill switch, rate & concurrency (AC5)

* **Global kill switch** — `mcp_probe_enabled` (default **false**). When off, *no* active probe runs
  for *any* tenant, regardless of consent. The passive lane is unaffected (it sends nothing), so the
  catalog keeps classifying observed behaviour even while active probing is frozen.
* **Per-tenant concurrency & rate** — `mcp_probe_max_concurrent_per_tenant`,
  `mcp_probe_max_runs_per_hour_per_tenant`. The authoritative counts come from the audit table
  (`mcp_probe_runs` in status `running`, and rows by `started_at`), so the caps hold across API
  replicas and restarts.
* **Per-run hard limits** — `ProbeLimits` (max requests, rate, wall-clock, max response bytes),
  enforced by `CountingTransport` at the one point all traffic passes through — not merely recorded.

Every active run, and every refusal, is written to `apiome.mcp_probe_runs` — the audit trail.

## The bridge to trust posture

CLX-3.2 shipped `make_proven_finding` and `ProbeEvidence` as a guarded, unused door. `app.mcp_probe_rules`
is the caller: it registers `REQUIRES_PROBE` trust-posture rules (`protocol.proven-auth-bypass`,
`protocol.proven-input-injection`) that turn an `exploited-in-test` probe finding into a `proven`
posture finding. It is loaded from the *probe* side (not the trust-posture packs) to keep the import
graph acyclic — so a trust-posture run in a context that never touched probing is byte-identical to
what CLX-3.2 produced. With no probe evidence, these rules are *skipped and reported*, never assumed
to pass.

## REST & CLI

```
GET    /v1/mcp/probes/catalog                         # probes, profiles, classification tiers
POST   /v1/mcp/{tenant}/endpoints/{id}/probe-targets  # enrol on the allowlist
GET    /v1/mcp/{tenant}/endpoints/{id}/probe-targets
DELETE /v1/mcp/{tenant}/endpoints/{id}/probe-targets/{target_id}
POST   /v1/mcp/{tenant}/endpoints/{id}/versions/{vid}/probe   # run a profile (passive default)
GET    /v1/mcp/{tenant}/endpoints/{id}/probe-runs     # audit trail
```

```
apiome mcp probe-catalog [--profile ...]
apiome mcp probe-target-add <endpoint> --i-own-or-am-authorized [--test-credential <id>]
apiome mcp probe-target-list <endpoint>
apiome mcp probe <endpoint> [--profile passive|safe-active|payload-fuzzing] [--i-approve-hostile-payloads]
apiome mcp probe-runs <endpoint>
```

An active run in a deployment with no probe runner configured passes every safety gate, records its
audit row, and then returns `503` — the gating is real and exercised even though the sandboxed
transport is a pluggable infrastructure component that this deployment does not enable.
