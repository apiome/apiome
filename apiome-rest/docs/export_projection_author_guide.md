# Export projection — emitter author guide (EFP-3.3, #4818)

> **Audience:** anyone adding a new export emitter or extending an existing one to
> support a new canonical construct.
> **Companion pages:** [Emitter SPI](./emitter_spi.md) (the `Emitter` contract itself),
> [projection guardrails](./projection_evidence_guardrails.md) (budgets, redaction,
> telemetry), and the user-facing
> [export-fidelity guide](../../docs/guide/export-fidelity.md) (what users see).

apiome promises users that pre-export projection evidence is **truthful**: every
non-preserved construct carries an honest cause category, a reviewed explanation, and —
only for a genuine specification limit — an authoritative destination-documentation
link. That promise is enforced by contract tests, but it is *kept* by emitter authors.
This page is the contract you sign when your emitter supports (or stops supporting) a
construct.

---

## The four obligations

For **every newly supported target construct** (and symmetrically, every construct you
stop supporting), you must update all four of:

| # | Obligation | Where | Enforced by |
|---|---|---|---|
| 1 | **Capability** — the static `CapabilityProfile` and, where the profile-derived default verdict would lie, the emitter's `fidelity_rule_pack()` | your emitter module | fidelity/report reconciliation tests (`tests/test_projection_corpus.py`) |
| 2 | **Reason** — a valid `ProjectionReason` for every non-preserved outcome your emitter produces | `src/app/projection_taxonomy.py` vocabulary; your rule pack verdicts | manifest validation rejects unknown codes; API + UI contract tests |
| 3 | **Documentation** — the destination's `DestinationCapability` entry: label, availability, reviewed `DocumentationEvidence` (or an explicit `documentation_unavailable` fallback) | `src/app/capability_registry.py` | registry snapshot tests; URL allowlist validation at model construction |
| 4 | **Fixtures** — projection corpus coverage: `DEEP` (with goldens) or `GENERIC`, or a documented `Waiver` | `tests/projection_corpus.py` (`CORPUS_COVERAGE`) | `test_every_emitter_declares_projection_coverage` fails on any unlisted emitter |

A PR that adds emitter behavior without all four is incomplete: the corpus gate
catches missing fixtures and unknown reason codes mechanically, but capability and
documentation honesty also need review — say in the PR body which constructs changed
status and why.

## Reason-code truthfulness rules

The taxonomy (`ProjectionReason`) has eight cause categories. The cardinal rule:

> **Never claim `destination_unsupported` when the real cause is apiome.**

- The destination's *specification* cannot represent the construct →
  `destination_unsupported`. This is the **only** category paired with a
  destination-format documentation link.
- The format could carry it but your emitter does not yet →
  `emitter_unsupported`. No destination link — the format is not at fault.
- The source lacked the detail (`source_incomplete`) or the parser could not capture
  it (`source_parse_limit`) → say so; the construct's status is usually `unavailable`,
  never a silent "preserved".
- A user-selected option excluded it → `option_excluded` (so the user knows a switch
  can flip it back).
- Redaction policy withheld it → `security_redacted`.
- A required external toolchain is missing in this runtime →
  `target_tool_unavailable`.
- It genuinely does not apply → `not_applicable`.

