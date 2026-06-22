# objectified-db

Database migrations **and** the `objectified-db` admin CLI for the Objectified platform.

- **Migrations** — SQL scripts in [`scripts/`](./scripts) applied by the CLI
  `objectified-db migrate` (compatible with
  [schema-evolution-manager](https://github.com/mbryzek/schema-evolution-manager)
  tracking in `schema_evolution_manager.scripts`). See the [`Dockerfile`](./Dockerfile).
- **Admin CLI** — a direct-to-database tool for privileged operations (users, tenants,
  membership, API keys), documented below.

## Admin CLI

### Security model

The CLI talks **directly to PostgreSQL** and deliberately **bypasses the REST API**. This is
intentional: provisioning users, tenants, and API keys is privileged, break-glass work that
should not be exposed over an HTTP service. Consequences:

- It requires **database credentials** and network access to Postgres. There is no app-level
  authentication — whoever can run it with valid DB creds has full control over these tables.
- Secrets (passwords, API keys) are **generated/printed once** and stored only as bcrypt
  hashes, exactly matching what `objectified-ui` writes and `objectified-rest` validates:
  - API key = `sk_` + 32 random bytes hex; stored `key_prefix = key[:12] + "..."`,
    `key_hash = bcrypt(key, 10)`. The REST service looks up by prefix and verifies with
    `bcrypt.checkpw(rawKey, key_hash)`.
  - Passwords = `bcrypt(password, 10)`.
- Treat it like `psql`: run it from a trusted operator host, prefer `--password-stdin` /
  `--random-password` over passing secrets as visible CLI args, and keep an audit trail.

### Build / run

```bash
yarn workspace objectified-db build      # compile to dist/
yarn workspace objectified-db dev -- <args>   # run from TS without building (tsx)
node objectified-db/dist/cli.js <args>   # run the built CLI
# or, once linked on PATH: objectified-db <args>
```

### Connecting to the database

Resolution order (first match wins):

1. `--database-url <url>` flag
2. `OBJECTIFIED_DB_URL` env
3. `DATABASE_URL` env
4. Individual flags `--host/--port/--user/--password/--database`
5. `POSTGRES_HOST/PORT/USER/PASSWORD/DB` env (the same vars used by `docker-compose.yml`),
   defaulting to `localhost:5432/objectified` as user `postgres`.

```bash
export OBJECTIFIED_DB_URL="postgresql://postgres:pw@localhost:5432/objectified"
objectified-db ping
```

Global flags: `--json` (machine-readable output), `-y, --yes` (skip confirmation prompts;
required for destructive operations when there is no TTY).

### Commands

```
objectified-db ping                         Verify the database connection

migrate [--dry-run] [--scripts-dir <path>]  Apply pending SQL migrations
migrate status [--scripts-dir <path>]       List applied / pending migrations

users create   --name --email (--password | --password-stdin | --random-password)
                                            [--unverified] [--disabled]
users list     [--all]
users set-password <email|id> (--password | --password-stdin | --random-password)
users delete   <email|id> [--hard]

tenants create      --name [--slug] [--description] [--disabled]
tenants list        [--all]
tenants delete      <slug|id> [--hard]
tenants add-user    <slug|id> <email|id> [--admin]
tenants remove-user <slug|id> <email|id> [--admin-only]
tenants members     <slug|id>

api-keys create  --tenant <slug|id> --name <name> [--description]
                 [--expires-days N] [--created-by <email|id>]
api-keys list    --tenant <slug|id> [--all]
api-keys revoke  <id|prefix> [--hard]
```

Soft-delete is the default for `delete`/`revoke` (`deleted_at` set, row disabled); `--hard`
removes the row. References accept either a UUID id or the natural key (user email, tenant
slug, API-key prefix).

### Docker

The image runs the compiled CLI. By default it applies migrations:

```bash
docker run --rm \
  -e POSTGRES_HOST=db -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=secret \
  -e POSTGRES_DB=objectified \
  objectified-db:latest

# Other subcommands
docker run --rm -e POSTGRES_HOST=db ... objectified-db:latest migrate status
docker run --rm -e POSTGRES_HOST=db ... objectified-db:latest ping
```

### Examples

```bash
# Apply pending migrations
objectified-db migrate
objectified-db migrate status
objectified-db migrate --dry-run

# Create a user with a generated password (printed once)
objectified-db users create --name "Ada Lovelace" --email ada@example.com --random-password

# Create a tenant (slug derived from the name if omitted) and make Ada an admin
objectified-db tenants create --name "Acme Corp"
objectified-db tenants add-user acme-corp ada@example.com --admin

# Mint an API key for the tenant (the key is shown exactly once)
objectified-db api-keys create --tenant acme-corp --name ci-key --expires-days 90

# Pipe a password instead of putting it in shell history
printf '%s' "$NEW_PW" | objectified-db users set-password ada@example.com --password-stdin

# Revoke a key non-interactively
objectified-db --yes api-keys revoke sk_265e18808...
```

### Notes

- All core tables are addressed in the `odb` schema (`odb.users`, `odb.tenants`, `odb.api_keys`,
  …), matching `objectified-rest`.
- `api-keys create` writes `created_by_user_id` when the column exists and transparently falls
  back for older databases (same behavior as the REST service).

### Type registry (extends `odb.primitives`)

The JSON Schema type registry is **not** a separate database. It lives in this same
`objectified-db` database, in the `odb` schema, by **extending the existing `odb.primitives`
table in place**. Primitives are tenant-scoped (each row's `tenant_id`) **and** system-wide
(`is_system` / `is_public`), so a tenant's own types and the shared `std/*` types compose across
the tenant's projects with ordinary same-database foreign keys.

Migration `20260622-230000.sql` adds these registry columns to `odb.primitives` (no new tables,
no separate schema):

| Column | Role |
|--------|------|
| `namespace` | Namespace path, e.g. `std/v0/types` (system-wide) or `tenant/<slug>/types` (tenant-owned) |
| `base_uri` | Import-source base URL the relative `$ref` values resolve against (Epic 3) |
| `schema_id` | The JSON Schema `$id` (namespace base + name) |
| `draft` | JSON Schema dialect/draft, default `2020-12` |
| `source` | Provenance: `human` or `imported` (`primitives_source_ck` check) |
| `refs` | JSONB array of `$ref` edges: `[{relative_ref, resolved_target, status ∈ {resolved, unresolved, circular}}]` |

The same migration drops the obsolete `otr` schema if an earlier build created it (the separate
`objectified-types-db` design was reversed — see #3446). Tenant vs system scope reuses the
existing `tenant_id` / `is_system` columns; the `std/v0` core system primitives are seeded in
#3449; `$ref` resolution (`relative_ref` → `resolved_target`) is implemented in Epic 3.
