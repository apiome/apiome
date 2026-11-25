# Pact / OpenAPI comparison corpus — PFX-2.2 (#6926)

Golden verdicts for `app.pact_oas_compare.compare_pact_to_oas`, read by
`tests/test_pact_oas_compare.py`.

| Path | What it holds |
| --- | --- |
| `providers/` | The provider contracts: `ledger-api-3.0.yaml` (OpenAPI 3.0) and `storefront-3.1.json` (OpenAPI 3.1). |
| `pacts/` | One hand-written pact per case. The id prefix is the intended verdict: `pass-`, `fail-`, `partial-`. |
| `cases.json` | The manifest: for each case its pact, its provider, the **intended** verdict and the failure, fidelity and warning codes it must produce. Written by hand, never regenerated. |
| `expected/` | The full comparison output per case and per foreign pact, without the validator's own `detail` text (its wording belongs to the `jsonschema` release). |
| `foreign/` | Pacts written by the Pact libraries themselves, compared with `providers/ledger-api-3.0.yaml`. |

## Foreign pacts

Each file is the unedited output of a consumer test run against the library's own mock server:

| File | Written by | Specification |
| --- | --- | --- |
| `pact-js-v3.json` | `@pact-foundation/pact` 17.1.4 (`PactV3`) | 3.0.0 |
| `pact-js-v4.json` | `@pact-foundation/pact` 17.1.4 (`PactV4`) | 4.0 |
| `pact-go-v4.json` | `github.com/pact-foundation/pact-go/v2` (`NewV4Pact`), Pact FFI 0.5.12 | 4.0 |
| `pact-jvm-v3.json` | `au.com.dius.pact.consumer:junit5` 4.6.17 (`PactDslWithProvider`) | 3.0.0 |

To add one, run a consumer test with the library, copy the pact file here unchanged and record
its expected output.

## Changing the corpus

Add a pact under `pacts/` and its entry to `cases.json` with the verdict and codes you intend.
Then record the full output and review the diff:

```bash
UPDATE_PACT_OAS_GOLDENS=1 uv run pytest tests/test_pact_oas_compare.py
```

The update writes `expected/` only. A case whose result disagrees with `cases.json` still fails,
so a change in the engine cannot rewrite an intended verdict.
