# objectified-cli

Python 3.12+, typer, httpx, pydantic-settings, py-yaml12, jsonschema, openapi-spec-validator

## Rules

This file applies **only** to the `objectified-cli` package. It complements the repository root `AGENTS.md`. **Keep it current** when commands, layout, configuration, HTTP client behaviour, or REST contract alignment changes.

## Role

`objectified-cli` is a **client** for [objectified-rest](../objectified-rest). It does not implement business logic or database access. All persistence and import orchestration live in the REST service; the CLI validates inputs locally, calls HTTP endpoints, formats output, and maps errors to process exit codes.

## REST contract

The **canonical API contract** is `objectified-rest/openapi.yaml` (OpenAPI **3.2.0**, JSON Schema 2020-12 dialect). See [OpenAPI 3.2](https://spec.openapis.org/oas/v3.2.0.html) and [`objectified-rest/AGENTS.md`](../objectified-rest/AGENTS.md) for server-side rules.

**Do not** invent routes or request/response shapes in the CLI. When the REST API changes:

1. Update the REST OpenAPI spec and implementations in `objectified-rest` first.
2. Align CLI paths, payloads, and field names with the committed contract.
3. Update tests (`pytest-httpx` mocks and integration tests under `tests/integration/`).

Key REST surfaces used by the CLI:

| Area | Endpoints (representative) |
|------|----------------------------|
| Health | `GET /health` (anonymous) |
| List / get | `GET /projects`, `GET /properties`, `GET /schemas`, `GET /project-versions`, `GET /types`, `GET /{resource}/{id}` |
| Paths / workflows | `GET /versions/{version_id}/paths`, `GET /versions/{version_id}/paths/{path_id}`, `GET .../operations`, `GET /versions/{version_id}/workflows`, `GET .../steps` |
| API keys | `GET /api-keys`, `GET /api-keys/policy`, `PUT /api-keys/policy`, `POST /api-keys`, `GET /api-keys/mcp-tools`, `GET /api-keys/{id}`, `POST /api-keys/{id}/rotate`, `DELETE /api-keys/{id}` |
| Integrations | `GET /dashboard/linked-accounts` (session bearer) |
| Repositories | `GET /tenants/{id}/repositories`, `POST /tenants/{id}/repositories`, `POST /tenants/{id}/repositories/test-public-url`, `POST /tenants/{id}/repositories/{repository_id}/scans`, `GET /tenants/{id}/repositories/{repository_id}/scans/{scan_id}`, `GET /tenants/{id}/repositories/{repository_id}/files`, `POST /tenants/{id}/repositories/{repository_id}/files/{file_id}/sniff`, `POST /tenants/{id}/repositories/{repository_id}/files/{file_id}/verify`, `POST /tenants/{id}/repositories/{repository_id}/files/{file_id}/import`, `POST /tenants/{id}/repositories/{repository_id}/imports:batch`, `POST /tenants/{id}/repositories/{repository_id}/imports:manifest`, `GET /tenants/{id}/repositories/{repository_id}/imports` (API key; tenant scope required); linked-account resolution uses `GET /dashboard/linked-accounts` and `GET /dashboard/linked-accounts/{id}/repositories` (session bearer) |
| Import | `POST /imports/openapi`, `POST /imports/arazzo`, `POST /imports/json-schema`, `POST /imports/json-schema-type`, `GET /imports/{job_id}` |
| Spec export | `GET /browse/tenants/{tenant}/projects/{project}/versions/{version}/spec?format=openapi\|arazzo` (optional API key) |
| Import provenance | `GET /versions/{id}/import-source`, `GET /versions/{id}/import-fidelity-diff` (API key) |

Tier 2 commands require `X-API-Key` (see **Auth** below). Tier 1 `GET /health` does not.

## CLI guidelines ([clig.dev](https://clig.dev/))

Follow [Command Line Interface Guidelines](https://clig.dev/):

- **Help:** `-h` / `--help` on every command; concise default help when invoked with no subcommand (`main.py` → `echo_concise_help()`).
- **Exit codes:** `exit_codes.py` — `0` success, `1` error, `2` usage (`EXIT_SUCCESS`, `EXIT_ERROR`, `EXIT_USAGE`). Map HTTP 4xx → usage, 5xx → error (`client/errors.py`).
- **Streams:** human tables and JSON on **stdout**; diagnostics, progress spinners, and tracebacks (with `--verbose`) on **stderr**.
- **Machine output:** global `--json` emits raw API JSON on stdout.
- **Configuration precedence** (highest first): CLI flags → `OBJECTIFIED_*` env → dotenv files (default package + cwd `.env`, or `--env-file`) → `~/.config/objectified/config.toml` → defaults. Document new settings in `.env.example` and `README.md`.
- **Secrets:** never log or print full API keys (`config show` masks `api-key`).
- **Examples:** keep copy-pasteable examples in `README.md` when adding commands.

## Layout

| Path | Role |
|------|------|
| `src/objectified_cli/main.py` | Typer root app, global flags, console entry `run()` |
| `run.sh` | Load `.env`, ensure `.venv`, forward argv to `objectified` or start interactive/batch mode |
| `src/objectified_cli/run_interactive.py` | Interactive prompt and stdin batch runner used by `run.sh` |
| `src/objectified_cli/cli_context.py` | Resolve settings, timeout, `--json`, `--no-progress`, `--insecure` from context |
| `src/objectified_cli/config.py` | `CliSettings`, TOML user config, env/flag overrides |
| `src/objectified_cli/client/http.py` | `RestClient` (httpx sync), auth headers |
| `src/objectified_cli/client/pagination.py` | Offset/limit pagination for list commands |
| `src/objectified_cli/client/repos_add.py` | Linked-account and public-URL payload builders for `repos add` |
| `src/objectified_cli/client/repos_files.py` | Repository file list filters and table output for `repos files` |
| `src/objectified_cli/client/repos_inspect.py` | Sniff and deep-verdict output for `repos inspect` |
| `src/objectified_cli/client/repos_closure.py` | `$ref` closure resolution for `repos inspect --closure` and `repos files --closure` |
| `src/objectified_cli/client/repos_import.py` | Import mapping validation and REST body builder for `repos import` |
| `src/objectified_cli/client/repos_import_batch.py` | Batch file selection, import map parsing, and summary output for `repos import --files` |
| `src/objectified_cli/client/repos_import_manifest.py` | Manifest import request builder, local manifest validation, and summary output for `repos import --manifest` |
| `src/objectified_cli/client/repos_imports.py` | Import provenance list filters and table output for `repos imports` |
| `src/objectified_cli/client/repos_verify.py` | Integrity/signature trust assessment and output for `repos verify` |
| `src/objectified_cli/client/repos_scan.py` | Scan enqueue output and poll loop for `repos scan --wait` |
| `src/objectified_cli/client/errors.py` | `CliError`, HTTP → exit code, concise help |
| `src/objectified_cli/client/browse_scope.py` | Resolve tenant/project/version slugs for browse spec export |
| `src/objectified_cli/client/spec_download.py` | Browse spec and import-source HTTP download helpers |
| `src/objectified_cli/spec_output.py` | Write document bytes; emit metadata on stdout/stderr per clig.dev |
| `src/objectified_cli/commands/` | Typer subcommands (`auth`, `api-keys`, `integrations`, `config`, `doctor`, `health`, `projects`, `properties`, `schemas`, `types`, `tokens`, `versions`, `paths`, `operations`, `workflows`, `spec`, `import`, `repos`) |
| `src/objectified_cli/paths_inventory.py` | REST helpers to resolve paths, operations, and workflow steps |
| `src/objectified_cli/output_paths.py` | Human tables for path/operation/workflow inspection |
| `src/objectified_cli/import_/` | OpenAPI/Arazzo/JSON Schema load (file, stdin, URL), validate, detect, upload, job poll |
| `src/objectified_cli/extract/` | OpenAPI `info` metadata and slug helpers |
| `src/objectified_cli/output.py` | Human tables and import result formatters |
| `src/objectified_cli/progress.py` | Stderr progress during long imports |
| `tests/` | Unit tests (no network); `tests/integration/` uses `pytest-httpx` mocks |
| `test/scaffold.test.mjs` | Node scaffold checks (package.json, pyproject, paths) |

## Commands (Typer)

Registered in `main.py`:

| Group | Purpose |
|-------|---------|
| `help` | Concise usage, or subcommand help (`objectified help projects list`) |
| `auth` | `whoami`, `status`, `tenants` (session bearer; `GET /auth/me`, `/auth/tenants`) |
| `config` | `show` / `set` / `unset` for `base-url`, `tenant`, `api-key`, `session-token` |
| `doctor` | Anonymous connectivity probe (`GET /health`) |
| `health` | Print health JSON |
| `projects` | `list`, `get` |
| `properties` | `list`, `get` |
| `schemas` | `list`, `get` |
| `types` | `list`, `show`, `search` (public `GET /types`; no API key), `publish`, `unpublish` (master tenant API key) |
| `versions` | `list`, `get` (REST path `project-versions`) |
| `paths` | `list`, `show` (`GET /versions/{version_id}/paths`, filters: `--method`, `--tag`, `--q`) |
| `lint` | Quality score + findings for a version (`GET /versions/{tenant}/{project}/{version}/lint`); `--base-version` folds breaking-change risk; `--min-grade A..F` gates CI exit code |
| `operations` | `show` (resolve by operation UUID or `operationId`) |
| `workflows` | `list`, `show` (`GET /versions/{version_id}/workflows`, steps sub-resource) |
| `spec` | `export` (browse reconstructed OpenAPI/Arazzo), `download-original` (`GET /versions/{id}/import-source`) |
| `import` | `openapi`, `arazzo`, `json-schema`, `json-schema-type` |
| `tokens` | `list`, `create`, `revoke` personal access tokens (`/auth/personal-access-tokens`) |
| `api-keys` | `list`, `create`, `show`, `rotate`, `revoke`, `policy get`, `policy set` workspace API keys (`/api-keys`) |
| `list-api-keys` | Top-level alias for `api-keys list` |
| `integrations` | `list`, `show` linked services (`GET /dashboard/linked-accounts`, session bearer) |
| `repos` | `list` tenant repositories (`GET /tenants/{id}/repositories`, filters: `--provider`, `--status`, `--name`; `--format table\|json`); `add` registers via public URL (`--url`, optional `--branch`) or linked account (`--account`, `--repo`, session bearer + API key); `scan` enqueues a branch scan (`POST /tenants/{id}/repositories/{repository_id}/scans`, optional `--branch`; `--wait` polls `GET …/scans/{scan_id}` and prints file counts); `files` lists scanned files (`GET …/files`, filters: `--glob`, `--regex`, `--preset`, `--detected-kind`, `--importable/--not-importable`; `--closure` adds a closure indicator column; table shows detected kind + importable verdict); `inspect` runs content sniff (`POST …/files/{file_id}/sniff`; prints verdict, kind, version, and reasons; `--closure` prints resolved/missing `$ref` members via `GET …/files/{file_id}/content` + file tree; `--deep` runs deep pre-import verdict (`POST …/files/{file_id}/verify`; prints validation/lint/fidelity/secrets findings and exits non-zero on blocking findings; `--format table\|json`); `verify` checks integrity + signature metadata (`GET …/files` or `GET …/files/{file_id}`; exits non-zero on integrity or invalid-signature failures; `--format table\|json`); `import` imports one repository file (`POST …/files/{file_id}/import`), many via batch import (`POST …/imports:batch` with `--files`/`--regex` file selection and optional `--map` YAML/JSON per-path mappings), or per manifest (`POST …/imports:manifest` with `--manifest`, or `--manifest-file PATH` for a local `.objectified.yaml`); `--new-project` or `--project` with `--version-id` / `--version-name` (batch only); optional `--dry-run`, `--resume-run-id`; reuses `emit_import_result` / batch or manifest summary output); `imports` lists import provenance (`GET …/imports`, filters: `--project`, `--version-id`, `--actor`, `--since`, `--until`; table shows file path, project, version, importer, imported_at, blob SHA) |

Global flags on the root callback: `--base-url`, `--tenant`, `--api-key`, `--session-token`, `--env-file`, `--json`, `--verbose`, `--timeout`, `--no-progress`, `--insecure`.

Add new subcommands as modules under `commands/` and register with `app.add_typer()` in `main.py`.

### Repository Store (`repos`)

Tenant-scoped Git repository commands live in `commands/repos.py` with client helpers under
`client/repos_*.py`. The CLI mirrors the Control Panel Repositories tab: register a repo, scan a
branch, browse files, sniff importability, verify trust signals, run deep pre-import verdicts,
import via the existing single-file importer (single, batch, or manifest), and list provenance.
**Do not fork** import logic — `repos import` calls
`POST /tenants/{id}/repositories/{repository_id}/files/{file_id}/import` and reuses
`emit_import_result` from `output.py`.

| Subcommand | REST surface | Auth |
|------------|--------------|------|
| `repos list` | `GET /tenants/{id}/repositories` | API key + tenant |
| `repos add` (public URL) | `POST …/test-public-url`, `POST …/repositories` | API key + tenant |
| `repos add` (linked account) | `GET /dashboard/linked-accounts`, `GET …/repositories`, `POST …/repositories` | API key + tenant + session bearer |
| `repos scan` | `POST …/scans`, `GET …/scans/{scan_id}` (when `--wait`) | API key + tenant |
| `repos files` | `GET …/files`, `GET …/files/{file_id}/content` (when `--closure`) | API key + tenant |
| `repos inspect` | `POST …/files/{file_id}/sniff`, `POST …/files/{file_id}/verify` (when `--deep`) | API key + tenant |
| `repos verify` | `GET …/files`, `GET …/files/{file_id}` | API key + tenant |
| `repos import` | `POST …/files/{file_id}/import`, `POST …/imports:batch`, `POST …/imports:manifest` | API key + tenant |
| `repos imports` | `GET …/imports` | API key + tenant |

**Trust flags:** `repos inspect --deep` calls `POST …/verify` and exits non-zero on blocking
findings. `repos verify` checks `content_integrity_verified` and `signature_status` and exits
non-zero on integrity or invalid-signature failures. `repos import --manifest` drives
`POST …/imports:manifest`; `--manifest-file PATH` validates a local `.objectified.yaml` and
resolves targets against scanned repository files.

Copy-pasteable examples for each subcommand are in [`README.md`](README.md) under
**Repository Store** (workflow + per-command subsections). When adding flags or REST fields,
update that section and the `repos` row in **Commands** above.

## Implementation rules

- **Python ≥ 3.14**, **uv** + `.venv`, PEP 8, `ruff` for lint. After dependency changes: `uv lock` and commit `uv.lock`.
- **HTTP:** use `RestClient` and `settings_from_context()`; do not open raw httpx calls in commands except via the client layer.
- **Auth:** `doctor` uses `RestClient(..., anonymous=True)` for unauthenticated `GET /health`; `health` uses normal `RestClient(...)` behavior (it may send `X-API-Key` when configured). Tier 2 list/import/get and `api-keys` commands use workspace API key auth (`X-API-Key`). `types list`, `types show`, and `types search` use `RestClient(..., anonymous=True)` for public `GET /types` reads; `types publish` and `types unpublish` require the master tenant API key. `auth`, `tokens`, and `integrations` use `RestClient(..., session=True)` with `Authorization: Bearer` from `OBJECTIFIED_SESSION_TOKEN` / `--session-token`; `tokens create` prints the raw PAT only once in human mode.
- **Imports:** validate OpenAPI (`openapi-spec-validator`), Arazzo 1.0 (vendored JSON Schema 2020-12 in `import_/schemas/arazzo/`), and JSON Schema 2020-12 (`jsonschema`) locally before upload; load documents from local paths, stdin (`-`), or `http`/`https` URLs via `import_/source.py`; use `import_/detect.py` to reject wrong document types with actionable messages. `import auto` resolves the format from content markers (`openapi`/`swagger`/`arazzo`/`$schema`); content always wins, and a `*.arazzo.{yaml,yml,json}` filename hint routes to Arazzo only as a last resort when no marker matches (mirrors the REST scanner; stdin has no filename hint). Optional ``--publish public|private`` (alias ``--visibility``) sets REST ``visibility`` on OpenAPI/Arazzo import (`private` → ``protected``); omit to leave the version as ``draft``. For ``import json-schema-type``, ``--publish public`` sets REST ``system: true`` (system-wide library; master tenant only); ``--publish private`` or omit defaults to tenant scope.
- **JSON Schema MVP:** only the file given is imported; external `$ref` targets are not resolved (document in README when behaviour changes).
- **Timeouts:** default 30 s; import poll/upload default 120 s unless `--timeout` is set (`cli_context.import_timeout_from_context`).
- **DRY:** reuse `output.py`, `client/pagination.py`, and `import_/upload.py` rather than duplicating format or poll logic.

## Testing

| Layer | Location | Notes |
|-------|----------|-------|
| Unit | `tests/test_*.py` | No live network; mock HTTP with `pytest-httpx` where needed; `repos` coverage in `tests/test_repos_commands.py` plus `tests/test_repos_*_helpers.py` |
| Integration (mocked) | `tests/integration/` | Import wait loop and list commands against mocked REST |
| Scaffold | `tests/test_scaffold.py`, `test/scaffold.test.mjs` | Package layout and tooling |
| Docs | `tests/test_readme.py`, `tests/test_agents.py` | README and AGENTS.md guard required sections |
| Fixtures | `tests/fixtures/` | Synthetic OpenAPI/Arazzo samples (no credentials or PII) for import/export tests |

Run from monorepo root or package:

| Task | Command |
|------|---------|
| Install / build | `yarn cli:build` or `cd packages/objectified-cli && uv sync` |
| Test | `yarn cli:test` or `uv run pytest tests/ -v && node --test test/*.test.mjs` |
| Lint | `yarn cli:lint` or `uv run ruff check src/ tests/` |

Tests must pass with **no warnings, no errors, and no skips** before merge.

## Review checklist

- [ ] Behaviour matches `objectified-rest/openapi.yaml` (no ad-hoc API shapes)
- [ ] [clig.dev](https://clig.dev/) exit codes, stdout/stderr split, and help text respected
- [ ] New env vars in `.env.example`; config precedence documented in `README.md`
- [ ] `AGENTS.md` and `README.md` updated if commands, layout, or conventions changed
- [ ] Unit and/or integration tests added; `yarn cli:test` and `yarn cli:lint` pass
- [ ] No secrets in logs, commits, or test fixtures

## Related docs

- [`README.md`](README.md) — install, configuration, examples
- [`docs/ROADMAP_OBJECTIFIED_CLI.md`](../../docs/ROADMAP_OBJECTIFIED_CLI.md) — planned commands and epics
- [`packages/objectified-rest`](../objectified-rest) — REST service and OpenAPI contract
