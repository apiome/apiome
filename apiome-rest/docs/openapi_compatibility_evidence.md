# OpenAPI compatibility evidence (CLX-2.3 / #4853)

Independent OpenAPI revision comparison via **oasdiff**, persisted as CLX-1.1
lint evidence and exposed for CI gates as normalized JSON, SARIF, or JUnit.

Native `CompatibilityCheckEngine` merge/rollback gates are unchanged. oasdiff
evidence is additive.

## Adapter

| Field | Value |
|-------|--------|
| Adapter / scanner id | `oasdiff.breaking` |
| SPI | `ExternalLinterAdapter` (`ScanMode.BREAKING`) |
| Tool key | `oasdiff` (`APIOME_OASDIFF_BIN`) |
| Command | `oasdiff changelog base revision --format json --allow-external-refs=false` |

Severity mapping (oasdiff `level` → Apiome):

| oasdiff | Envelope severity | `changeClass` |
|---------|-------------------|---------------|
| ERR (3) | error | breaking |
| WARN (2) | warning | dangerous |
| INFO (1) | info | informational |

Rendered changelog (markdown) is stored under evidence `coverage.changelogMarkdown`.
Optional HTML comes from `openapi-changes` when available, otherwise
`oasdiff --format html`.

## REST

- `POST /v1/versions/{tenant}/{project}/compatibility/evidence`  
  Body: `{ baseRevisionId, headRevisionId }`. Runs oasdiff, persists evidence on
  the head revision, returns normalized JSON.  
  Query `?format=sarif|junit` (or matching `Accept`) for gate artifacts.
- `GET /v1/versions/{tenant}/{project}/{version}/compatibility/evidence`  
  Lists persisted `oasdiff.breaking` runs (JSON), or emits the latest run as
  SARIF/JUnit when `?format=` is set.

Best-effort capture also runs when:

- `POST …/compatibility` (native check) succeeds
- `GET …/lint?baseRevisionId=` folds a base comparison

## CLI

```bash
apiome compat --project payments-api --version 1.1.0 --base-version 1.0.0
apiome compat --project payments-api --version 1.1.0 --base-version 1.0.0 --format sarif
apiome compat --project payments-api --version 1.1.0 --base-version 1.0.0 --fail-on dangerous
```

Exit non-zero when findings meet `--fail-on` (default `breaking`).

## Failure → coverage

Unavailable tool, timeout, crash, or malformed JSON map to CLX-1.1
`unavailable` / `failed` outcomes with `coverage.state=none` — never a false clean scan.

## Packaging

Pinned in `toolchain_packaging.BUNDLED_TOOLS` and installed in the REST image
Dockerfile (`OASDIFF_VERSION`). `openapi-changes` is declared but optional.
