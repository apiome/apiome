# Message pact / AsyncAPI comparison corpus — PFX-3.6 (#6936)

Golden verdicts for `app.pact_asyncapi_compare.compare_pact_to_asyncapi`, read by
`tests/test_pact_asyncapi_compare.py`.

| Path | What it holds |
| --- | --- |
| `providers/` | The provider contracts: `orders-3.0.yaml` (AsyncAPI 3.0: send / receive operations, a templated address, Avro and PDF payloads, a payload outside the document) and `streetlights-2.6.json` (AsyncAPI 2.6: `subscribe` / `publish`, a `oneOf` message). |
| `pacts/` | One hand-written pact per case: Pact 3 message pacts (`messages`) and Pact 4 pacts with `Asynchronous/Messages` interactions. The id prefix is the intended verdict: `pass-`, `fail-`, `partial-`. `pass-06` and `pass-07` are written in the shapes pact-js and pact-jvm produce. |
| `cases.json` | The manifest: for each case its pact, its provider, the **intended** verdict and the failure, fidelity and warning codes it must produce. Written by hand, never regenerated. |
| `expected/` | The full comparison output per case, without the validator's own `detail` text. |

Two codes are reached only with a purpose-built document and are covered by unit tests in the same
file instead: `message.ambiguous` (more than 50 candidate messages) and `findings-truncated`.

## Changing the corpus

Add a pact under `pacts/` and its entry to `cases.json` with the verdict and codes you intend.
Then record the full output and review the diff:

```bash
UPDATE_PACT_ASYNCAPI_GOLDENS=1 PYTHONPATH=. uv run pytest tests/test_pact_asyncapi_compare.py
```

The update writes `expected/` only. A case whose result disagrees with `cases.json` still fails, so
a change in the engine cannot rewrite an intended verdict.