Statuses follow the same honesty rule: a reframed construct is `approximated` or
`transformed` (with the dropped semantics enumerated in the verdict), not `retained`;
invented target content (field numbers, synthesized ids) is `synthesized`. The
`AsyncApiEmitter` rule pack is the reference example: its profile says
`operations=False`, but the emitter *carries* reframed REST operations, so the pack
corrects the default critical `DROP` verdict to an honest `APPROX` — see
[emitter_spi.md](./emitter_spi.md#asyncapiemitter).

Also remember the manifest is **deterministic by contract**: same revision + target +
options + emitter version ⇒ same node/edge IDs, ordering, counts, and snapshot hash.
Acknowledgements and job provenance (EFP-3.1) key on that hash, so nondeterminism in
your emitter breaks the stale-preview guarantee, not just a test.

## Documentation-link governance

Destination-documentation links are **reviewed data in the capability registry**
(`src/app/capability_registry.py`), never ad-hoc strings in UI components or emitter
code.

**Adding or changing a link:**

1. The link must be the format's **authoritative** specification or reference —
   versioned or section-anchored where the format supports it (`DocumentationEvidence.version`
   / `.anchor`), so a user lands on the words that justify the claim.
2. Only `https` URLs on `ALLOWED_DOCUMENTATION_HOSTS` pass — exact lowercased host
   match, no ports, no credentials. `validate_documentation_url` runs at model
   construction, so an off-allowlist link cannot even be registered. If your format's
   authoritative host is missing, extend the allowlist **in the same PR** that adds the
   reviewed link using it, and justify the host's authority in the PR body.
3. No authoritative public spec? Set `documentation_unavailable=True` with a short
   `note` — a truthful "no stable public specification" beats a link to a wiki.
4. Update the entry's `review_date` and, because any entry/template/link change is a
   contract change, bump `REGISTRY_VERSION` (see version ownership below).

**Review ownership:**

- **Emitter author** (you): supplies and justifies the initial link, version, and
  anchor when adding a destination or construct; re-verifies affected anchors whenever
  bumping the emitter's targeted spec version.
- **Reviewer of the PR**: independently opens every added/changed URL and confirms it
  is the authoritative source, the anchor resolves, and the version label matches the
  page — link review is part of code review, not a follow-up.
- **Release owner**: before a release that touches export, re-runs the registry test
  suite and spot-checks `REVIEW_DATE`; a registry whose links were last reviewed more
  than a release cycle ago should be re-reviewed even without code changes (stale
  anchors are the common failure).

## Version-update ownership

Three version stamps make projection evidence attributable; each has one owner:

| Stamp | Owner | Bump when |
|---|---|---|
| `emitter_version` (per emitter) | emitter author | any change to emitted output, capability profile, or rule pack verdicts |
| `REGISTRY_VERSION` + entry `review_date` (`capability_registry.py`) | whoever edits the registry | any capability entry, reason template, or documentation link change |
| apiome-rest OpenAPI version (`AGENTS.md` rule) | whoever changes the REST contract | any change to the export routes/models |

All three are folded into the projection snapshot hash, so bumping them correctly is
what invalidates stale acknowledgements when behavior changes — skipping a bump lets a
user's old acknowledgement silently cover new behavior. When in doubt, bump.

## Fixture obligations (the corpus gate)

`tests/projection_corpus.py` declares `CORPUS_COVERAGE`: **every registered emitter
format must appear exactly once** as `DEEP`, `GENERIC`, or a `Waiver`:

- `DEEP` — for targets that claim addressable output locations: manifest goldens,
  artifact emission, and target-pointer resolution against the emitted document.
  Regenerate goldens with `UPDATE_PROJECTION_GOLDENS=1`; goldens must stay
  deterministic and **redacted** (the corpus plants a sentinel secret to prove it).
- `GENERIC` — joins the all-emitter sweep: determinism, report reconciliation,
  envelope parity, and registry-evidence completeness.
- `Waiver("reason")` — an explicit, documented opt-out for a target whose manifest
  genuinely cannot be exercised in CI. An empty reason fails.

When your emitter starts supporting a new construct, extend the fixtures so the corpus
*exercises* it — a status that never appears in a fixture is a status the contract
tests cannot defend. The shared fixtures already cover all seven statuses and all
eight reason categories; keep it that way.

## Author checklist

Before requesting review for an emitter change:

- [ ] `CapabilityProfile` reflects what the target represents **faithfully** (not
      approximated/synthesized).
- [ ] `fidelity_rule_pack()` corrects any profile-derived verdict that would lie.
- [ ] Every non-preserved outcome carries the honest `ProjectionReason`;
      `destination_unsupported` only for true specification limits.
- [ ] `DestinationCapability` entry updated: label, availability, documentation
      evidence or truthful `documentation_unavailable`, `review_date`.
- [ ] New/changed documentation URLs are authoritative, versioned/anchored, on the
      allowlist, and were opened and verified by a human.
- [ ] `CORPUS_COVERAGE` updated (`DEEP`/`GENERIC`/`Waiver`); fixtures exercise the
      new constructs; goldens regenerated, deterministic, and redacted.
- [ ] `emitter_version` bumped; `REGISTRY_VERSION` bumped if the registry changed;
      apiome-rest OpenAPI version bumped if the REST contract changed.
- [ ] `pytest tests/test_projection_corpus.py tests/test_capability_registry.py`
      (and the export route tests) pass with no warnings or skips.
