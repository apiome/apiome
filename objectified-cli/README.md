# objectified-cli

Command-line client for the [Objectified](https://github.com/KenSuenobu/objectified) REST API. Import OpenAPI, Arazzo, and JSON Schema documents, list tenant resources, and manage configuration from the terminal.

Follows [clig.dev](https://clig.dev/) guidelines: structured help (`help`, `-h` / `--help`), sensible exit codes, human-readable tables on stdout, and diagnostics on stderr.

## Install

**Requirements:** Python ≥ 3.14, [uv](https://docs.astral.sh/uv/) (recommended).

From the monorepo:

```bash
cd packages/objectified-cli
uv sync
uv run objectified --version
```

`uv sync` installs the `objectified` console script into `.venv/bin`. Use `uv run objectified …`, `.venv/bin/objectified …`, or activate the virtual environment before calling `objectified` directly.

From the repository root via Turborepo:

```bash
yarn cli:build
yarn cli:test
```

### Run script

`run.sh` loads `.env` from this package, ensures the local `.venv` exists, and runs the CLI:

```bash
cd packages/objectified-cli
./run.sh --version
./run.sh doctor
./run.sh projects list
```

With **no arguments**, `run.sh` starts an interactive prompt (`objectified>`) when stdin is a TTY, or reads **one command per line** from stdin (batch mode):

```bash
./run.sh
objectified> doctor
objectified> projects list
objectified> exit

printf '%s\n' "doctor" "projects list" | ./run.sh
```

Equivalent via Yarn: `yarn run` from `packages/objectified-cli`.

## Configuration

Settings resolve in this order (highest wins first):

1. CLI flags (`--base-url`, `--tenant`, `--api-key`, `--session-token`, `--env-file`)
2. Environment variables (`OBJECTIFIED_*`)
3. Dotenv files (default: package `.env` then `.env` in the current working directory; `--env-file` replaces both with a single file)
4. User config file (`$XDG_CONFIG_HOME/objectified/config.toml`, default `~/.config/objectified/config.toml`)
5. Built-in defaults (`base_url` → `http://localhost:8000`)

### Environment variables

| Variable | Description |
|----------|-------------|
| `OBJECTIFIED_BASE_URL` | REST API base URL (default `http://localhost:8000`) |
| `OBJECTIFIED_TENANT_ID` | Tenant UUID (optional; some operations need tenant scope) |
| `OBJECTIFIED_API_KEY` | API key sent as `X-API-Key` (required for Tier 2 API-key-authenticated commands/routes, including list/import and `api-keys`) |
| `OBJECTIFIED_SESSION_TOKEN` | UI session bearer token from `POST /auth/login` (required for `auth`, `tokens`, and `integrations` commands) |

Copy the package template and edit values:

```bash
cd packages/objectified-cli
cp .env.example .env
# edit OBJECTIFIED_BASE_URL, OBJECTIFIED_TENANT_ID, OBJECTIFIED_API_KEY
```

Or export variables for a single shell session:

```bash
export OBJECTIFIED_BASE_URL=https://api.example.com
export OBJECTIFIED_API_KEY=obj_your_key_here
```

Use an alternate dotenv file for one invocation:

```bash
objectified --env-file /path/to/staging.env doctor
```

### User config file

Persist defaults with `objectified config` (writes `~/.config/objectified/config.toml`):

```bash
objectified config set base-url https://api.example.com
objectified config set api-key obj_your_key_here
objectified config show
objectified config unset tenant
```

You can also edit the file directly. Top-level keys or an `[objectified]` table are supported:

```toml
base_url = "https://api.example.com"
tenant_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
api_key = "obj_your_key_here"
```

```toml
[objectified]
base_url = "https://api.example.com"
api_key = "obj_your_key_here"
```

`config show` masks `api-key` and `session-token` values; commands other than `tokens create` do not print full secret values.

### Identity and personal access tokens

Auth commands use a session bearer token (from dashboard login or `POST /auth/login`), not the workspace API key:

```bash
export OBJECTIFIED_SESSION_TOKEN=obj_sess_your_token_here

objectified config set session-token obj_sess_your_token_here
objectified auth whoami
objectified auth status
objectified auth tenants
objectified tokens list
objectified tokens create my-cli-token --scope read --scope write --ttl-days 30
objectified tokens revoke <pat-uuid>
```

`tokens create` prints the full PAT secret once in human mode; list and revoke never expose it.

### Workspace API keys and integrations

API key lifecycle commands use the workspace API key (`X-API-Key`). Integration status uses a session bearer token like `auth` and `tokens`:

```bash
export OBJECTIFIED_API_KEY=obj_your_key_here
export OBJECTIFIED_SESSION_TOKEN=obj_sess_your_token_here

objectified api-keys list
objectified list-api-keys
objectified api-keys list --type mcp --output json
objectified api-keys create --type browser --label "CI reader" --scope read,write --yes
objectified api-keys create --type mcp --label "Agent" --transport streamable_http --tools spec.list --yes
objectified api-keys show <key-uuid>
objectified api-keys rotate <key-uuid>
objectified api-keys revoke <key-uuid>
objectified integrations list
objectified integrations show github
```

`api-keys create` and `api-keys rotate` print the one-time secret once in human mode (`--output json` includes `secret`); list and show only show masked key prefixes. Use `--yes` to skip the create or revoke confirmation prompt in CI. `integrations show` flags re-auth when status is `expired`.

### Repository Store credentials

`repos` commands require a workspace API key (`X-API-Key`) and tenant scope (`OBJECTIFIED_TENANT_ID` or `--tenant`). Registering via a linked Git account also requires a session bearer token (`OBJECTIFIED_SESSION_TOKEN` or `--session-token`) to resolve `GET /dashboard/linked-accounts` and `GET /dashboard/linked-accounts/{id}/repositories`.

```bash
export OBJECTIFIED_BASE_URL=http://localhost:8000
export OBJECTIFIED_API_KEY=obj_dev_key
export OBJECTIFIED_TENANT_ID=acme-corp
export OBJECTIFIED_SESSION_TOKEN=obj_sess_your_token_here
```

## Examples

Replace placeholders such as `<uuid>` with values from your tenant. Tier 2 commands (list, import, get) require an API key via flag, env, `.env`, or `config set`.

### Help

```bash
objectified help
objectified help projects list
objectified --help
```

In interactive mode (`./run.sh`), type `help` or `help <subcommand>` at the `objectified>` prompt.

### Verify connectivity

```bash
# Anonymous health check (no API key)
objectified --base-url http://localhost:8000 health

# Probe reachability before configuring credentials
objectified doctor
```

### Configure once, reuse everywhere

```bash
export OBJECTIFIED_BASE_URL=http://localhost:8000
export OBJECTIFIED_API_KEY=obj_dev_key

objectified config set base-url http://localhost:8000
objectified config set api-key obj_dev_key
objectified config show
```

Override saved defaults for one invocation:

```bash
objectified --base-url http://localhost:8000 --api-key obj_dev_key projects list
```

### Import auto-detect

Detect the document format from top-level headers (``openapi``, ``swagger``, ``arazzo``, ``$schema``) and run the matching importer:

```bash
objectified import auto ./spec.json
objectified import auto https://example.com/openapi.json
objectified import auto ./schema.json --dry-run

# Filename hint: a *.arazzo.{yaml,yml,json} document routes to the Arazzo
# importer even when its `arazzo:` version line is missing or it would
# otherwise sniff as generic YAML.
objectified import auto ./checkout.arazzo.yaml
```

Content markers always win; the ``*.arazzo.{yaml,yml,json}`` extension hint is a
last resort applied only when no header matches (mirrors the REST repository
scanner). Stdin (``-``) has no filename, so pipe Arazzo documents that omit the
``arazzo:`` line through ``import arazzo`` explicitly.

### Import OpenAPI

```bash
# Create project + version from info.title / info.version
objectified import openapi ./openapi.yaml

# Resolve the project name from another OpenAPI field
objectified import openapi ./openapi.yaml --project-name-field info.summary

# Or embed the field path in the document itself
# info:
#   x-objectified-project-name-field: info.summary

# Import from a public HTTP(S) URL
objectified import openapi https://example.com/openapi.json

# Plan without persisting
objectified import openapi ./openapi.yaml --dry-run

# Update an existing project
objectified import openapi ./openapi.yaml --project-id <uuid> --version 2.0.0

# Publish immediately after import (default leaves the version as draft)
objectified import openapi ./openapi.yaml --publish public
objectified import openapi ./openapi.yaml --publish private
```

### Import Arazzo

Import an [Arazzo 1.0](https://spec.openapis.org/arazzo/latest.html) workflow document (validated locally before upload):

```bash
objectified import arazzo ./checkout.arazzo.yaml
objectified import arazzo https://example.com/workflows/checkout.json
objectified import arazzo ./checkout.yaml --dry-run
objectified import arazzo ./checkout.yaml --project-id <uuid> --version-id <uuid>
objectified import arazzo ./checkout.yaml --no-wait
objectified import arazzo ./checkout.yaml --publish public
objectified --json import arazzo ./checkout.yaml
```

Use `import openapi` for OpenAPI API descriptions and `import json-schema` for standalone JSON Schema files.

### OpenAPI/Arazzo path workflow (import → inspect → export)

After importing a spec, inspect normalized paths and operations, then export a reconstructed document for CI or review. Replace placeholders with values from your tenant.

```bash
export OBJECTIFIED_BASE_URL=http://localhost:8000
export OBJECTIFIED_API_KEY=obj_dev_key
export OBJECTIFIED_TENANT_ID=acme-corp

# 1. Import (OpenAPI or Arazzo)
objectified import openapi ./payments-openapi.json
objectified import arazzo ./checkout.arazzo.yaml

# 2. Inspect stored paths and operations (project slug + version from import output)
objectified paths list --project payments-api --version 1.0.0
objectified paths show /payments --project payments-api --version 1.0.0
objectified operations show createPayment --project payments-api --version 1.0.0

# Score schema quality (server-computed, deterministic) and gate CI
objectified lint --project payments-api --version 1.0.0
objectified lint --project payments-api --version 1.0.0 --base-version 0.9.0
objectified lint --project payments-api --version 1.0.0 --min-grade B

# Arazzo workflows (after arazzo import)
objectified workflows list --project checkout-flow --version 1.0.0
objectified workflows show checkout --project checkout-flow --version 1.0.0

# 3. Export reconstructed spec or download the original upload bytes
objectified spec export \
  --project payments-api \
  --version 1.0.0 \
  --format openapi \
  --output ./artifacts/openapi.json

objectified spec download-original \
  --import-id <version-uuid> \
  --output ./artifacts/original.yaml
```

Machine-readable inspection (`--json` on stdout):

```bash
objectified --json paths list --project <uuid> --version <uuid>
objectified --json paths show <path-uuid> --project <uuid> --version <uuid>
objectified --json operations show createPayment --project payments-api --version 1.0.0
objectified --json workflows list --project <uuid> --version <uuid>
```

Post-MVP verification commands (`spec fidelity`, `spec diff`, `spec verify-attestation`) are documented when they land in the CLI.

### Inspect paths and operations

List flattened path/operation rows for a project version (filters: `--method`, `--tag`, `--q`):

```bash
objectified paths list --project payments-api --version 1.0.0
objectified paths list --project payments-api --version 1.0.0 --method POST --tag payments
objectified paths show /payments --project payments-api --version 1.0.0
objectified paths show <path-uuid> --project <uuid> --version <uuid>
objectified operations show createPayment --project payments-api --version 1.0.0
objectified --json operations show <operation-uuid> --project <uuid> --version <uuid>
```

### Inspect Arazzo workflows

```bash
objectified workflows list --project checkout-flow --version 1.0.0
objectified workflows show checkout --project checkout-flow --version 1.0.0
objectified workflows show <workflow-uuid> --project <uuid> --version <uuid>
objectified --json workflows list --project <uuid> --version <uuid>
```

### Import JSON Schema

Import a standalone [JSON Schema 2020-12](https://json-schema.org/draft/2020-12/json-schema-core.html) file as a tenant property or schema:

```bash
objectified import json-schema ./email.json
objectified import json-schema https://example.com/schemas/email.json
objectified import json-schema ./user.json --as schema --version-id <uuid>
objectified import json-schema ./field.json --project-id <uuid> --link-project-property
```

`--link-project-property` requires `--project-id`. Use `import openapi` for full OpenAPI specifications.

**`$ref` resolution (MVP):** Only the schema document in the given file is imported. External or relative `$ref` targets are not resolved or inlined; bundle multi-file schemas before import if you need a self-contained definition.

### Repository Store

Connect Git repositories, scan branches for spec files, sniff importability, and import into projects or versions. The CLI mirrors the Control Panel Repositories tab (`add` → `scan` → `files` → `inspect` → `import` → `imports`).

End-to-end workflow (replace placeholders with values from your tenant):

```bash
# 1. Register a repository (public URL or linked account)
objectified repos add --url https://github.com/acme/public-specs.git
objectified repos add --url https://github.com/acme/public-specs.git --branch release
objectified repos add --account "Acme GitHub" --repo acme/api-specs

# 2. Scan the default or selected branch (--wait polls until complete)
objectified repos scan <repository-uuid>
objectified repos scan <repository-uuid> --branch release --wait

# 3. List scanned files (filters match the Files tab)
objectified repos files <repository-uuid>
objectified repos files <repository-uuid> --glob "**/openapi*.yaml, **/arazzo/*.yaml"
objectified repos files <repository-uuid> --preset openapi --importable

# 4. Sniff a file before import
objectified repos inspect <repository-uuid> <file-uuid>
objectified repos inspect <repository-uuid> <file-uuid> --format json
objectified repos inspect <repository-uuid> <file-uuid> --closure
objectified repos inspect <repository-uuid> <file-uuid> --closure --format json
objectified repos inspect <repository-uuid> <file-uuid> --deep
objectified repos inspect <repository-uuid> <file-uuid> --deep --format json

# 4b. Verify integrity + signature trust (CI-friendly; exits 1 on failure)
objectified repos verify <repository-uuid>
objectified repos verify <repository-uuid> <file-uuid>
objectified repos verify <repository-uuid> --format json

# 5. Import into a new or existing project/version
objectified repos import <repository-uuid> <file-uuid> --new-project
objectified repos import <repository-uuid> --files "**/openapi*.yaml" --new-project
objectified repos import <repository-uuid> <file-uuid> --project <project-uuid> --version-name 2.0.0
objectified repos import <repository-uuid> <file-uuid> --project <project-uuid> --version-id <version-uuid>
objectified repos import <repository-uuid> <file-uuid> --new-project --dry-run

# 6. Review import provenance
objectified repos imports <repository-uuid>
objectified repos imports <repository-uuid> --project <project-uuid> --format json
objectified repos imports <repository-uuid> --since 2026-06-01T00:00:00Z --until 2026-06-30T23:59:59Z
```

#### `repos list`

List registered repositories for the tenant. Filters: `--provider` (`github`, `gitlab`, `bitbucket`, `public_url`), `--status` (`pending`, `scanning`, `ready`, `error`, `archived`), `--name` (substring). Use `--format json` or global `--json` for machine output.

```bash
objectified repos list
objectified repos list --tenant <uuid-or-slug>
objectified repos list --provider github --status ready
objectified repos list --name api-specs --all --format json
```

#### `repos add`

Register a repository via public HTTPS clone URL or a linked account. Public URLs are pre-flighted with `POST /tenants/{id}/repositories/test-public-url`. Linked-account mode requires `--account` (display name from `integrations list`) and `--repo` (`OWNER/NAME` slug).

```bash
objectified repos add --url https://github.com/acme/public-specs.git
objectified repos add --url https://github.com/acme/public-specs.git --branch release
objectified repos add --account "Acme GitHub" --repo acme/api-specs
objectified repos add --account "Acme GitHub" --repo acme/api-specs --branch develop --format json
```

#### `repos scan`

Enqueue a branch scan (`POST /tenants/{id}/repositories/{repository_id}/scans`). Omit `--branch` to use the repository default. `--wait` polls `GET …/scans/{scan_id}` until the scan finishes and prints file counts.

```bash
objectified repos scan <repository-uuid>
objectified repos scan <repository-uuid> --branch release
objectified repos scan <repository-uuid> --wait
objectified repos scan <repository-uuid> --branch main --wait --poll-interval 2
```

#### `repos files`

List files discovered by the latest scan (`GET …/files`). `--glob` accepts comma-separated patterns; `--regex` is mutually exclusive with `--glob`. `--preset` values: `all_importable`, `openapi`, `arazzo`, `asyncapi`, `json_schema`, `graphql`, `protobuf`, `avro`, `postman`, `sql_ddl`. Use `--importable` or `--not-importable` to filter by sniff verdict; omit both to include unsniffed rows. `--closure` adds a closure indicator column showing resolved and missing `$ref` targets per file.

```bash
objectified repos files <repository-uuid>
objectified repos files <repository-uuid> --glob "**/openapi*.yaml"
objectified repos files <repository-uuid> --regex 'openapi.*\.ya?ml$'
objectified repos files <repository-uuid> --preset openapi --importable
objectified repos files <repository-uuid> --detected-kind openapi-candidate --all
objectified repos files <repository-uuid> --closure
objectified repos files <repository-uuid> --closure --format json
```

#### `repos inspect`

Run content sniff on a cached file (`POST …/files/{file_id}/sniff`). Prints importable verdict, detected kind, version, and reasons. Sniff before import when the Files table shows a pending verdict. Use `--closure` to print the resolved `$ref` closure and flag unresolved targets. Use `--deep` to run the deep pre-import verdict (`POST …/files/{file_id}/verify`) and print validation, lint, fidelity, and secrets findings; exits with code `1` when blocking findings are reported.

```bash
objectified repos inspect <repository-uuid> <file-uuid>
objectified repos inspect <repository-uuid> <file-uuid> --format json
objectified repos inspect <repository-uuid> <file-uuid> --closure
objectified repos inspect <repository-uuid> <file-uuid> --closure --format json
objectified repos inspect <repository-uuid> <file-uuid> --deep
objectified repos inspect <repository-uuid> <file-uuid> --deep --format json
```

#### `repos verify`

Check repository file integrity and commit signature metadata (`GET …/files` or `GET …/files/{file_id}`). Prints per-file integrity and signature status. Exits with code `1` when any file has failed git blob verification or an invalid signature. Omit the file UUID to verify all files (fetches all pages by default).

```bash
objectified repos verify <repository-uuid>
objectified repos verify <repository-uuid> <file-uuid>
objectified repos verify <repository-uuid> --format json
objectified --json repos verify <repository-uuid>
```

#### `repos import`

Import a repository file into the catalog (`POST …/files/{file_id}/import`), many files in one batch run (`POST …/imports:batch`), or per a GitOps manifest (`POST …/imports:manifest`). Single-file mode requires a file UUID argument. Batch mode selects files with `--files` (comma-separated globs) or `--regex`, then applies either global target flags or a `--map` YAML/JSON file with per-path mappings. Manifest mode uses `--manifest` to import from the repository's scanned `.objectified.yaml`, or `--manifest-file PATH` to validate and import from a local manifest file (resolved against scanned repository files). Use exactly one target mode per file: `--new-project` (create project + version from document metadata), or `--project` with optional `--version-id` (existing version) or `--version-name` (new version under the project). `--resume-run-id` retries a prior batch or manifest run without re-selecting files. Reuses the same `ImportResult` output as `import openapi` / `import arazzo` for single imports; batch and manifest modes print an aggregate summary. `--dry-run` plans without persisting.

```bash
objectified repos import <repository-uuid> <file-uuid> --new-project
objectified repos import <repository-uuid> <file-uuid> --new-project --version-name 1.0.0
objectified repos import <repository-uuid> <file-uuid> --project <project-uuid> --version-name 2.0.0
objectified repos import <repository-uuid> <file-uuid> --project <project-uuid> --version-id <version-uuid>
objectified repos import <repository-uuid> <file-uuid> --new-project --dry-run
objectified repos import <repository-uuid> --files "**/openapi*.yaml" --new-project
objectified repos import <repository-uuid> --files "**/*.yaml" --map ./import-map.yaml
objectified repos import <repository-uuid> --regex 'openapi' --project <project-uuid> --version-id <version-uuid>
objectified repos import <repository-uuid> --resume-run-id <batch-run-uuid>
objectified repos import <repository-uuid> --manifest
objectified repos import <repository-uuid> --manifest-file ./.objectified.yaml
objectified repos import <repository-uuid> --manifest --dry-run
objectified --json repos import <repository-uuid> --files "**/*.yaml" --new-project
```

#### `repos imports`

List import provenance for a repository (`GET …/imports`). Filters: `--project`, `--version-id`, `--actor` (user UUID), `--since` / `--until` (ISO-8601). Table columns: file path, project, version, importer, `imported_at`, blob SHA.

```bash
objectified repos imports <repository-uuid>
objectified repos imports <repository-uuid> --project <project-uuid>
objectified repos imports <repository-uuid> --version-id <version-uuid> --format json
objectified repos imports <repository-uuid> --actor <user-uuid> --since 2026-06-01T00:00:00Z
```

### MCP catalog

Register, list, and inspect external MCP servers in your tenant's catalog. These commands
require an API key and a tenant scope (`--tenant` or `OBJECTIFIED_TENANT_ID`); the server
re-scopes from the token, so you only ever see your own catalog.

Register a server (`POST /v1/mcp/{tenant}/endpoints`). `--name` and `--url` are required;
`--transport` defaults to `streamable_http` (`sse` and `stdio` are also accepted):

```bash
objectified mcp register --name "Weather MCP" --url https://mcp.example.com/sse
objectified mcp register --name "Weather MCP" --url https://mcp.example.com/sse --transport sse
objectified mcp register --name "Weather MCP" --url https://mcp.example.com/sse \
  --description "Weather lookups" --category tools --visibility public
```

Attach an outbound credential while registering — `--bearer` seals a bearer token, `--header`
seals a custom header secret as `Name:Value` (the two are mutually exclusive). The secret is
sealed server-side via `PUT …/credentials` and is never echoed back:

```bash
objectified mcp register --name "Weather MCP" --url https://mcp.example.com/sse --bearer "$MCP_TOKEN"
objectified mcp register --name "Weather MCP" --url https://mcp.example.com/sse --header "X-Api-Token: $MCP_TOKEN"
```

List the catalog (`GET /v1/mcp/{tenant}/endpoints`) and show one endpoint by id
(`GET /v1/mcp/{tenant}/endpoints/{id}`). Both honour the global `--json` flag and a local
`--output json`:

```bash
objectified mcp list
objectified mcp list --output json
objectified mcp show <endpoint-uuid>
objectified --json mcp show <endpoint-uuid>
```

### Import JSON Schema types

Import system-wide JSON Schema type definitions (typically a `$defs` library) into the platform type table:

```bash
objectified import json-schema-type ./common-types.json
objectified import json-schema-type https://example.com/schemas/common-types.json
objectified import json-schema-type ./email.json --name contact_email --description "Primary email"
objectified import json-schema-type ./common-types.json --dry-run
objectified import json-schema-type ./common-types.json --publish public
objectified import json-schema-type ./common-types.json --publish private
```

Use `--publish public` to import into the system-wide type library (master tenant only). Use `--publish private` or omit the flag to import tenant-scoped types. `--visibility` is an alias for `--publish`.

Requires an API key (for `creator_id`) but not a tenant-scoped import target. If you run `import json-schema` on a type library file, the CLI suggests `import json-schema-type` instead.

### List resources

Human-readable tables (default):

```bash
objectified projects list
objectified projects list --limit 50 --all
objectified properties list
objectified schemas list
objectified versions list --project-id <uuid>
objectified types list
objectified types show email
objectified types search phone
```

Machine-readable JSON:

```bash
objectified --json projects list
objectified --json schemas get <uuid>
objectified --json types list
objectified --json types show email
```

Fetch a single record:

```bash
objectified projects get <uuid>
objectified properties get <uuid>
```

### Publish and unpublish types

Requires the master tenant API key (Tier 2). Publishing promotes a tenant-owned
type to the system-wide library (`system: true`). Unpublishing demotes a
system-wide type to tenant scope under the master tenant.

```bash
# Publish a tenant-owned type by slug
objectified types publish email

# Publish by UUID
objectified types publish <type-uuid>

# Unpublish a system-wide type
objectified types unpublish email

# Machine-readable result
objectified --json types publish email
```

### Publish and unpublish versions

Requires an API key (Tier 2). Publishing records `published_on` and makes the
version discoverable: `public` adds it to the public catalog, while `private`
publishes it as tenant-protected (visible only within your tenant).

Pass a version UUID directly, or use `--project` to publish by version slug or
label. The default visibility is `public`.

```bash
# Publish a version to the public catalog (by UUID)
objectified versions publish <version-uuid>

# Publish privately (tenant-protected), resolving by project + label
objectified versions publish 1.0.0 --project payments-api --visibility private

# Return a published version to draft (removes it from the catalog)
objectified versions unpublish 1.0.0 --project payments-api

# Machine-readable result
objectified --json versions publish <version-uuid>
```

### Export reconstructed specs (CI artifacts)

Requires tenant scope (`OBJECTIFIED_TENANT_ID` or `--tenant`). Sends `X-API-Key` when configured so protected published versions are visible. Document bytes go to `--output`; diagnostics and metadata go to stderr. With global `--json`, metadata is JSON on stdout when `--output` is a file, and on stderr when `--output -` so stdout stays byte-safe for pipelines.

```bash
export OBJECTIFIED_TENANT_ID=acme-corp

# Write OpenAPI JSON to a CI artifact path
objectified spec export \
  --project payments-api \
  --version 1.0.0 \
  --format openapi \
  --output ./artifacts/openapi.json

# Stream YAML to stdout (metadata on stderr)
objectified spec export \
  --project payments-api \
  --version 1.0.0 \
  --format arazzo \
  --yaml \
  --output -

# Machine-readable metadata (document still written to --output file)
objectified --json spec export \
  --project payments-api \
  --version 1.0.0 \
  --format openapi \
  --output ./artifacts/openapi.json
```

### Download original import artifact

`--import-id` is the project version UUID that owns the active import provenance row (`GET /versions/{id}/import-source`). Requires an API key.

```bash
objectified spec download-original \
  --import-id <version-uuid> \
  --output ./artifacts/original.yaml

objectified spec download-original \
  --import-id <version-uuid> \
  --output -
```

## Development

```bash
cd packages/objectified-cli
uv venv --allow-existing
uv sync
uv run pytest tests/ -v
uv run ruff check src/ tests/
```

```bash
yarn cli:lint
```

See [`AGENTS.md`](AGENTS.md) for contributor conventions, layout, and review checklist.

See the [CLI roadmap](../../docs/ROADMAP_OBJECTIFIED_CLI.md) for planned commands.
