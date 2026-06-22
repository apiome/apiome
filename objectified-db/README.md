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

registry provision [--registry-database <name>]
                                            Create the registry database if absent
registry migrate [--dry-run] [--registry-database <name>] [--scripts-dir <path>]
                                            Provision (if needed) + apply registry migrations
registry migrate status [--registry-database <name>] [--scripts-dir <path>]
                                            List applied / pending registry migrations
registry ping [--registry-database <name>]  Verify the registry database connection

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

# Stand up the separate type-registry database (objectified-types-db) and migrate it.
# Reuses the same connection flags/env; only the database name differs
# (override with --registry-database or OBJECTIFIED_TYPES_DB).
objectified-db registry migrate          # provisions the DB (if absent) then applies registry-scripts/
objectified-db registry migrate status
objectified-db registry ping

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

### Type registry database (`objectified-types-db`)

The JSON Schema type registry lives in a **separate database** so its namespaces, type
definitions, and `$ref` edges never share tables with the core ADE schema (`odb`). Registry
tables are created in the `otr` schema by migrations under
[`registry-scripts/`](./registry-scripts), tracked independently from the core
[`scripts/`](./scripts) (each database keeps its own `schema_evolution_manager.scripts`).

- `registry migrate` connects to the **same** Postgres server using the global connection
  flags/env, then provisions the registry database (issuing `CREATE DATABASE` from the
  `postgres` maintenance database if absent) and applies pending registry migrations.
- The registry database name resolves from `--registry-database` → `OBJECTIFIED_TYPES_DB`
  env → `objectified-types-db` (default). To place the registry on a *different* server, set
  `OBJECTIFIED_TYPES_DB_URL` to a full connection string.

The `otr` schema holds three core entity tables (#3447):

| Table | Role | Key constraints |
|-------|------|-----------------|
| `type_namespace` | Scoped, addressable collection of types (`std/*` system or `tenant/<slug>/*`) | `scope ∈ {system, tenant}`; system ⇒ `tenant_id` NULL, tenant ⇒ `tenant_id` set; namespace `path` unique per scope |
| `type_definition` | A JSON Schema 2020-12 type (`json_schema` JSONB, `$id`, draft, source, mutability) | **unique `(namespace_id, name)`**; FK → `type_namespace` (cascade) |
| `type_ref` | A relative `$ref` edge from one type to another, with resolution status | `status ∈ {resolved, unresolved, circular}`; FK → `type_definition` (cascade); unique `(source_type_id, relative_ref)` |

All tables use UUID PKs, soft deletes (`deleted_at`), and carry no cross-database foreign keys
(the core `odb` schema lives in a separate database). Resolution of `relative_ref` →
`resolved_target` is implemented in Epic 3; the `std/v0` core types are seeded in #3449.
