# Objectified: CLI - Feature Roadmap

> A first-party TypeScript command-line interface (`objectified-cli`, binary `objectified`) that wraps the Objectified REST service and provides a complete programmatic interface to the SaaS offering. The CLI mirrors the REST surface — tenants, projects, versions, primitives, properties, classes, paths/operations, browse/schema export, data records, migrations, and version tags — and is designed for both human use (rich tables, color, prompts) and automation (stable JSON, exit codes, NDJSON, SARIF).
>
> **Revenue Model**: The CLI itself is free and open-source under the same license as the rest of Objectified. Advanced features (telemetry dashboards, plugin marketplace, signed enterprise binaries) are gated at Pro/Enterprise; bulk-import quotas and CI parallelism caps follow tenant plan limits.
>
> **Tech Stack**: Node.js 20 LTS / TypeScript 5.x, [oclif](https://oclif.io) v4 (topic-command framework, lazy loading, plugin system), [openapi-typescript](https://openapi-ts.dev) for the generated REST client, `keytar` for OS keychain credentials, `cli-table3` + `chalk` + `ora` for output rendering, [changesets](https://github.com/changesets/changesets) for semver release flow, Node.js Single Executable Applications (SEA) for cross-platform binaries, and GitHub Actions for CI + NPM publishing.
>
> **Design References**:
> - [clig.dev](https://clig.dev) — Command Line Interface Guidelines
> - [Heroku CLI Style Guide](https://devcenter.heroku.com/articles/cli-style-guide)
> - [bettercli.org](https://bettercli.org)
> - [axi.md](https://axi.md/)

---

## MVP Definition

The MVP delivers an `npm i -g objectified-cli` install that lets a developer:
- Authenticate with `objectified auth login` (browser PKCE flow) or `OBJECTIFIED_API_KEY` for CI.
- Resolve their default tenant with `objectified tenants use <slug>` (per profile).
- List, inspect, and create projects + versions (`projects list/show/create`, `versions list/show/create/publish`).
- Browse the public directory of tenants/projects/versions without authentication (`browse tenants/projects/versions`).
- Download published specs in OpenAPI / Swagger format with one command (`schema fetch`, `schema swagger`).
- Override the connection target with `--base-url`, switch profiles with `--profile`, and emit machine-readable output with `--json`.
- Get help everywhere — `objectified --help`, `objectified <topic> --help`, `objectified docs <topic>` — with at least two examples per command.
- Receive helpful error messages with documented exit codes (3 unauth, 4 forbidden, 5 not-found, 6 conflict, 7 validation, 8 server, 9 network, 10 rate-limited, 11 config).
- Publish to a configurable NPM artifactory (npmjs.com by default) on every tagged release via `objectified-cli-publish.yml`.

Everything else (data plane, full paths/classes/properties CRUD, primitives import, plugins, self-update, telemetry, Homebrew/Scoop) lands in v2.

---

## Global Design Principles

The CLI follows seven non-negotiable rules drawn from the references above:

1. **Topic-command structure** — `objectified TOPIC COMMAND [args] [flags]`. Every multi-step verb hangs off a topic (`objectified projects list`, not `objectified list-projects`).
2. **`--base-url` is canonical** — every command honors `--base-url`, the `OBJECTIFIED_BASE_URL` env var, and `[profile.*] base_url` in `config.toml`, in that order.
3. **Human-first by default, machine-friendly on demand** — TTY → tables + color; `--json` or non-TTY → stable, sorted, parseable JSON. `NO_COLOR` is honored.
4. **Errors are short, actionable, and on `stderr`** — every error includes a hint, an exit code, and (where available) a `Request-Id`.
5. **Idempotency where the verb allows** — `GET`/`PUT`/`DELETE` retry safely on 429/5xx; `POST` retries only on 429.
6. **Progressive disclosure** — `--help` shows essentials, `objectified docs <topic>` shows prose docs, man pages ship for full reference.
7. **Composable** — every command writes a single concern to `stdout`; `--ndjson` for streamable output; piping works (`objectified … --json | jq …`).

---

## Connection Model

```
                        objectified CLI (TypeScript)
                                  │
                                  │ HTTPS  (X-API-Key  |  Bearer <jwt>)
                                  ▼
                        ┌──────────────────────────┐
                        │   --base-url resolves    │
                        │   from flag → env →      │
                        │   profile.toml → default │
                        └────────────┬─────────────┘
                                     │
                ┌────────────────────┼────────────────────┐
                ▼                    ▼                    ▼
         objectified-rest      objectified-rest     objectified-rest
         (production)          (staging)            (local docker)
         api.objectified.dev   api.staging.…        localhost:3001
                │
                ▼
            PostgreSQL
            (tenants/projects/versions/classes/…)
```

Every command lives in one of three connection modes:

| Mode               | Command examples                                  | Auth                          |
|--------------------|---------------------------------------------------|-------------------------------|
| Authenticated      | `projects create`, `versions publish`, `data import` | OAuth (keychain) or API-key  |
| Tenant-scoped read | `projects list`, `classes show`, `paths full`      | OAuth or API-key              |
| Public discovery   | `browse tenants`, `schema fetch`, `schema diff`    | None (works without login)   |

---

## Epic Index

| #   | Epic                                                                                                       | Issue   | Sub-tickets | MVP-relevant |
|-----|------------------------------------------------------------------------------------------------------------|---------|-------------|--------------|
| 1   | [CLI Foundation & DevEx](https://github.com/KenSuenobu/objectified-commercial/issues/3174)                 | #3174   | 8           | All 8        |
| 2   | [Authentication & Tenant Context](https://github.com/KenSuenobu/objectified-commercial/issues/3175)        | #3175   | 8           | 6 of 8       |
| 3   | [Projects (CLI)](https://github.com/KenSuenobu/objectified-commercial/issues/3176)                         | #3176   | 6           | 3 of 6       |
| 4   | [Versions (CLI)](https://github.com/KenSuenobu/objectified-commercial/issues/3177)                         | #3177   | 9           | 4 of 9       |
| 5   | [Primitives (CLI)](https://github.com/KenSuenobu/objectified-commercial/issues/3178)                       | #3178   | 6           | 0 (v2)       |
| 6   | [Properties (CLI)](https://github.com/KenSuenobu/objectified-commercial/issues/3179)                       | #3179   | 6           | 0 (v2)       |
| 7   | [Classes (CLI)](https://github.com/KenSuenobu/objectified-commercial/issues/3180)                          | #3180   | 8           | 0 (v2)       |
| 8   | [Paths & Operations (CLI)](https://github.com/KenSuenobu/objectified-commercial/issues/3181)               | #3181   | 7           | 0 (v2)       |
| 9   | [Browse & Schema Export (CLI)](https://github.com/KenSuenobu/objectified-commercial/issues/3182)           | #3182   | 9           | 5 of 9       |
| 10  | [Data Records (CLI)](https://github.com/KenSuenobu/objectified-commercial/issues/3183)                     | #3183   | 7           | 0 (v2)       |
| 11  | [Migration Plans & Version Tags (CLI)](https://github.com/KenSuenobu/objectified-commercial/issues/3184)   | #3184   | 7           | 0 (v2)       |
| 12  | [Distribution, Release & Self-Update](https://github.com/KenSuenobu/objectified-commercial/issues/3185)    | #3185   | 8           | 2 of 8       |

Total: **12 epics**, **87 sub-tickets** (open roadmap items; completed work is dropped from the Epic 1 summary table below).

---

## Epic 1 (#3174): CLI Foundation & DevEx

### Summary Table

No open tickets in this epic’s summary pack (foundation items #3186–#3193 are complete).

### Detailed Issue Descriptions

#### 1.1 (#3186) — Scaffold `objectified-cli` (**done**)

Landed as `objectified-cli/` at the repo root (oclif v4, `objectified` binary, `hello` smoke command, Vitest + ESLint + Prettier, Turbo `build`). Remaining foundation tickets below build on this package.

---

#### 1.2 (#3187) — Global flags (**done**)

Landed: `BaseCommand` declares the canonical global flags (`--api-key`, `--base-url`, `--config`, `--json`, `--no-color`, `--profile`, `--quiet`/`-q`, `--verbose`), resolves `baseUrl` / `apiKey` with flag → env → `[profile]` → `[default]` → built-in default, documents resolution order on `objectified --help`, normalizes argv so globals may appear before the subcommand, adds stub `projects list`, and ships unit + integration coverage.

`BaseCommand` exposes the canonical flag set so every concrete command inherits them with consistent semantics.

| Flag           | Env                       | Default                                  |
|----------------|---------------------------|------------------------------------------|
| `--api-key`    | `OBJECTIFIED_API_KEY`     | (none)                                   |
| `--base-url`   | `OBJECTIFIED_BASE_URL`    | `https://api.objectified.dev`            |
| `--config`     | `OBJECTIFIED_CONFIG`      | `~/.config/objectified/config.toml`      |
| `--json`       | `OBJECTIFIED_JSON=1`      | off (auto-on if not TTY)                 |
| `--no-color`   | `NO_COLOR=1`              | off (auto-on if not TTY)                 |
| `--profile`    | `OBJECTIFIED_PROFILE`     | `default`                                |
| `--quiet`/`-q` | —                         | off                                      |
| `--verbose`    | `OBJECTIFIED_VERBOSE=1`   | off                                      |

```
Resolution order (highest precedence wins):
  1. Command-line flag           (--base-url=https://…)
  2. Environment variable        (OBJECTIFIED_BASE_URL=…)
  3. Config file profile section ([profile.prod] base_url=…)
  4. Config file [default]
  5. Built-in default            (https://api.objectified.dev)
```

**Acceptance Criteria:** typed `this.flags`, resolution-order matrix unit-tested; `--json` always emits JSON; `--no-color`/non-TTY auto-disables ANSI; errors → stderr.

**Parallelism / Dependencies:** Depends on 1.1. Parallel with 1.3, 1.4, 1.7.

Part of Epic: CLI Foundation & DevEx (#3174)

---

#### 1.3 (#3188) — Configuration system (**done**)

Landed: XDG-style config dir on Linux/macOS (`env-paths` on Linux; `~/.config/objectified` when `XDG_CONFIG_HOME` unset on macOS), `%APPDATA%\\Objectified\\config.toml` on Windows; `default_profile` + `[profile.*]` / `[default]` parsing; auto-created `config.toml` at `0600` on Unix; `objectified config path|get|set|list`; profile validation with friendly errors; API keys never read from file (flag/env only); `OBJECTIFIED_TENANT` + `tenant_slug` in context; Vitest coverage for resolution order and paths.

**Parallelism / Dependencies:** Depended on 1.1, 1.2. Blocks Epic 2.

Part of Epic: CLI Foundation & DevEx (#3174)

---

#### 1.4 (#3189) — Output renderers (**done**)

Landed: `src/lib/output.ts` exposes `createCliOutput()` with `table` (TTY → styled table / pipe → TSV / `--json` → stable sorted JSON array), `json` (pretty on TTY, compact when piped or `--quiet`), `yaml`, `text`, `kv`, `spinner` (ora on stderr; silent when non-TTY, `--json`, or `--quiet`), `success`, `warn`, `error` (stderr), plus `banner` / `hint`. `BaseCommand` exposes `this.output` wired to globals (`supports-color`, `LANG`/`LC_ALL` for ASCII borders when `LANG=C` or `--no-color`). Snapshot tests cover TTY vs pipe vs `--json`. Legacy helpers `logInfo` / `writeJsonLine` remain for narrow call sites.

```
            stdout TTY    stdout pipe   --json    --quiet
table       ANSI table    TSV          n/a       suppressed
json        pretty + 2sp  compact      forced    forced
spinner     animated      none         none      none
banner      shown         hidden       hidden    hidden
errors      stderr+color  stderr       stderr    stderr (kept)
```

**Parallelism / Dependencies:** Depended on 1.1, 1.2. Parallel with 1.3, 1.5, 1.6, 1.7.

Part of Epic: CLI Foundation & DevEx (#3174)

---

#### 1.5 (#3190) — Generated REST client from `openapi.yaml` (**done**)

Landed: `yarn codegen` in `objectified-cli/` runs `@hey-api/openapi-ts` (`@hey-api/client-fetch`) on `objectified-rest/openapi.yaml`, fixes relative imports for `moduleResolution: NodeNext`, and writes stable barrels `src/generated/client.ts`, `models.ts`, and `operations.ts`. `src/lib/client.ts` wraps the SDK with mutable API-key/bearer injection, exponential backoff on 5xx, honoring `Retry-After` on 429, a one-shot optional `onUnauthorized` hook after 401, and verbose `x-request-id` capture. ESLint allows imports from `src/generated/` only from `lib/client.ts`. `yarn test` runs `codegen:check` (regenerate + `git diff src/generated`) so stale generated output fails with instructions. `projects list` uses the generated operation and requires `OBJECTIFIED_TENANT` or profile `tenant_slug`; Vitest covers the wiring with a stubbed global `fetch` (real subprocess integration avoids binding an HTTP listener where sandboxes block listen).

**Parallelism / Dependencies:** Depended on 1.1, 1.2, 1.3. Blocks all functional commands.

Part of Epic: CLI Foundation & DevEx (#3174)

---

#### 1.6 (#3191) — Error handling, exit codes, retries (**done**)

Landed: `ObjectifiedCliError` + `httpStatusToCliError` (all 4xx/5xx), `formatAndReportCliFailure` / `handleError` template (Reason, Hint, Request-Id, Exit code), top-level `run`+`handle` replacement in `bin/run.js` / `dev.js` (stacks only with `--verbose` or `OBJECTIFIED_DEBUG=1`), `leven` did-you-mean for unknown commands, network errno hints, client retries (idempotent: 429+5xx with 250/500/1s/2s, max 4 attempts; `POST`/`PATCH`: 429 only), `objectified docs errors`, Vitest HTTP mapping + `handleError` snapshots, integration coverage.

Documented BSD/sysexits-inspired exit codes:

```
0   success                  6   conflict        9   network/timeout
1   generic                  7   validation     10   rate limited
2   misuse                   8   server error   11   config error
3   not authenticated
4   forbidden
5   not found
```

Every error printed to stderr includes hint + request-id when available:

```
✖ Failed to publish version 'v2.1.0'.
  Reason: Schema 'Order.amount' is not backwards-compatible.
  Hint:   Run `objectified versions compatibility payments-api --base v2.0.0 --head v2.1.0`
  Request-Id: 7f2c…a041
  Exit code:  6
```

**Acceptance Criteria:** all failures route through `handleError`; stack traces only under `--verbose`; did-you-mean uses Levenshtein < 3.

**Parallelism / Dependencies:** Depends on 1.1, 1.2, 1.5.

Part of Epic: CLI Foundation & DevEx (#3174)

---

#### 1.7 (#3192) — Help system, examples, man pages, `objectified docs` (**done**)

Landed: custom `CommandHelp` (grouped **COMMON** / **OUTPUT** / **AUTH** / **OTHER**, **EXAMPLES** before flag groups, **SEE ALSO** from `static seeAlso`), ≥2 `examples` per command enforced in tests, `objectified docs` topic index plus prose topics (`errors`, `output`, `profiles`, `completions`, `plugins`, `telemetry`), `oclif readme` + `scripts/generate-man.mjs` writing `man/man1/*.1` and `package.json` `man`, CI workflow guards `git diff` after `yarn workspace objectified-cli test`, help honors **NO_COLOR**, non-TTY stdout, and `--no-color` via `stripAnsi`.

**Parallelism / Dependencies:** Depended on 1.1, 1.2.

Part of Epic: CLI Foundation & DevEx (#3174)

---

#### 1.8 (#3193) — Shell completions for bash, zsh, fish, PowerShell (**done**)

Landed: `objectified completion install|show|uninstall`, hidden `completion candidates` driver, bash/zsh/fish/PowerShell wrappers that complete manifest-backed commands/flags offline and merge REST-backed suggestions (projects, versions, classes, primitives; tenant slugs from config for `tenants use`) with a five-minute cache under `~/.cache/objectified/completion/`, degrading to no dynamic hits when offline; managed `# >>> objectified completion >>>` blocks for uninstall; `objectified docs completions` + README coverage.

```
$ objectified projects show pay<TAB>
payments-api      payouts-api      payroll-api
```

**Parallelism / Dependencies:** Depended on 1.1, 1.2.

Part of Epic: CLI Foundation & DevEx (#3174)

---

## Epic 2 (#3175): Authentication & Tenant Context

### Summary Table

| #         | Title                                                  | Description                                                       | Labels                                                  | MVP | Parallel |
|-----------|--------------------------------------------------------|-------------------------------------------------------------------|---------------------------------------------------------|-----|----------|
| 2.1 (#3194) | `auth login` (PKCE browser) + `auth logout`         | Loopback PKCE flow, token to keychain                             | `enhancement`, `mvp`, `cli`, `roadmap-cli`, `auth`     | Yes | Yes (with 2.2) |
| 2.2 (#3195) | API-key auth (`--api-key`, env, file)                | Headless / CI-friendly auth                                       | `enhancement`, `mvp`, `cli`, `roadmap-cli`, `auth`, `api-keys` | Yes | Yes (with 2.1) |
| 2.3 (#3196) | `auth status` (whoami)                               | Show profile, base-url, tenant, user, expiry, plan                | `enhancement`, `mvp`, `cli`, `roadmap-cli`, `auth`     | Yes | Yes      |
| 2.4 (#3197) | Secure credential storage (keytar + encrypted fallback) | OS keychain primary, AES-GCM file fallback for headless           | `enhancement`, `mvp`, `cli`, `roadmap-cli`, `auth`, `security` | Yes | No       |
| 2.5 (#3198) | `tenants list` / `tenants info`                      | Enumerate user's tenants and inspect one                          | `enhancement`, `mvp`, `cli`, `roadmap-cli`, `tenancy`  | Yes | Yes      |
| 2.6 (#3199) | `tenants use <slug>`                                 | Set default tenant per profile                                    | `enhancement`, `mvp`, `cli`, `roadmap-cli`, `tenancy`  | Yes | No       |
| 2.7 (#3200) | Multi-profile management                             | `auth profiles list/add/remove/set-default`                       | `enhancement`, `cli`, `roadmap-cli`, `auth`            | No  | Yes      |
| 2.8 (#3201) | Token refresh + 401 auto-retry                       | Pre-emptive refresh + transparent retry                           | `enhancement`, `cli`, `roadmap-cli`, `auth`            | No  | Yes      |

### Detailed Issue Descriptions

#### 2.1 (#3194) — `objectified auth login` (PKCE browser flow) + `auth logout`

Standard PKCE-on-loopback pattern (same as `gh auth login` and `heroku login`):

```
1. CLI starts a localhost listener on a random free port.
2. Opens https://app.objectified.dev/cli/login?code_challenge=…&redirect_uri=http://127.0.0.1:<port>
3. User completes login in the browser.
4. Browser redirects to http://127.0.0.1:<port>/?code=…
5. CLI exchanges code+verifier at /v1/auth/cli/token → access + refresh tokens.
6. Tokens stored in OS keychain (2.4).
7. CLI prints `✔ Logged in as kenji@objectified.dev`.
```

Headless fallback: `--no-browser` prints URL + manual code entry. `--profile staging` only logs that profile in. `auth logout` revokes server-side and clears keychain.

**Acceptance Criteria:** completes in < 30 s typical; loopback bound to `127.0.0.1` only; code verifier ≥ 43 chars (S256); E2E test against mock authz server.

**Parallelism / Dependencies:** Depends on 1.x, 1.5. Parallel with 2.2.

Part of Epic: Authentication & Tenant Context (#3175)

---

#### 2.2 (#3195) — API-key auth

Three input methods: `--api-key <key>`, `OBJECTIFIED_API_KEY` env, `--api-key-file <path>`. Optional `auth login --api-key` persists into keychain. API key wins over OAuth token when both present (matches AWS / GitHub CLI).

**Acceptance Criteria:** key never echoed in logs (redacted as `sk_***`); never persisted unless explicit `auth login --api-key`; `auth status` indicates auth type.

**Parallelism / Dependencies:** Depends on 1.x, 1.5. Parallel with 2.1.

Part of Epic: Authentication & Tenant Context (#3175)

---

#### 2.3 (#3196) — `objectified auth status`

```
$ objectified auth status
  Profile:    default
  Base URL:   https://api.objectified.dev
  Tenant:     acme-corp (Acme Corporation)
  User:       kenji@objectified.dev
  Auth type:  OAuth (PKCE)
  Expires:    in 6h 12m
  Plan:       Enterprise
```

`--json` for scripts (stable schema). Exit 0 if authenticated, 3 otherwise.

**Acceptance Criteria:** works for OAuth + API key + env-only; one round trip; ISO 8601 UTC in JSON, local TZ in human view.

**Parallelism / Dependencies:** Depends on 2.1 or 2.2, 2.4.

Part of Epic: Authentication & Tenant Context (#3175)

---

#### 2.4 (#3197) — Secure credential storage

`keytar` (Keychain / libsecret / Credential Vault). Encrypted file fallback at `~/.config/objectified/credentials.enc` (AES-256-GCM) for headless Linux containers.

```
┌────────────────────────────────────────────────────────┐
│  Credential Resolution                                 │
├────────────────────────────────────────────────────────┤
│  1. --api-key flag             (highest)               │
│  2. OBJECTIFIED_API_KEY env                            │
│  3. OS keychain (per profile)                          │
│  4. encrypted file fallback                            │
│  5. (none → exit 3, hint to login)                     │
└────────────────────────────────────────────────────────┘
```

**Acceptance Criteria:** keytar works across mac/linux/win in CI matrix; fallback file `0600`; no plaintext on disk; threat model documented.

**Parallelism / Dependencies:** Depends on 1.1, 1.3.

Part of Epic: Authentication & Tenant Context (#3175)

---

#### 2.5 (#3198) — `tenants list` / `tenants info`

```
$ objectified tenants list
  SLUG          NAME                  ROLE      ACTIVE
  acme-corp     Acme Corporation      owner     ★
  acme-staging  Acme (staging)        admin
  contoso-ltd   Contoso Ltd.          member
```

`--json` returns the array. Active default highlighted with star.

**Parallelism / Dependencies:** Depends on 2.1 or 2.2, 2.4.

Part of Epic: Authentication & Tenant Context (#3175)

---

#### 2.6 (#3199) — `tenants use <slug>`

Sets `[profile.<name>] tenant_slug = …` in config. Subsequent commands resolve tenant slug as: `--tenant <slug>` > `OBJECTIFIED_TENANT` > config > error (exit 11, hint to run `tenants use`).

```
       command line
            │
            │   --tenant=… ?  ───── yes ────┐
            │                                 │
            │   OBJECTIFIED_TENANT?  ── yes ─┤
            │                                 │
            │   profile.tenant_slug? ── yes ─┤
            │                                 │
            │   none ──→ exit 11             ▼
                                       resolved tenant
```

**Acceptance Criteria:** validates access via `HEAD /v1/tenants/{slug}` before writing config; did-you-mean for typos.

**Parallelism / Dependencies:** Depends on 2.5. Blocks every tenant-scoped command.

Part of Epic: Authentication & Tenant Context (#3175)

---

#### 2.7 (#3200) — Multi-profile management

`auth profiles list/add/remove/set-default` for managing multiple environments (`dev`, `staging`, `prod`). `add` validates base URL reachability; `remove` revokes credentials before deleting.

**Parallelism / Dependencies:** Depends on 1.3, 2.1 or 2.2, 2.4.

Part of Epic: Authentication & Tenant Context (#3175)

---

#### 2.8 (#3201) — Token refresh + 401 auto-retry

Client interceptor: on 401, refresh token at `/v1/auth/cli/refresh`, retry the original request once. Pre-emptive refresh when `expires_at` is within 60 s. Concurrent requests share a single in-flight refresh promise (no thundering herd).

**Acceptance Criteria:** transparent refresh, no extra log under default verbosity; two consecutive 401s abort with exit 3; API-key path skips refresh.

**Parallelism / Dependencies:** Depends on 1.5, 1.6, 2.1, 2.4.

Part of Epic: Authentication & Tenant Context (#3175)

---

## Epic 3 (#3176): Projects (CLI)

### Summary Table

| #         | Title                                | Description                                          | Labels                                | MVP | Parallel |
|-----------|--------------------------------------|------------------------------------------------------|---------------------------------------|-----|----------|
| 3.1 (#3202) | `projects list`                    | Paginated table; sort/filter/search; `--json`         | `enhancement`, `mvp`, `cli`, `roadmap-cli` | Yes | Yes      |
| 3.2 (#3203) | `projects show <slug-or-id>`       | Slug resolution; rich detail + recent activity        | `enhancement`, `mvp`, `cli`, `roadmap-cli` | Yes | Yes      |
| 3.3 (#3204) | `projects create`                  | Interactive + non-interactive + `--from-file`         | `enhancement`, `mvp`, `cli`, `roadmap-cli` | Yes | Yes      |
| 3.4 (#3205) | `projects update`                  | Partial update with diff renderer + concurrency check | `enhancement`, `cli`, `roadmap-cli`   | No  | Yes      |
| 3.5 (#3206) | `projects delete`                  | Typed confirmation, refuses on published versions     | `enhancement`, `cli`, `roadmap-cli`   | No  | Yes      |
| 3.6 (#3207) | `projects export`                  | Deterministic full project dump (JSON or YAML)        | `enhancement`, `cli`, `roadmap-cli`, `export` | No  | Yes      |

See each ticket on GitHub for the full description, acceptance criteria, ASCII diagrams (where applicable), parallelism analysis, and tech-stack notes.

---

## Epic 4 (#3177): Versions (CLI)

### Summary Table

| #         | Title                              | Description                                                        | Labels                                          | MVP | Parallel |
|-----------|------------------------------------|--------------------------------------------------------------------|-------------------------------------------------|-----|----------|
| 4.1 (#3208) | `versions list`                  | List versions with state, tags, publish date, author               | `enhancement`, `mvp`, `cli`, `roadmap-cli`, `versions` | Yes | Yes      |
| 4.2 (#3209) | `versions show`                  | Single-version detail; resolves semver/UUID/tag-name               | `enhancement`, `mvp`, `cli`, `roadmap-cli`, `versions` | Yes | Yes      |
| 4.3 (#3210) | `versions create`                | Create draft; supports `--base` (copy from existing)               | `enhancement`, `mvp`, `cli`, `roadmap-cli`, `versions` | Yes | Yes      |
| 4.4 (#3211) | `versions fork`                  | Fork existing version into a new semver                            | `enhancement`, `cli`, `roadmap-cli`, `versions`, `git-behavior` | No  | Yes |
| 4.5 (#3212) | `versions publish`               | Pre-publish checks → freeze → tag move → publish                   | `enhancement`, `mvp`, `cli`, `roadmap-cli`, `versions` | Yes | Yes      |
| 4.6 (#3213) | `versions unpublish`             | Retract published version with audit reason                        | `enhancement`, `cli`, `roadmap-cli`, `versions` | No  | Yes      |
| 4.7 (#3214) | `versions freeze`                | Immutable schema snapshot; `--unfreeze` allowed pre-download       | `enhancement`, `cli`, `roadmap-cli`, `versions` | No  | Yes      |
| 4.8 (#3215) | `versions compatibility`         | Backward-compat check; SARIF + CI exit codes                       | `enhancement`, `cli`, `roadmap-cli`, `versions`, `validation` | No  | Yes |
| 4.9 (#3216) | `versions delete`                | Delete draft/archived; refuses published without `--force`         | `enhancement`, `cli`, `roadmap-cli`, `versions` | No  | Yes      |

### Notable Detail — 4.5 (#3212) `versions publish`

```
$ objectified versions publish payments-api v2.1.0

  Pre-publish checks:
    ✔ schema valid (OpenAPI 3.1)
    ✔ no unfilled required descriptions (24 classes)
    ✔ backwards-compatible vs v2.0.0 (no breaking changes)
    ✔ change report generated

  Publishing v2.1.0 …
    ✔ frozen schema snapshot stored (sha256: 7f2c…a041)
    ✔ tag 'latest' moved from v2.0.0 → v2.1.0
    ✔ change-report URL: https://app.objectified.dev/acme/payments-api/changes/v2.0.0...v2.1.0

  ✔ Published v2.1.0 in 1.4s.
```

`--allow-breaking` required if compatibility (4.8) finds breaks. `--update-tag stable` moves a tag pointer in the same step. `--skip-checks` for emergencies; requires `--yes` and prints a banner.

### Notable Detail — 4.8 (#3215) `versions compatibility`

```
Result: 1 breaking change found (removal of /v1/charges/legacy).
Exit code: 6
```

Exit 0 if clean, 6 if unsuppressed breaking change found, 8 on server error fetching either side. `--sarif` for GitHub code-scanning, `--json` for piping into custom CI gates.

---

## Epic 5 (#3178): Primitives (CLI)

### Summary Table

| #         | Title                            | Description                                              | Labels                            | MVP | Parallel |
|-----------|----------------------------------|----------------------------------------------------------|-----------------------------------|-----|----------|
| 5.1 (#3217) | `primitives list`              | Filter by base type, system vs custom                     | `enhancement`, `cli`, `roadmap-cli` | No  | Yes      |
| 5.2 (#3218) | `primitives show`              | Constraints + usage count                                 | `enhancement`, `cli`, `roadmap-cli` | No  | Yes      |
| 5.3 (#3219) | `primitives create`            | Interactive (with regex/example local validation) + flags | `enhancement`, `cli`, `roadmap-cli` | No  | Yes      |
| 5.4 (#3220) | `primitives update`            | Partial update; system primitives are read-only           | `enhancement`, `cli`, `roadmap-cli` | No  | Yes      |
| 5.5 (#3221) | `primitives delete`            | Usage check + typed confirmation                          | `enhancement`, `cli`, `roadmap-cli` | No  | Yes      |
| 5.6 (#3222) | `primitives import`            | Bulk JSON/YAML import with dry-run + per-row report       | `enhancement`, `cli`, `roadmap-cli`, `import` | No  | Yes      |

### Notable Detail — 5.6 (#3222) bulk import flow

```
┌──────────────────────────────────────────────┐
│ ./acme-primitives.yaml                       │
│ ┌──────────────────────────────────────────┐ │
│ │ - name: acme-loyalty-id                  │ │
│ │   base: string                           │ │
│ │   pattern: ^LM-[0-9]{8}$                 │ │
│ │   examples: [LM-00000001, LM-12345678]   │ │
│ │ - name: acme-region-code                 │ │
│ │   base: string                           │ │
│ │   pattern: ^(EU|US|APAC)$                │ │
│ └──────────────────────────────────────────┘ │
└──────────────────────────────────────────────┘
                   │
                   ▼
       POST /v1/primitives/{tenant_slug}/import
                   │
                   ▼
              ┌────────┐
              │ Report │  → stdout (table) or --report file (JSON)
              └────────┘
```

Round-trip symmetry: `primitives list --json | objectified primitives import --update --yes` works.

---

## Epic 6 (#3179): Properties (CLI)

### Summary Table

| #         | Title                          | Description                                          | Labels                            | MVP | Parallel |
|-----------|--------------------------------|------------------------------------------------------|-----------------------------------|-----|----------|
| 6.1 (#3223) | `properties list`            | Filter by primitive/tag, search by name              | `enhancement`, `cli`, `roadmap-cli` | No  | Yes      |
| 6.2 (#3224) | `properties show`            | Constraints + per-class usage                        | `enhancement`, `cli`, `roadmap-cli` | No  | Yes      |
| 6.3 (#3225) | `properties create`          | Interactive (primitive autocomplete) or `--from-file` | `enhancement`, `cli`, `roadmap-cli` | No  | Yes      |
| 6.4 (#3226) | `properties update`          | Partial; primitive change requires `--allow-breaking` | `enhancement`, `cli`, `roadmap-cli` | No  | Yes      |
| 6.5 (#3227) | `properties delete`          | Refuses delete when in-use without `--force`          | `enhancement`, `cli`, `roadmap-cli` | No  | Yes      |
| 6.6 (#3228) | `properties copy`            | Cross-project copy with rename/include-tags           | `enhancement`, `cli`, `roadmap-cli` | No  | Yes      |

---

## Epic 7 (#3180): Classes (CLI)

### Summary Table

| #         | Title                                       | Description                                              | Labels                            | MVP | Parallel |
|-----------|---------------------------------------------|----------------------------------------------------------|-----------------------------------|-----|----------|
| 7.1 (#3229) | `classes list`                            | Lean or `--with-properties` (one round trip)             | `enhancement`, `cli`, `roadmap-cli` | No  | Yes      |
| 7.2 (#3230) | `classes show`                            | Hydrated detail (properties + tags) by default           | `enhancement`, `cli`, `roadmap-cli` | No  | Yes      |
| 7.3 (#3231) | `classes create`                          | Interactive multi-select properties; `--from-file`       | `enhancement`, `cli`, `roadmap-cli` | No  | Yes      |
| 7.4 (#3232) | `classes update`                          | Partial; rename only on draft                            | `enhancement`, `cli`, `roadmap-cli` | No  | Yes      |
| 7.5 (#3233) | `classes delete`                          | Typed confirmation; path-ref impact list                 | `enhancement`, `cli`, `roadmap-cli` | No  | Yes      |
| 7.6 (#3234) | `classes properties add`                  | Bulk syntax: `name:required` repeated                    | `enhancement`, `cli`, `roadmap-cli` | No  | Yes      |
| 7.7 (#3235) | `classes properties remove`               | Detach without deleting underlying property              | `enhancement`, `cli`, `roadmap-cli` | No  | Yes      |
| 7.8 (#3236) | `classes properties reorder`              | `--order` full list or `--move … --before/--after/--to`  | `enhancement`, `cli`, `roadmap-cli` | No  | Yes      |

---

## Epic 8 (#3181): Paths & Operations (CLI)

### Summary Table

| #         | Title                                        | Description                                                | Labels                                  | MVP | Parallel |
|-----------|----------------------------------------------|------------------------------------------------------------|-----------------------------------------|-----|----------|
| 8.1 (#3237) | `paths list` / `paths show`                | Path enumeration + per-path tree                           | `enhancement`, `cli`, `roadmap-cli`, `paths` | No  | Yes      |
| 8.2 (#3238) | `paths create / update / delete`           | Path string CRUD; rename only when no operations exist     | `enhancement`, `cli`, `roadmap-cli`, `paths` | No  | Yes      |
| 8.3 (#3239) | `paths full`                               | Composite hydrated view (`…/full`); JSON-piping friendly   | `enhancement`, `cli`, `roadmap-cli`, `paths` | No  | Yes      |
| 8.4 (#3240) | `paths operations <add/update/delete/describe>` | Operation lifecycle + dedicated `description` endpoint  | `enhancement`, `cli`, `roadmap-cli`, `paths` | No  | Yes      |
| 8.5 (#3241) | `paths parameters <add/update/delete/link>` | Path/query/header/cookie params + per-operation linking    | `enhancement`, `cli`, `roadmap-cli`, `paths` | No  | Yes      |
| 8.6 (#3242) | `paths request-bodies`                     | Bodies + content-types + `copy-from-class` shortcut + link | `enhancement`, `cli`, `roadmap-cli`, `paths` | No  | Yes      |
| 8.7 (#3243) | `paths responses`                          | Same shape as request-bodies; `--status 4xx-defaults`      | `enhancement`, `cli`, `roadmap-cli`, `paths` | No  | Yes      |

### Topic Tree

```
objectified paths
        ├── list
        ├── show <path-id>
        ├── full <path-id>            # composite hydrated view
        ├── create / update / delete
        ├── operations <subcommand>
        ├── parameters <subcommand>
        ├── request-bodies <subcommand>
        └── responses <subcommand>
```

---

## Epic 9 (#3182): Browse & Schema Export (CLI)

### Summary Table

| #         | Title                                                  | Description                                                | Labels                                              | MVP | Parallel |
|-----------|--------------------------------------------------------|------------------------------------------------------------|-----------------------------------------------------|-----|----------|
| 9.1 (#3244) | `browse tenants`                                     | Public tenant directory (no auth required)                 | `enhancement`, `mvp`, `cli`, `roadmap-cli`, `browser` | Yes | Yes      |
| 9.2 (#3245) | `browse projects <tenant>`                           | Public projects per tenant                                 | `enhancement`, `mvp`, `cli`, `roadmap-cli`, `browser` | Yes | Yes      |
| 9.3 (#3246) | `browse versions <tenant>/<project>`                 | Published versions with tags + change summary              | `enhancement`, `mvp`, `cli`, `roadmap-cli`, `browser` | Yes | Yes      |
| 9.4 (#3247) | `schema fetch <tenant>/<project>/<version>`          | OpenAPI 3.1 bundle or single class                          | `enhancement`, `mvp`, `cli`, `roadmap-cli`, `export`, `browser` | Yes | Yes |
| 9.5 (#3248) | `schema swagger`                                     | Download Swagger UI bundle or open in browser              | `enhancement`, `mvp`, `cli`, `roadmap-cli`, `export`, `browser` | Yes | Yes |
| 9.6 (#3249) | `schema arazzo`                                      | Arazzo workflow bundle (default `--format yaml`)           | `enhancement`, `cli`, `roadmap-cli`, `export`, `browser` | No  | Yes |
| 9.7 (#3250) | `schema json`                                        | JSON Schema bundle or per-class                            | `enhancement`, `cli`, `roadmap-cli`, `export`, `browser` | No  | Yes |
| 9.8 (#3251) | `schema diff <v1> <v2>`                              | Summary / unified / SARIF / JSON diff                      | `enhancement`, `cli`, `roadmap-cli`, `browser`, `export` | No | Yes |
| 9.9 (#3252) | `browse open`                                        | Open the browse URL in the default browser                 | `enhancement`, `cli`, `roadmap-cli`, `browser`     | No  | Yes      |

### Notable Detail — 9.4 (#3247) `schema fetch`

The single most important consumer command in the whole CLI:

```
# Full bundle as YAML
$ objectified schema fetch acme-corp/payments-api/v2.1.0 --format yaml > payments.openapi.yaml

# Single class as JSON
$ objectified schema fetch acme-corp/payments-api/v2.1.0 --class Charge --format json | jq

# Verify against expected SHA
$ objectified schema fetch acme-corp/payments-api/v2.1.0 --output payments.json --expect-sha256 7f2c…a041
```

Streamed straight from REST → stdout/file, no parsing in the middle. `--latest`, `--accept tag:stable`, `--expect-sha256` give CI everything it needs to pin a spec and fail loudly when it changes.

---

## Epic 10 (#3183): Data Records (CLI)

### Summary Table

| #         | Title                              | Description                                                | Labels                                         | MVP | Parallel |
|-----------|------------------------------------|------------------------------------------------------------|------------------------------------------------|-----|----------|
| 10.1 (#3253) | `data list --class <class>`     | Cursor-paginated; filters + sort + `--ndjson`              | `enhancement`, `cli`, `roadmap-cli`, `database` | No  | Yes      |
| 10.2 (#3254) | `data get <record-id>`          | Single-record inspect; class required                       | `enhancement`, `cli`, `roadmap-cli`, `database` | No  | Yes      |
| 10.3 (#3255) | `data create`                   | `--from-file` / `--stdin` / `--field`; local schema validation | `enhancement`, `cli`, `roadmap-cli`, `database` | No  | Yes  |
| 10.4 (#3256) | `data update`                   | `--partial` (default) or `--replace`; `--if-version`        | `enhancement`, `cli`, `roadmap-cli`, `database` | No  | Yes      |
| 10.5 (#3257) | `data delete`                   | Soft-delete with audit `--reason`                           | `enhancement`, `cli`, `roadmap-cli`, `database` | No  | Yes      |
| 10.6 (#3258) | `data restore`                  | Re-activate a soft-deleted record                           | `enhancement`, `cli`, `roadmap-cli`, `database` | No  | Yes      |
| 10.7 (#3259) | `data import`                   | NDJSON / JSON / CSV streamer with progress, retries, `--report` | `enhancement`, `cli`, `roadmap-cli`, `database`, `import` | No | Yes |

### Notable Detail — 10.7 (#3259) bulk import

```
       ./charges.ndjson
              │
              ▼
  ┌──────────────────────┐
  │  parser (stream)     │  → validates per-row vs class schema
  └──────────┬───────────┘
             │ batches of 500
             ▼
  ┌──────────────────────┐
  │  worker pool (×4)    │  → POSTs in parallel, retries on 429/5xx
  └──────────┬───────────┘
             ▼
       progress bar + --report
```

Constant-memory streaming; `--report <path>` writes a per-row JSON result file; `--continue-on-error` keeps the loader going past row failures.

---

## Epic 11 (#3184): Migration Plans & Version Tags (CLI)

### Summary Table

| #         | Title                                  | Description                                                   | Labels                                          | MVP | Parallel |
|-----------|----------------------------------------|---------------------------------------------------------------|-------------------------------------------------|-----|----------|
| 11.1 (#3260) | `migrations list`                    | Filter by from/to version + status                            | `enhancement`, `cli`, `roadmap-cli`, `versions` | No  | Yes      |
| 11.2 (#3261) | `migrations counts`                  | Per-project rollup                                            | `enhancement`, `cli`, `roadmap-cli`, `versions` | No  | Yes      |
| 11.3 (#3262) | `migrations show`                    | Full plan body (mappings, deprecations, notes)                | `enhancement`, `cli`, `roadmap-cli`, `versions` | No  | Yes      |
| 11.4 (#3263) | `tags list` / `tags show`            | Float-pointer enumeration + history                           | `enhancement`, `cli`, `roadmap-cli`, `versions` | No  | Yes      |
| 11.5 (#3264) | `tags create`                        | Pin a new tag to a version                                    | `enhancement`, `cli`, `roadmap-cli`, `versions` | No  | Yes      |
| 11.6 (#3265) | `tags update` (move)                 | Promote a tag (`stable` → next semver) with confirmation       | `enhancement`, `cli`, `roadmap-cli`, `versions` | No  | Yes      |
| 11.7 (#3266) | `tags delete`                        | Typed confirmation; doesn't touch the version                 | `enhancement`, `cli`, `roadmap-cli`, `versions` | No  | Yes      |

---

## Epic 12 (#3185): Distribution, Release & Self-Update (NPM, CI/CD)

### Summary Table

| #         | Title                                                      | Description                                                    | Labels                                                                 | MVP | Parallel |
|-----------|------------------------------------------------------------|----------------------------------------------------------------|------------------------------------------------------------------------|-----|----------|
| 12.1 (#3267) | `objectified-cli.yml` GitHub workflow (CI)              | Lint, type-check, tests on every PR (matrix: mac/linux/win × Node 20/22) | `enhancement`, `mvp`, `cli`, `roadmap-cli`, `distribution`, `infrastructure` | Yes | Yes |
| 12.2 (#3268) | `objectified-cli-publish.yml` (NPM artifactory)         | Publish to configurable NPM registry on `cli-v*` tags          | `enhancement`, `mvp`, `cli`, `roadmap-cli`, `distribution`, `npm-publish`, `infrastructure` | Yes | Yes |
| 12.3 (#3269) | Semver release tooling (changesets)                     | Per-PR changesets → bot release PR → `cli-v*` tag               | `enhancement`, `cli`, `roadmap-cli`, `distribution`                    | No  | Yes      |
| 12.4 (#3270) | Cross-platform single-file binaries                     | Node SEA for mac/linux/win, signed + notarized                 | `enhancement`, `cli`, `roadmap-cli`, `distribution`                    | No  | Yes      |
| 12.5 (#3271) | `objectified update` (self-update)                      | Detects install mode (npm/binary/brew/CI), upgrades            | `enhancement`, `cli`, `roadmap-cli`, `distribution`                    | No  | Yes      |
| 12.6 (#3272) | Opt-in anonymous telemetry                              | `telemetry on/off/status`; default off; transparent            | `enhancement`, `cli`, `roadmap-cli`, `distribution`                    | No  | Yes      |
| 12.7 (#3273) | Plugin architecture                                     | `objectified-plugin-*` packages via `@oclif/plugin-plugins`    | `enhancement`, `cli`, `roadmap-cli`, `distribution`                    | No  | Yes      |
| 12.8 (#3274) | Homebrew tap + Scoop manifest                           | Auto-update from release workflow                              | `enhancement`, `cli`, `roadmap-cli`, `distribution`                    | No  | Yes      |

### Detailed Issue Description — 12.2 (#3268) `objectified-cli-publish.yml`

The workflow that satisfies the user requirement: _"a publish step in the GitHub build rule that allows for publishing to an NPM artifactory server."_

```yaml
name: Objectified CLI Publish

on:
  push:
    branches: [ main ]
    paths:
      - 'objectified-cli/package.json'
    tags:
      - 'cli-v*'
  workflow_dispatch:
    inputs:
      dist_tag:
        description: 'NPM dist tag (latest, next, beta, …)'
        default: 'latest'
        required: true
      registry:
        description: 'NPM registry URL'
        default: 'https://registry.npmjs.org'
        required: true

env:
  NPM_REGISTRY: ${{ vars.NPM_REGISTRY || 'https://registry.npmjs.org' }}

jobs:
  publish:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write   # for npm provenance
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: 22
          registry-url: ${{ env.NPM_REGISTRY }}
          cache: npm

      - run: npm ci --workspace=objectified-cli
      - run: npm run codegen --workspace=objectified-cli
      - run: npm run build   --workspace=objectified-cli
      - run: npm test         --workspace=objectified-cli

      - name: Determine dist tag
        id: disttag
        run: |
          ref="${GITHUB_REF##*/}"
          if [[ "$ref" == cli-v*-rc.* ]]; then echo "tag=next" >> $GITHUB_OUTPUT
          elif [[ "$ref" == cli-v*-beta.* ]]; then echo "tag=beta" >> $GITHUB_OUTPUT
          else echo "tag=latest" >> $GITHUB_OUTPUT
          fi

      - name: Publish
        working-directory: objectified-cli
        run: npm publish --provenance --access public --tag ${{ steps.disttag.outputs.tag }}
        env:
          NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}
```

The `NPM_REGISTRY` env var lets us point at npmjs.com, GitHub Packages, JFrog Artifactory, or self-hosted Verdaccio without code changes — only a repo variable.

### Release Pipeline Diagram

```
        ┌──────────┐   merge to main    ┌──────────────────────┐
        │   PR     │ ─────────────────► │  changesets bot PR    │
        └──────────┘                    │  Version Packages     │
                                        │                       │
                                        │ • bump version        │
                                        │ • update CHANGELOG    │
                                        └──────────┬───────────┘
                                                   │ merge
                                                   ▼
                                          git tag cli-v1.2.3
                                                   │
                                                   ▼
                                       triggers 12.2 publish workflow
                                                   │
                                ┌──────────────────┼──────────────────┐
                                ▼                  ▼                  ▼
                              npm           binaries (12.4)        Homebrew/Scoop (12.8)
```

---

## MVP Release — Ticket Bundle

The MVP delivers an installable, useful CLI focused on _read_ and _publish_ for a single project's lifecycle. Total: **20 open sub-tickets** across 5 epics (plus completed foundation items such as #3186, #3187, #3188, #3189, #3190, #3191, and #3192).

| Epic     | Tickets                                                                                                   | Count |
|----------|-----------------------------------------------------------------------------------------------------------|-------|
| 2 (#3175) | #3194, #3195, #3196, #3197, #3198, #3199                                                                  | 6     |
| 3 (#3176) | #3202, #3203, #3204                                                                                        | 3     |
| 4 (#3177) | #3208, #3209, #3210, #3212                                                                                | 4     |
| 9 (#3182) | #3244, #3245, #3246, #3247, #3248                                                                          | 5     |
| 12 (#3185) | #3267, #3268                                                                                               | 2     |

**MVP Demo Story:**
1. `npm i -g objectified-cli`
2. `objectified auth login`
3. `objectified tenants use acme-corp`
4. `objectified projects list`
5. `objectified versions list payments-api`
6. `objectified versions create payments-api --version 2.2.0-rc.1 --notes 'New refund flow'`
7. `objectified versions publish payments-api 2.2.0-rc.1`
8. `objectified schema fetch acme-corp/payments-api/2.2.0-rc.1 --format yaml > payments.openapi.yaml`
9. (CI) `objectified --json projects list | jq` works in any pipeline
10. (Public) `objectified browse tenants` works without authentication

---

## v2 Release — Ticket Bundle

v2 fills out the writable surface for primitives, properties, classes, paths, data records, migrations, version tags, and the release-engineering polish (binaries, self-update, telemetry, plugins, Homebrew/Scoop). Total: **62 sub-tickets**.

| Epic     | v2 Tickets                                                                                                                     | Count |
|----------|--------------------------------------------------------------------------------------------------------------------------------|-------|
| 1 (#3174) | *(complete in this pack)*                                                                                                       | 0     |
| 2 (#3175) | #3200, #3201                                                                                                                   | 2     |
| 3 (#3176) | #3205, #3206, #3207                                                                                                            | 3     |
| 4 (#3177) | #3211, #3213, #3214, #3215, #3216                                                                                              | 5     |
| 5 (#3178) | #3217, #3218, #3219, #3220, #3221, #3222                                                                                       | 6     |
| 6 (#3179) | #3223, #3224, #3225, #3226, #3227, #3228                                                                                       | 6     |
| 7 (#3180) | #3229, #3230, #3231, #3232, #3233, #3234, #3235, #3236                                                                         | 8     |
| 8 (#3181) | #3237, #3238, #3239, #3240, #3241, #3242, #3243                                                                                | 7     |
| 9 (#3182) | #3249, #3250, #3251, #3252                                                                                                     | 4     |
| 10 (#3183) | #3253, #3254, #3255, #3256, #3257, #3258, #3259                                                                                | 7     |
| 11 (#3184) | #3260, #3261, #3262, #3263, #3264, #3265, #3266                                                                                | 7     |
| 12 (#3185) | #3269, #3270, #3271, #3272, #3273, #3274                                                                                       | 6     |

**v2 capability deltas vs MVP:**
- Full read/write CRUD for primitives, properties, classes, paths, operations, parameters, request bodies, and responses — i.e. you can model an entire API surface from the CLI.
- Data plane (records list/get/create/update/delete/restore + bulk import).
- Migration plans + version tags as first-class topics.
- Cross-platform single-file binaries (mac/linux/win, signed/notarized) so install no longer requires Node.
- `objectified update` self-update.
- Opt-in telemetry to drive future prioritization.
- Plugin architecture (`objectified-plugin-*`) for third-party extensions.
- Homebrew tap + Scoop manifest auto-published from the release pipeline.
- Multi-profile management commands and shell completions (bash/zsh/fish/PowerShell).

---

## Labels Created / Reused

| Label              | Meaning                                                                  | Color    |
|--------------------|--------------------------------------------------------------------------|----------|
| `cli`              | Command-line interface (objectified-cli)                                 | `1F6FEB` |
| `roadmap-cli`      | PLANNED_ROADMAP_CLI.md ticket pack                                       | `BFDADC` |
| `npm-publish`      | NPM artifactory publishing workflow                                      | `CB3837` |
| `distribution`     | Release engineering and distribution                                     | `0E8A16` |
| `epic`             | Umbrella issue grouping related sub-issues *(reused)*                    | `6F42C1` |
| `mvp`              | Minimum Viable Product release *(reused)*                                | `ABF781` |
| `enhancement`      | New feature or request *(reused)*                                        | `A2EEEF` |
| `auth`             | Authentication *(reused)*                                                | `9FED28` |
| `tenancy`          | Feature area: tenancy *(reused)*                                         | `605874` |
| `versions`         | Versions section *(reused)*                                              | `AE3B8B` |
| `paths`            | Path Designer *(reused)*                                                 | `FBCA04` |
| `browser`          | Browser application *(reused)*                                           | `B067BA` |
| `export`           | Export functionality *(reused)*                                          | `178C11` |
| `import`           | Import sources *(reused)*                                                | `547B56` |
| `database`         | Feature area: database *(reused)*                                        | `FA666B` |
| `validation`       | Objectified Validation *(reused)*                                        | `D63384` |
| `security`         | Feature area: security *(reused)*                                        | `306360` |
| `api-keys`         | Feature area: api-keys *(reused)*                                        | `700679` |
| `documentation`    | Improvements or additions to documentation *(reused)*                    | `0075CA` |
| `infrastructure`   | Infrastructure and deployment *(reused)*                                 | `0E8A16` |
| `typescript`       | TypeScript-flavored work *(reused)*                                      | `EDEDED` |
| `openapi`          | OpenAPI-related *(reused)*                                               | `0052CC` |
| `git-behavior`     | Git-like version workflows *(reused)*                                    | `5319E7` |
| `ai-generated`     | Generated using AI LLM *(reused)*                                        | `00FF00` |

---

## Execution Order

The tickets were created in the order below — that is also the recommended **execution** order. Earlier epics provide primitives that later epics rely on.

1. **Epic 1 — Foundation** (#3174: #3186, #3187, #3188, #3189, #3190, #3191, #3192, and #3193 landed). Without the scaffold, no other command can exist.
2. **Epic 2 — Auth & Tenants** (#3175 then #3194 → #3201). Required for any tenant-scoped command.
3. **Epic 3 — Projects** (#3176 then #3202 → #3207). The first useful read/write surface.
4. **Epic 4 — Versions** (#3177 then #3208 → #3216). The publish flow that makes the CLI valuable in CI.
5. **Epic 9 — Browse & Schema Export** (#3182 then #3244 → #3252). The most-used consumer surface; lands early because it works without auth.
6. **Epic 12 — Distribution (CI + NPM publish only)** (#3185 then #3267, #3268). Ship MVP — `npm i -g objectified-cli` works.
7. **Epic 5 — Primitives** (#3178 then #3217 → #3222). v2 schema-modeling surface starts here.
8. **Epic 6 — Properties** (#3179 then #3223 → #3228). Builds on primitives.
9. **Epic 7 — Classes** (#3180 then #3229 → #3236). Builds on properties.
10. **Epic 8 — Paths & Operations** (#3181 then #3237 → #3243). Builds on classes (for `copy-from-class`).
11. **Epic 10 — Data Records** (#3183 then #3253 → #3259). Runtime data plane after schema is locked.
12. **Epic 11 — Migration Plans & Version Tags** (#3184 then #3260 → #3266). Polishing on top of versions.
13. **Epic 12 — Distribution (rest)** (#3269 → #3274). Release engineering polish: changesets, binaries, self-update, telemetry, plugins, Homebrew/Scoop.

This order is also encoded in the ticket numbering: every dependency is on a lower-numbered ticket.
