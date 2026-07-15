# Axis score algorithm (`clx-axis-v1`)

Apiome rolls catalog and MCP lint evidence into a multi-axis evaluation. The algorithm
identity shown in the UI is:

| Field | Value |
|-------|--------|
| Algorithm id | `clx-axis-v1` |
| Algorithm version | `1` (implementation revision) |

Source: `apiome-rest/src/app/axis_score.py` (`ALGORITHM_ID`, `ALGORITHM_VERSION`).

## What the axes mean

Axes include quality, protocol, security, supply chain, supportability, and compatibility.
An axis that has not been scanned is **not assessed** — that is not a clean score.

Composite scores are withheld until required coverage is met (v1: the `quality` axis).

## Honesty guarantees

- Skipped rules (missing transcript, source, SBOM, or probe consent) never count as passes.
- Static trust-posture findings are **signals**, not proven exploits, until a consent-gated
  probe demonstrates exploitability ([MCP probes](../../apiome-rest/docs/mcp_probes.md)).

## Related documentation

- [Lint & quality](lint-and-quality.md)
- [Scanner evaluation corpus](../../apiome-rest/docs/scanner_evaluation.md) (CLX-4.3)
- [MCP trust posture](../../apiome-rest/docs/mcp_trust_posture.md)
- Built-in schema rules: [lint-rules.md](lint-rules.md)
