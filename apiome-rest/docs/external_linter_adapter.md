# External-linter adapter SPI (CLX-2.1)

> **Status:** sandboxed adapter registry + restricted runner + JSON/JSONL/SARIF parsers —
> `src/app/external_linter_adapter.py`, `external_linter_runner.py`, `external_linter_parsers.py`,
> `external_linter_evidence.py`
> **Issue:** [#4851](https://github.com/apiome/apiome/issues/4851) ·
> **Epic:** CLX-EPIC-2 (#4845) · Refines MFI-4.3 (#3748)

Each tool integration should not invent its own execution, version pinning, temporary-file
handling, output parsing, resource limits, or operational-failure semantics. This SPI
generalizes the Buf lint pattern onto the MFI-5.x toolchain runner and the CLX-1.1 evidence
contract.

```
 AdapterDeclaration ─▶ RestrictedRunner ─▶ tool stdout
                              │                 │
                              ▼                 ▼
                     failure kinds      JSON / JSONL / SARIF
                     (timeout / …)              │
                              │                 ▼
                              └────▶ envelope + evidence run
                                           │
                                           ▼
                                    coverage_entries
```

## Adapter declaration

An adapter publishes:

| Field | Meaning |
|-------|---------|
| `adapter_id` | Registry key (e.g. `buf.lint`) |
| `scanner_id` | Evidence scanner id |
| `formats` / `scan_modes` | What the adapter accepts |
| `tool_key` | MFI-5.1/5.2 toolchain tool |
| `output_format` | `json` / `jsonl` / `sarif` |
| `adapter_version` | Stamped on every evidence run |

Register with `register=True` (same pattern as import sources / rule packs):

```python
class BufLintAdapter(ExternalLinterAdapter, register=True):
    adapter_id = "buf.lint"
    formats = ("protobuf",)
    tool_key = "buf"
    output_format = "jsonl"
    ...
```

Look up with `get_adapter`, list with `available_adapters`, filter with `adapters_for_format`.

## Restricted runner

`RestrictedRunner` wraps `ToolchainRunner`:

- explicit argv (never a shell);
- default no-network `SandboxPolicy` (MFI-5.3);
- input/output / resource caps from that policy;
- logs redact secret-bearing env keys (`token`, `password`, `api_key`, …) and never dump stdout/stderr.

Failures are classified as `unavailable` / `timeout` / `crash` / `malformed` / `failed` /
`blocked_by_policy` so adapters and tests do not catch raw toolchain exceptions.

## Parsers and normalizers

| Format | Parser | Notes |
|--------|--------|-------|
| JSON | `parse_json_document` | Array, `{findings\|results\|issues}`, or single object |
| JSONL | `parse_jsonl` | Hard-fails on malformed lines (`parse_jsonl_tolerant` remains for Buf) |
| SARIF 2.1 | `parse_sarif` | Preserves source `ruleId` and `physicalLocation` path/line/column |

`envelope_from_tool_finding` projects tool findings into the CLX-1.1 evidence envelope.

## Evidence

`adapter_evidence_run` / `AdapterRunResult.to_evidence_run` build write-ready evidence-run
dicts. Timeout, unavailable tool, malformed output, and crash become `outcome=failed` or
`unavailable` with `coverage.state=none` — never silent absence. Persistence into
`lint_evidence_runs` at score-capture time is left to later CLX consumers (#4852+).

## Built-in: Buf lint

`BufLintAdapter` is the real-tool conformance target. `proto_lint.run_buf_lint` delegates to
it so existing merge / score callers keep working.

## Built-in: OpenAPI validation packs (CLX-2.2 / #4852)

Spectral, Vacuum, and Redocly adapters live in `openapi_validation_adapters.py` and are
orchestrated by `openapi_validation_pack.py`. See
[`openapi_validation_packs.md`](./openapi_validation_packs.md).

## Conformance

- Fixture corpus: `tests/fixtures/external_linter/`
- Unit tests: `tests/test_external_linter_adapter.py`
- Conformance: `tests/test_external_linter_conformance.py` (fake tool always; real `buf` gated)
- OpenAPI packs: `tests/test_openapi_validation_packs.py` +
  `tests/fixtures/openapi_validation_parity/`

## Relationship

- **CLX-1.1 (#4848)** — evidence outcomes / envelope / coverage.
- **MFI-5.1–5.3** — toolchain runner, packaging, sandbox.
- **MFI-4.3 (#3748)** — refined by this SPI; Spectral/Vacuum/Redocly packs are CLX-2.2 (#4852).
- **CLX-2.2 (#4852)** — OpenAPI validation packs and evidence capture at score time.