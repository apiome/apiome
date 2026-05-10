# objectified-cli

TypeScript CLI for [Objectified](https://objectified.dev), built with [oclif](https://oclif.io/) v4.

<!-- toc -->
* [objectified-cli](#objectified-cli)
* [Requirements](#requirements)
* [Install (monorepo / local)](#install-monorepo--local)
* [or](#or)
* [Development](#development)
* [Usage](#usage)
* [Commands](#commands)
* [Performance](#performance)
<!-- tocstop -->

# Requirements

- Node.js 20+

# Install (monorepo / local)

From this directory:

```bash
npm install -g .
# or
npm link
```

The `objectified` binary should be on your `PATH`. Man pages ship under `man/man1/` (`man objectified`, `man objectified-config-get`, …) when installed from npm.

# Development

```bash
yarn install   # from repo root
yarn workspace objectified-cli build
yarn workspace objectified-cli dev hello
yarn workspace objectified-cli test
```

The workspace root pins `ansi-regex`, `string-width`, and `strip-ansi` so oclif’s help layout (`widest-line` / `wrap-ansi`) always resolves CommonJS-compatible builds under Yarn’s hoisting.

`yarn build` runs `oclif manifest`, `oclif readme` (this file), and `scripts/generate-man.mjs`. **Commit** updated `README.md`, `package.json` (`man` array), `man/man1/*.1`, and `oclif.manifest.json` when commands change—`yarn test` fails if they drift from `HEAD`.

Specification import **format parity** (CLI vs Import dialog, repository scanner, REST importer): [`docs/CLI_SPEC_IMPORT_FORMAT_PARITY.md`](../docs/CLI_SPEC_IMPORT_FORMAT_PARITY.md) — Epic [#3328](https://github.com/KenSuenobu/objectified-commercial/issues/3328).

# Usage

<!-- usage -->
```sh-session
$ npm install -g objectified-cli
$ objectified COMMAND
running command...
$ objectified (--version)
objectified-cli/0.1.29 <platform> node-v<major.minor.patch>
$ objectified --help [COMMAND]
USAGE
  $ objectified COMMAND
...
```
<!-- usagestop -->

# Commands

<!-- commands -->
* [`objectified auth login`](#objectified-auth-login)
* [`objectified auth logout`](#objectified-auth-logout)
* [`objectified auth status`](#objectified-auth-status)
* [`objectified browse projects TENANT`](#objectified-browse-projects-tenant)
* [`objectified browse tenants`](#objectified-browse-tenants)
* [`objectified browse versions REF`](#objectified-browse-versions-ref)
* [`objectified completion`](#objectified-completion)
* [`objectified completion install [SHELL]`](#objectified-completion-install-shell)
* [`objectified completion show [SHELL]`](#objectified-completion-show-shell)
* [`objectified completion uninstall`](#objectified-completion-uninstall)
* [`objectified config get KEY`](#objectified-config-get-key)
* [`objectified config list`](#objectified-config-list)
* [`objectified config path`](#objectified-config-path)
* [`objectified config set KEY VALUE`](#objectified-config-set-key-value)
* [`objectified docs`](#objectified-docs)
* [`objectified docs completions`](#objectified-docs-completions)
* [`objectified docs errors`](#objectified-docs-errors)
* [`objectified docs output`](#objectified-docs-output)
* [`objectified docs plugins`](#objectified-docs-plugins)
* [`objectified docs profiles`](#objectified-docs-profiles)
* [`objectified docs telemetry`](#objectified-docs-telemetry)
* [`objectified hello [NAME]`](#objectified-hello-name)
* [`objectified help [COMMAND]`](#objectified-help-command)
* [`objectified import spec PATH`](#objectified-import-spec-path)
* [`objectified projects create`](#objectified-projects-create)
* [`objectified projects list`](#objectified-projects-list)
* [`objectified projects show REF`](#objectified-projects-show-ref)
* [`objectified schema fetch REF`](#objectified-schema-fetch-ref)
* [`objectified schema swagger REF`](#objectified-schema-swagger-ref)
* [`objectified tenants info SLUG`](#objectified-tenants-info-slug)
* [`objectified tenants list`](#objectified-tenants-list)
* [`objectified tenants use [SLUG]`](#objectified-tenants-use-slug)
* [`objectified version`](#objectified-version)
* [`objectified versions create PROJECT`](#objectified-versions-create-project)
* [`objectified versions list PROJECT`](#objectified-versions-list-project)
* [`objectified versions publish PROJECT VERSION`](#objectified-versions-publish-project-version)
* [`objectified versions show PROJECT VERSION`](#objectified-versions-show-project-version)
* [`objectified whoami`](#objectified-whoami)

## `objectified auth login`

Sign in via PKCE browser flow or store an API key in the OS keychain (`--api-key`).

```
USAGE
  $ objectified auth login [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config <value>]
    [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose] [--no-browser]

DESCRIPTION
  Sign in via PKCE browser flow or store an API key in the OS keychain (`--api-key`).

EXAMPLES
  $ objectified auth login

  $ objectified --profile staging auth login

  $ objectified auth login --no-browser

  $ objectified auth login --api-key

  $ objectified auth login --api-key sk_live_…

  $ objectified --json auth login

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

OTHER
  --no-browser  Do not launch a browser; print the login URL and read the authorization code from stdin.

SEE ALSO
  objectified auth logout

  objectified auth status

  objectified docs profiles
```

## `objectified auth logout`

Revoke CLI refresh token at the API (OAuth profiles) and remove stored credentials from the OS keychain and any encrypted file fallback.

```
USAGE
  $ objectified auth logout [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config <value>]
    [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose] [--all-profiles]

DESCRIPTION
  Revoke CLI refresh token at the API (OAuth profiles) and remove stored credentials from the OS keychain and any
  encrypted file fallback.

EXAMPLES
  $ objectified auth logout

  $ objectified --profile staging auth logout

  $ objectified auth logout --all-profiles

  $ objectified --json auth logout

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

OTHER
  --all-profiles  Revoke and clear stored OAuth credentials for every profile in config.

SEE ALSO
  objectified auth login

  objectified auth status

  objectified docs profiles
```

## `objectified auth status`

Show active profile, API base URL, tenant, user, auth type, token expiry, and plan (GET /v1/auth/cli/whoami).

```
USAGE
  $ objectified auth status [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config <value>]
    [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose]

DESCRIPTION
  Show active profile, API base URL, tenant, user, auth type, token expiry, and plan (GET /v1/auth/cli/whoami).

EXAMPLES
  $ objectified auth status

  $ objectified --profile staging auth status

  $ objectified --json auth status

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

SEE ALSO
  objectified auth login

  objectified auth logout

  objectified docs output

  objectified docs profiles

ALIASES
  $ objectified whoami
```

## `objectified browse projects TENANT`

List projects for a tenant from GET /v1/browse/tenants/{tenant}/projects (public directory without auth; optional credentials include private projects)

```
USAGE
  $ objectified browse projects TENANT [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config
    <value>] [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose] [--domain <value>]
    [--has-published] [--search <value>] [--limit <value>] [--all]

ARGUMENTS
  TENANT  Tenant slug (for example acme-corp).

DESCRIPTION
  List projects for a tenant from GET /v1/browse/tenants/{tenant}/projects (public directory without auth; optional
  credentials include private projects)

EXAMPLES
  $ objectified browse projects acme-corp

  $ objectified --json browse projects acme-corp

  $ objectified browse projects acme-corp --search payment --domain finance

  $ objectified browse projects acme-corp --has-published --all

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

OTHER
  --all             Print every project returned by the API after filters (no --limit cap).
  --domain=<value>  Filter by project metadata domain or domainCategory (case-insensitive; server-side).
  --has-published   Only projects with at least one published version (any visibility for members; public publishes only
                    when unauthenticated).
  --limit=<value>   [default: 50] Maximum rows to display (1–500; default 50). Ignored with --all.
  --search=<value>  Filter project slug and name (substring; applied on the server).

SEE ALSO
  objectified browse tenants

  objectified projects list

  objectified auth status

  objectified docs errors
```

## `objectified browse tenants`

List tenants with published public specs (GET /v1/browse/tenants; no authentication required)

```
USAGE
  $ objectified browse tenants [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config <value>]
    [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose] [--search <value>] [--sort
    latest|name|projects] [--limit <value>] [--all]

DESCRIPTION
  List tenants with published public specs (GET /v1/browse/tenants; no authentication required)

EXAMPLES
  $ objectified browse tenants

  $ objectified --json browse tenants

  $ objectified browse tenants --search acme --sort latest

  $ objectified browse tenants --all

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

OTHER
  --all             Print every tenant returned by the API after sort/filter (no --limit cap).
  --limit=<value>   [default: 50] Maximum rows to display (1–500; default 50). Ignored with --all.
  --search=<value>  Filter tenant names and slugs (substring; applied on the server).
  --sort=<option>   [default: name] Sort order: name (default), latest (most recent activity first), or projects (desc).
                    <options: latest|name|projects>

SEE ALSO
  objectified tenants list

  objectified auth status

  objectified docs errors
```

## `objectified browse versions REF`

List published versions for a project from GET /v1/browse/tenants/{tenant}/projects/{project}/versions (public directory; optional credentials include non-public published versions)

```
USAGE
  $ objectified browse versions REF [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config
    <value>] [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose] [--since <value>] [--limit
    <value>] [--all]

ARGUMENTS
  REF  Tenant and project slugs as tenant/project (for example acme-corp/payments-api).

DESCRIPTION
  List published versions for a project from GET /v1/browse/tenants/{tenant}/projects/{project}/versions (public
  directory; optional credentials include non-public published versions)

EXAMPLES
  $ objectified browse versions acme-corp/payments-api

  $ objectified --json browse versions acme-corp/payments-api

  $ objectified browse versions acme-corp/payments-api --since 2026-01-01

  $ objectified browse versions acme-corp/payments-api --all

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

OTHER
  --all            Print every version returned by the API after filters (no --limit cap).
  --limit=<value>  [default: 50] Maximum rows to display (1–500; default 50). Ignored with --all.
  --since=<value>  Include only versions published on or after this instant (ISO 8601, forwarded to the API as `since`).

SEE ALSO
  objectified browse projects

  objectified browse tenants

  objectified versions list

  objectified docs errors
```

## `objectified completion`

Install or print shell completion scripts for bash, zsh, fish, or PowerShell.

```
USAGE
  $ objectified completion [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config <value>]
    [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose]

DESCRIPTION
  Install or print shell completion scripts for bash, zsh, fish, or PowerShell.

EXAMPLES
  $ objectified completion install

  $ objectified completion install zsh

  $ objectified completion show bash

  $ objectified completion uninstall

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

SEE ALSO
  objectified docs completions

  objectified hello

  objectified config path
```

## `objectified completion install [SHELL]`

Append shell completion glue to the right startup file for your shell.

```
USAGE
  $ objectified completion install [SHELL] [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config
    <value>] [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose]

ARGUMENTS
  [SHELL]  (bash|zsh|fish|powershell) Shell to install for (default: inferred from $SHELL / OS)

DESCRIPTION
  Append shell completion glue to the right startup file for your shell.

EXAMPLES
  $ objectified completion install

  $ objectified completion install fish

  $ objectified --profile staging completion install zsh

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

SEE ALSO
  objectified completion show

  objectified docs completions

  objectified config path
```

## `objectified completion show [SHELL]`

Print shell completion glue (with marker comments) to stdout.

```
USAGE
  $ objectified completion show [SHELL] [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config
    <value>] [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose]

ARGUMENTS
  [SHELL]  (bash|zsh|fish|powershell) Shell to generate

DESCRIPTION
  Print shell completion glue (with marker comments) to stdout.

EXAMPLES
  $ objectified completion show

  $ objectified completion show bash

  $ objectified completion show fish >> ~/.config/fish/completions/objectified.fish

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

SEE ALSO
  objectified completion install

  objectified docs completions
```

## `objectified completion uninstall`

Remove Objectified completion blocks added by `completion install`.

```
USAGE
  $ objectified completion uninstall [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config <value>]
    [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose]

DESCRIPTION
  Remove Objectified completion blocks added by `completion install`.

EXAMPLES
  $ objectified completion uninstall

  $ objectified --json completion uninstall

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

SEE ALSO
  objectified completion install

  objectified docs completions
```

## `objectified config get KEY`

Print a single config value by dotted key

```
USAGE
  $ objectified config get KEY [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config
    <value>] [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose]

ARGUMENTS
  KEY  Dotted path (e.g. default_profile, profile.prod.base_url)

DESCRIPTION
  Print a single config value by dotted key

EXAMPLES
  $ objectified config get default_profile

  $ objectified config get profile.prod.base_url

  $ objectified --json config get profile.staging.tenant_slug

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

SEE ALSO
  objectified config set

  objectified config path
```

## `objectified config list`

Print the entire config file (stable JSON with --json, otherwise TOML)

```
USAGE
  $ objectified config list [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config <value>]
    [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose]

DESCRIPTION
  Print the entire config file (stable JSON with --json, otherwise TOML)

EXAMPLES
  $ objectified config list

  $ objectified --json config list

  $ objectified config list > backup.toml

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

SEE ALSO
  objectified config path

  objectified config get
```

## `objectified config path`

Print the resolved config.toml path

```
USAGE
  $ objectified config path [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config <value>]
    [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose]

DESCRIPTION
  Print the resolved config.toml path

EXAMPLES
  $ objectified config path

  $ objectified --json config path

  $ objectified config path | pbcopy

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

SEE ALSO
  objectified config get

  objectified config list
```

## `objectified config set KEY VALUE`

Set a config value by dotted key and persist config.toml

```
USAGE
  $ objectified config set KEY VALUE [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config
    <value>] [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose]

ARGUMENTS
  KEY    Dotted path (e.g. default_profile, profile.prod.tenant_slug)
  VALUE  New value (stored as a TOML string)

DESCRIPTION
  Set a config value by dotted key and persist config.toml

EXAMPLES
  $ objectified config set profile.staging.base_url https://api.staging.example

  $ objectified config set default_profile staging

  $ objectified --json config set profile.prod.tenant_slug acme-corp

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

SEE ALSO
  objectified config get

  objectified docs profiles
```

## `objectified docs`

List documentation topics (`objectified docs`) or open one with `objectified docs <topic>`.

```
USAGE
  $ objectified docs [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config <value>]
    [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose]

DESCRIPTION
  List documentation topics (`objectified docs`) or open one with `objectified docs <topic>`.

EXAMPLES
  $ objectified docs

  $ objectified docs output

  $ objectified --json docs

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

SEE ALSO
  objectified docs errors

  objectified hello

  objectified config path
```

## `objectified docs completions`

Shell completions (install/show/uninstall, static manifest + cached REST suggestions)

```
USAGE
  $ objectified docs completions [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config <value>]
    [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose]

DESCRIPTION
  Shell completions (install/show/uninstall, static manifest + cached REST suggestions)

EXAMPLES
  $ objectified docs completions

  $ objectified --help

  $ objectified docs completions --json

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

SEE ALSO
  objectified completion install

  objectified docs output
```

## `objectified docs errors`

Exit codes, hints, and error-handling reference

```
USAGE
  $ objectified docs errors [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config <value>]
    [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose]

DESCRIPTION
  Exit codes, hints, and error-handling reference

EXAMPLES
  $ objectified docs errors

  $ objectified docs errors --json

  $ objectified projects list --json

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

SEE ALSO
  objectified docs

  objectified docs output

  objectified hello
```

## `objectified docs output`

TTY vs JSON output, quiet mode, verbose logs, and color

```
USAGE
  $ objectified docs output [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config <value>]
    [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose]

DESCRIPTION
  TTY vs JSON output, quiet mode, verbose logs, and color

EXAMPLES
  $ objectified docs output

  $ objectified --json hello

  $ objectified docs output > ./output-notes.txt

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

SEE ALSO
  objectified docs

  objectified docs errors

  objectified hello
```

## `objectified docs plugins`

Future oclif plugin extensibility for Objectified

```
USAGE
  $ objectified docs plugins [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config <value>]
    [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose]

DESCRIPTION
  Future oclif plugin extensibility for Objectified

EXAMPLES
  $ objectified docs plugins

  $ objectified docs plugins --json

  $ objectified docs telemetry

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

SEE ALSO
  objectified docs

  objectified docs telemetry
```

## `objectified docs profiles`

config.toml profiles, defaults, and precedence rules

```
USAGE
  $ objectified docs profiles [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config <value>]
    [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose]

DESCRIPTION
  config.toml profiles, defaults, and precedence rules

EXAMPLES
  $ objectified docs profiles

  $ objectified --profile staging config path

  $ objectified docs profiles | sed -n '1,12p'

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

SEE ALSO
  objectified docs

  objectified config path

  objectified config get
```

## `objectified docs telemetry`

Telemetry posture and safe verbose debugging

```
USAGE
  $ objectified docs telemetry [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config <value>]
    [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose]

DESCRIPTION
  Telemetry posture and safe verbose debugging

EXAMPLES
  $ objectified docs telemetry

  $ objectified --verbose hello
  $ objectified docs telemetry

  $ objectified docs telemetry > notes.txt

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

SEE ALSO
  objectified docs errors

  objectified docs output
```

## `objectified hello [NAME]`

Smoke-test greeting for the Objectified CLI

```
USAGE
  $ objectified hello [NAME] [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config
    <value>] [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose]

ARGUMENTS
  [NAME]  Who to greet

DESCRIPTION
  Smoke-test greeting for the Objectified CLI

EXAMPLES
  $ objectified hello

  $ objectified hello Ada

  $ objectified --json hello

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

SEE ALSO
  objectified docs output

  objectified config path
```

## `objectified help [COMMAND]`

Display help for objectified.

```
USAGE
  $ objectified help [COMMAND...] [-n]

ARGUMENTS
  [COMMAND...]  Command to show help for.

DESCRIPTION
  Display help for objectified.

OTHER
  -n, --nested-commands  Include all nested commands in the output.
```

_See code: [@oclif/plugin-help](https://github.com/oclif/plugin-help/blob/6.2.46/src/commands/help.ts)_

## `objectified import spec PATH`

Start a tenant-scoped specification import (POST /v1/tenants/{tenant_slug}/imports with JSON+base64), poll job status with backoff, then commit (default), rollback preview, or stop after preview (`--no-commit`). Supported formats vs the dashboard Import dialog and repository filename scanner: docs/CLI_SPEC_IMPORT_FORMAT_PARITY.md (Epic #3328).

```
USAGE
  $ objectified import spec PATH [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config
    <value>] [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose] [--map-project <value> |
    --create-project | --create-or-map-project | --existing-project-id <value>] [--project-name <value>] [--project-slug
    <value>] [--version <value>] [--project-description <value>] [--version-description <value>] [--domain <value>]
    [--visibility private|public] [--yes] [--format <value>] [--filename <value>] [--dry-run] [--no-wait] [--commit]
    [--rollback]

ARGUMENTS
  PATH  Path to the spec file, or `-` to read raw bytes from stdin.

DESCRIPTION
  Start a tenant-scoped specification import (POST /v1/tenants/{tenant_slug}/imports with JSON+base64), poll job status
  with backoff, then commit (default), rollback preview, or stop after preview (`--no-commit`). Supported formats vs the
  dashboard Import dialog and repository filename scanner: docs/CLI_SPEC_IMPORT_FORMAT_PARITY.md (Epic #3328).

EXAMPLES
  $ objectified import spec ./openapi.yaml --project-name 'Payments API' --project-slug payments-api --version 1.0.0

  $ objectified import spec ./openapi.yaml --map-project payments-api --version 1.0.0

  $ objectified import spec ./openapi.yaml --create-project --project-name 'Payments API' --project-slug payments-api --version 1.0.0 --yes

  $ objectified import spec ./openapi.yaml --tenant acme --create-or-map-project --yes --no-wait

  $ objectified import spec ./openapi.yaml --create-or-map-project --project-name 'Payments API' --project-slug payments-api --version 1.0.0 --yes --no-wait

  $ objectified --json import spec ./spec.json --project-slug my-api --project-name 'My API' --version 2.0.0 --no-wait

  $ objectified import spec - --filename ./api.yaml --project-slug svc --project-name Service --version 0.1.0 < ./api.yaml

  $ objectified import spec ./asyncapi.yml --project-slug events --project-name Events --version 1.0.0 --dry-run

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

OTHER
  --[no-]commit                  After preview (pending-approval), POST …/commit (default). Use --no-commit to leave the
                                 preview transaction open.
  --create-or-map-project        Resolve project by slug: reuse when metadata matches; otherwise create then import
                                 (CI-friendly). Mutually exclusive with --map-project and --create-project.
  --create-project               POST /v1/projects/{tenant} when --project-slug is free, then import onto that project
                                 id. Refuses if the slug already exists.
  --domain=<value>               Optional domainCategory when creating a project (only with --create-project or
                                 --create-or-map-project).
  --dry-run                      Forward dry_run in import options (validate/analyze without persisting;
                                 server-defined).
  --existing-project-id=<value>  Legacy: attach the job to this catalog project id. Cannot be combined with
                                 --map-project / --create-project / --create-or-map-project.
  --filename=<value>             Original filename hint when PATH is `-` (improves sniffing for stdin payloads); may
                                 include directories (basename is used).
  --format=<value>               Importer kind when extension/content sniff is ambiguous (openapi-3, asyncapi-2,
                                 protobuf, graphql, …).
  --map-project=<value>          Target an existing catalog project by slug (tenant-scoped lookup); forwards
                                 metadata.existing_project_id. Mutually exclusive with --create-project,
                                 --create-or-map-project, and --existing-project-id.
  --no-wait                      Start the job and print the job id immediately without polling or finalize calls (CI
                                 stitching).
  --project-description=<value>  Optional project description forwarded in import metadata.
  --project-name=<value>         Display name for the catalog project. With --create-or-map-project, defaults to
                                 info.title from OpenAPI/AsyncAPI. Otherwise required except with --map-project
                                 (optional there for validation only).
  --project-slug=<value>         URL-safe project slug (^[a-z][a-z0-9-]{1,62}$). With --create-or-map-project, derived
                                 from the display name when omitted. Otherwise required unless --map-project supplies
                                 the slug.
  --rollback                     After preview (pending-approval), POST …/rollback instead of commit (implies
                                 --no-commit).
  --version=<value>              Semantic version id for the imported catalog revision (for example 1.0.0). With
                                 --create-or-map-project, defaults to info.version from OpenAPI/AsyncAPI when omitted.
                                 Required for other project strategies.
  --version-description=<value>  Optional version description forwarded in import metadata.
  --visibility=<option>          Optional visibility metadata when creating a project: private or public (default:
                                 private).
                                 <options: private|public>
  --yes                          Non-interactive guard for CI scripts (recommended with create-if-missing flags; import
                                 itself does not prompt).

SEE ALSO
  objectified projects create

  objectified versions create

  objectified docs errors

  objectified tenants use
```

## `objectified projects create`

Create a project for the active tenant (POST /v1/projects/{tenant_slug}); interactive or CI flags.

```
USAGE
  $ objectified projects create [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config <value>]
    [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose] [--name <value>] [--slug <value>]
    [--description <value>] [--domain <value>] [--visibility private|public] [--from-file <value>] [--yes] [--dry-run]

DESCRIPTION
  Create a project for the active tenant (POST /v1/projects/{tenant_slug}); interactive or CI flags.

EXAMPLES
  $ objectified projects create

  $ objectified projects create --name 'Payments API' --slug payments-api --yes

  $ objectified projects create --from-file ./project.yaml --yes

  $ objectified projects create --dry-run --name 'Payments API' --slug payments-api

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

OTHER
  --description=<value>  Optional description.
  --domain=<value>       Domain category id (metadata domainCategory). Validated against GET …/domains when available.
  --dry-run              Print the POST JSON body and exit without calling the API.
  --from-file=<value>    Load fields from JSON or YAML (validated JSON Schema).
  --name=<value>         Project display name.
  --slug=<value>         URL-safe slug (^[a-z][a-z0-9-]{1,62}$).
  --visibility=<option>  Stored in project metadata: private or public.
                         <options: private|public>
  --yes                  Skip confirmation prompts (CI guard).

SEE ALSO
  objectified projects list

  objectified projects show

  objectified tenants use

  objectified docs errors
```

## `objectified projects list`

List Objectified projects for the active tenant (GET /v1/projects/{tenant_slug})

```
USAGE
  $ objectified projects list [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config <value>]
    [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose] [--limit <value>] [--all] [--sort
    <value>] [--filter <value>...] [--search <value>] [--columns <value>] [--include-deleted]

DESCRIPTION
  List Objectified projects for the active tenant (GET /v1/projects/{tenant_slug})

EXAMPLES
  $ objectified projects list

  $ objectified --json projects list

  $ objectified projects list --sort name --limit 25

  $ objectified projects list --filter domain=finance --search payment

  $ objectified --profile staging projects list --all

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

OTHER
  --all                List every matching row after sort/filter (no --limit cap).
  --columns=<value>    Comma-separated columns: slug, name, domain, versions, latest, latest_published_at, description,
                       id, updated_at, enabled, creator_email, creator_name, published_at.
  --filter=<value>...  Keep rows where a field equals a value (case-insensitive). Example: --filter domain=finance
  --include-deleted    Include soft-deleted projects from the API.
  --limit=<value>      [default: 50] Maximum rows after sort/filter (1–500; default 50). Ignored with --all.
  --search=<value>     Case-insensitive substring match across slug, name, and description.
  --sort=<value>       Sort by field; prefix with '-' for descending. Fields: name, slug, updated_at, published_at
                       (default: slug).

SEE ALSO
  objectified tenants use

  objectified config path

  objectified docs errors
```

## `objectified projects show REF`

Show one project by slug or UUID (GET /v1/projects/{tenant}/{id} or …/by-slug/{slug})

```
USAGE
  $ objectified projects show REF [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config
    <value>] [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose]

ARGUMENTS
  REF  Project slug or project UUID (uuid-shaped refs resolve as id first)

DESCRIPTION
  Show one project by slug or UUID (GET /v1/projects/{tenant}/{id} or …/by-slug/{slug})

EXAMPLES
  $ objectified projects show payments-api

  $ objectified --json projects show payments-api

  $ objectified projects show 33333333-4444-5555-6666-777777777777

  $ objectified --profile staging projects show my-project

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

SEE ALSO
  objectified projects list

  objectified tenants use

  objectified docs errors
```

## `objectified schema fetch REF`

Download the published OpenAPI bundle or one class schema from GET /v1/schema/{tenant}/{project}/{version}[/{class}] (stdin/stdout friendly; optional checksum gate).

```
USAGE
  $ objectified schema fetch REF [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config
    <value>] [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose] [-c <value>] [--format
    json|yaml] [-o <value>] [--expect-sha256 <value>] [--latest] [--accept <value>]

ARGUMENTS
  REF  Published target as tenant/project/version (slashes separate the three slugs; semver, latest, or server-resolved
       tag via --accept).

DESCRIPTION
  Download the published OpenAPI bundle or one class schema from GET /v1/schema/{tenant}/{project}/{version}[/{class}]
  (stdin/stdout friendly; optional checksum gate).

EXAMPLES
  $ objectified schema fetch acme-corp/payments-api/2.1.0

  $ objectified schema fetch acme-corp/payments-api/2.1.0 --format yaml > spec.yaml

  $ objectified schema fetch acme-corp/payments-api/2.1.0 --class Charge --format json

  $ objectified schema fetch acme-corp/payments-api/2.1.0 --output ./build/openapi.json

  $ objectified schema fetch acme-corp/payments-api/2.1.0 --expect-sha256 <64-hex>

  $ objectified schema fetch acme-corp/payments-api/2.1.0 --latest

  $ objectified schema fetch acme-corp/payments-api/2.1.0 --accept tag:stable

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

OTHER
  --accept=<value>         Extra Accept token forwarded to the API (for example tag:stable); combined with class
                               format negotiation when --class is set.
  -c, --class=<value>          Fetch only this class (GET adds /{class_name}; uses content negotiation for JSON vs
                               YAML).
      --expect-sha256=<value>  SHA-256 of the emitted bytes (after --format); exit 7 when the digest does not match (CI
                               drift gate).
      --format=<option>        [default: json] Output serialization. Full-bundle YAML is converted client-side from
                               JSON.
                               <options: json|yaml>
      --latest                 Send version_slug `latest` (overrides the third segment of the positional ref).
  -o, --output=<value>         Write bytes to this path instead of stdout.

SEE ALSO
  objectified browse versions

  objectified versions show

  objectified docs errors
```

## `objectified schema swagger REF`

Open hosted Swagger UI at GET /v1/swagger/{tenant}/{project}/{version} or download the published OpenAPI bundle (GET /v1/schema/…) as JSON/YAML. On an interactive TTY, defaults to opening the browser unless --output or --format is set; piping, non-TTY stdout, or global --json emits the bundle instead.

```
USAGE
  $ objectified schema swagger REF [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config
    <value>] [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose] [--open] [--format json|yaml]
    [-o <value>]

ARGUMENTS
  REF  Published target as tenant/project/version (slashes separate the three slugs; semver or published tag slug).

DESCRIPTION
  Open hosted Swagger UI at GET /v1/swagger/{tenant}/{project}/{version} or download the published OpenAPI bundle (GET
  /v1/schema/…) as JSON/YAML. On an interactive TTY, defaults to opening the browser unless --output or --format is set;
  piping, non-TTY stdout, or global --json emits the bundle instead.

EXAMPLES
  $ objectified schema swagger acme-corp/payments-api/2.1.0

  $ objectified schema swagger acme-corp/payments-api/2.1.0 --open

  $ objectified schema swagger acme-corp/payments-api/2.1.0 --output ./swagger.json

  $ objectified schema swagger acme-corp/payments-api/2.1.0 --format json > ./openapi.json

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

OTHER
  --format=<option>  Bundle serialization for download mode (GET /v1/schema/…). When set without --output, writes to
                         stdout. Full-bundle YAML is converted client-side from JSON.
                         <options: json|yaml>
      --open             Open the Swagger UI page in the default browser (also the default when stdout is a TTY and
                         neither --output nor --format is set).
  -o, --output=<value>   Write the OpenAPI bundle to this path instead of stdout (GET /v1/schema/…).

SEE ALSO
  objectified schema fetch

  objectified browse versions

  objectified versions show
```

## `objectified tenants info SLUG`

Show tenant details when you have access (GET /v1/tenants/{slug})

```
USAGE
  $ objectified tenants info SLUG [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config
    <value>] [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose]

ARGUMENTS
  SLUG  Tenant slug

DESCRIPTION
  Show tenant details when you have access (GET /v1/tenants/{slug})

EXAMPLES
  $ objectified tenants info acme-corp

  $ objectified --json tenants info acme-corp

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

SEE ALSO
  objectified tenants list

  objectified tenants use

  objectified auth status

  objectified config path
```

## `objectified tenants list`

List tenants you can access (GET /v1/tenants/me)

```
USAGE
  $ objectified tenants list [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config <value>]
    [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose] [--limit <value>] [--offset <value>]

DESCRIPTION
  List tenants you can access (GET /v1/tenants/me)

EXAMPLES
  $ objectified tenants list

  $ objectified --json tenants list

  $ objectified tenants list --limit 100 --offset 0

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

OTHER
  --limit=<value>   [default: 50] Page size for /v1/tenants/me (1–100; default 50).
  --offset=<value>  Offset into the full tenant list (pagination).

SEE ALSO
  objectified tenants info

  objectified tenants use

  objectified auth status

  objectified config path
```

## `objectified tenants use [SLUG]`

Set or clear the default tenant slug for the active profile (writes tenant_slug in config.toml; validates via HEAD /v1/tenants/{slug})

```
USAGE
  $ objectified tenants use [SLUG] [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config
    <value>] [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose] [--clear]

ARGUMENTS
  [SLUG]  Tenant slug to use as the profile default

DESCRIPTION
  Set or clear the default tenant slug for the active profile (writes tenant_slug in config.toml; validates via HEAD
  /v1/tenants/{slug})

EXAMPLES
  $ objectified tenants use acme-corp

  $ objectified tenants use --profile staging acme-staging

  $ objectified --json tenants use acme-corp

  $ objectified tenants use --clear

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

OTHER
  --clear  Remove tenant_slug from this profile so each command needs --tenant or OBJECTIFIED_TENANT.

SEE ALSO
  objectified tenants list

  objectified config path

  objectified docs profiles
```

## `objectified version`

```
USAGE
  $ objectified version [--json] [--verbose]

OTHER
  --verbose  Show additional information about the CLI.

GLOBAL
  --json  Format output as json.

FLAG DESCRIPTIONS
  --verbose  Show additional information about the CLI.

    Additionally shows the architecture, node version, operating system, and versions of plugins that the CLI is using.
```

_See code: [@oclif/plugin-version](https://github.com/oclif/plugin-version/blob/2.2.43/src/commands/version.ts)_

## `objectified versions create PROJECT`

Create a new draft schema revision (POST /v1/versions/{tenant_slug}/{project_id}); CI-friendly.

```
USAGE
  $ objectified versions create PROJECT [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config
    <value>] [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose] [--version <value>] [--notes
    <value>] [--notes-file <value>] [--base <value>] [--branch <value>] [--draft] [--from-file <value>]

ARGUMENTS
  PROJECT  Project slug or UUID (uuid-shaped refs resolve as id first)

DESCRIPTION
  Create a new draft schema revision (POST /v1/versions/{tenant_slug}/{project_id}); CI-friendly.

EXAMPLES
  $ objectified versions create payments-api --version 2.2.0-rc.1 --notes 'Adds idempotency keys'

  $ objectified --json versions create payments-api --version 1.4.0 --notes-file ./CHANGELOG.md

  $ objectified versions create payments-api --version 2.0.0 --base v1.9.0

  $ objectified versions create payments-api --from-file ./version-create.json

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

OTHER
  --base=<value>        Copy schema from this semver, revision UUID, or tag (default: latest published revision, if
                        any).
  --branch=<value>      Named branch to advance when the project has multiple version branches.
  --[no-]draft          Create a draft revision (default). Publishing via --no-draft is not supported here — use
                        `versions publish` when available.
  --from-file=<value>   Merge fields from a JSON object (VersionCreateRequest-shaped). CLI flags override file values
                        where both are set.
  --notes=<value>       Release notes (markdown). First line is also used as the short revision note.
  --notes-file=<value>  Read release notes as UTF-8 markdown from a file (mutually exclusive with --notes).
  --version=<value>     Semantic version for the new draft (required unless set in --from-file).

SEE ALSO
  objectified versions list

  objectified versions show

  objectified versions publish

  objectified projects show

  objectified docs errors
```

## `objectified versions list PROJECT`

List schema versions for a project (GET /v1/versions/{tenant_slug}/{project_id}; tags joined from version tags)

```
USAGE
  $ objectified versions list PROJECT [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config
    <value>] [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose] [--state <value>] [--limit
    <value>] [--all] [--sort <value>] [--reverse]

ARGUMENTS
  PROJECT  Project slug or UUID (uuid-shaped refs resolve as id first)

DESCRIPTION
  List schema versions for a project (GET /v1/versions/{tenant_slug}/{project_id}; tags joined from version tags)

EXAMPLES
  $ objectified versions list payments-api

  $ objectified --json versions list payments-api

  $ objectified versions list payments-api --state draft,published --limit 25

  $ objectified versions list payments-api --sort published_at --reverse

  $ objectified --profile staging versions list my-api --all

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

OTHER
  --all            List every matching version after sort/filter (no --limit cap).
  --limit=<value>  [default: 10] Maximum rows after sort/filter (1–500; default 10). Ignored with --all.
  --reverse        Reverse the default sort direction (defaults are descending).
  --sort=<value>   Sort by version, published_at, or created_at (default: version).
  --state=<value>  Comma-separated filters (OR): draft, published, archived, frozen. Matches CLI-derived states.

SEE ALSO
  objectified projects show

  objectified projects list

  objectified tenants use

  objectified docs errors
```

## `objectified versions publish PROJECT VERSION`

Publish a draft schema revision (POST …/{record_id}/publish); runs pre-publish checks unless skipped (#3212).

```
USAGE
  $ objectified versions publish PROJECT VERSION [--api-key <value>] [--api-key-file <value>] [--base-url <value>]
    [--config <value>] [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose] [--allow-breaking]
    [--skip-checks] [--update-tag <value>] [-m <value>] [--yes]

ARGUMENTS
  PROJECT  Project slug or UUID (uuid-shaped refs resolve as id first)
  VERSION  Draft semver (`v` optional), revision UUID, or tag resolving to a draft

DESCRIPTION
  Publish a draft schema revision (POST …/{record_id}/publish); runs pre-publish checks unless skipped (#3212).

EXAMPLES
  $ objectified versions publish payments-api v2.1.0

  $ objectified --json versions publish payments-api 2.1.0

  $ objectified versions publish payments-api v2.1.0 --allow-breaking

  $ objectified versions publish payments-api v2.1.0 --update-tag latest --message 'Ship refunds'

  $ objectified versions publish payments-api v2.1.0 --skip-checks --yes

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

OTHER
  --allow-breaking      Allow publish when POST …/compatibility reports breaking changes versus the published
                            baseline.
  -m, --message=<value>     Publish short message stored as revision note (maps to shortMessage on publish).
      --skip-checks         Bypass client-side pre-publish checks and send skipPublishChecks to the API (emergency
                            only).
      --update-tag=<value>  After a successful publish, move this tag name to the published revision (create if
                            missing).
      --yes                 Acknowledge destructive/skip-checks flows non-interactively (required with --skip-checks).

SEE ALSO
  objectified versions create

  objectified versions list

  objectified versions show

  objectified docs errors
```

## `objectified versions show PROJECT VERSION`

Show one schema revision by semver, revision UUID, or tag name (GET …/{record_id} or …/by-version/{version_id}; tags from version tags)

```
USAGE
  $ objectified versions show PROJECT VERSION [--api-key <value>] [--api-key-file <value>] [--base-url <value>]
    [--config <value>] [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose]

ARGUMENTS
  PROJECT  Project slug or UUID (uuid-shaped refs resolve as id first)
  VERSION  Semver string (with or without v), revision UUID, or tag name (e.g. stable)

DESCRIPTION
  Show one schema revision by semver, revision UUID, or tag name (GET …/{record_id} or …/by-version/{version_id}; tags
  from version tags)

EXAMPLES
  $ objectified versions show payments-api v2.1.0

  $ objectified versions show payments-api 2.1.0

  $ objectified --json versions show payments-api stable

  $ objectified versions show payments-api 22222222-2222-2222-2222-222222222222

  $ objectified --profile staging versions show my-api next

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

SEE ALSO
  objectified versions list

  objectified projects show

  objectified tenants use

  objectified docs errors
```

## `objectified whoami`

Show active profile, API base URL, tenant, user, auth type, token expiry, and plan (GET /v1/auth/cli/whoami).

```
USAGE
  $ objectified whoami [--api-key <value>] [--api-key-file <value>] [--base-url <value>] [--config <value>]
    [--json] [--color] [--profile <value>] [--tenant <value>] [-q] [--verbose]

DESCRIPTION
  Show active profile, API base URL, tenant, user, auth type, token expiry, and plan (GET /v1/auth/cli/whoami).

EXAMPLES
  $ objectified whoami

  $ objectified --profile staging whoami

  $ objectified --json whoami

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.
  --tenant=<value>    [env: OBJECTIFIED_TENANT] Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config
                      tenant_slug).

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>       [env: OBJECTIFIED_API_KEY] API key for direct authentication (OBJECTIFIED_API_KEY); overrides
                          config.toml api_key. Not persisted unless you run `auth login --api-key`.
  --api-key-file=<value>  Read API key from a file (single line; avoids shell history).

SEE ALSO
  objectified auth login

  objectified auth logout

  objectified docs output

  objectified docs profiles

ALIASES
  $ objectified whoami
```
<!-- commandsstop -->

Global flags apply to every command (see **`objectified --help`**): `--api-key`, `--base-url`, `--config`, `--json`, `--no-color`, `--profile`, `--quiet`/`-q`, `--verbose`, plus env vars `OBJECTIFIED_*` and `NO_COLOR`. Effective API URL and optional API key resolve in order: **CLI flag → environment → `[profile.NAME]` in config → `[default]` in config → built-in default** (`https://api.objectified.dev` for the URL). Config file default path: `~/.config/objectified/config.toml`.

You may place global flags before the subcommand (for example `objectified --json projects list`); the runtime reorders them for oclif.

Longer prose lives under **`objectified docs <topic>`** (`output`, `errors`, `profiles`, `completions`, `plugins`, `telemetry`).

# Performance

`objectified --version` and `objectified --help` are sized for sub‑200 ms cold start on typical developer hardware (see integration test budgets).
