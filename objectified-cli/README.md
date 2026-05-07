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

# Usage

<!-- usage -->
```sh-session
$ npm install -g objectified-cli
$ objectified COMMAND
running command...
$ objectified (--version)
objectified-cli/0.1.7 <platform> node-v<major.minor.patch>
$ objectified --help [COMMAND]
USAGE
  $ objectified COMMAND
...
```
<!-- usagestop -->

# Commands

<!-- commands -->
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
* [`objectified projects list`](#objectified-projects-list)
* [`objectified version`](#objectified-version)

## `objectified completion`

Install or print shell completion scripts for bash, zsh, fish, or PowerShell.

```
USAGE
  $ objectified completion [--api-key <value>] [--base-url <value>] [--config <value>] [--json] [--color]
    [--profile <value>] [-q] [--verbose]

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

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>  API key for direct authentication (bypasses login token).

SEE ALSO
  objectified docs completions

  objectified hello

  objectified config path
```

## `objectified completion install [SHELL]`

Append shell completion glue to the right startup file for your shell.

```
USAGE
  $ objectified completion install [SHELL] [--api-key <value>] [--base-url <value>] [--config <value>] [--json]
    [--color] [--profile <value>] [-q] [--verbose]

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

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>  API key for direct authentication (bypasses login token).

SEE ALSO
  objectified completion show

  objectified docs completions

  objectified config path
```

## `objectified completion show [SHELL]`

Print shell completion glue (with marker comments) to stdout.

```
USAGE
  $ objectified completion show [SHELL] [--api-key <value>] [--base-url <value>] [--config <value>] [--json]
    [--color] [--profile <value>] [-q] [--verbose]

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

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>  API key for direct authentication (bypasses login token).

SEE ALSO
  objectified completion install

  objectified docs completions
```

## `objectified completion uninstall`

Remove Objectified completion blocks added by `completion install`.

```
USAGE
  $ objectified completion uninstall [--api-key <value>] [--base-url <value>] [--config <value>] [--json] [--color]
    [--profile <value>] [-q] [--verbose]

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

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>  API key for direct authentication (bypasses login token).

SEE ALSO
  objectified completion install

  objectified docs completions
```

## `objectified config get KEY`

Print a single config value by dotted key

```
USAGE
  $ objectified config get KEY [--api-key <value>] [--base-url <value>] [--config <value>] [--json] [--color]
    [--profile <value>] [-q] [--verbose]

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

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>  API key for direct authentication (bypasses login token).

SEE ALSO
  objectified config set

  objectified config path
```

## `objectified config list`

Print the entire config file (stable JSON with --json, otherwise TOML)

```
USAGE
  $ objectified config list [--api-key <value>] [--base-url <value>] [--config <value>] [--json] [--color]
    [--profile <value>] [-q] [--verbose]

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

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>  API key for direct authentication (bypasses login token).

SEE ALSO
  objectified config path

  objectified config get
```

## `objectified config path`

Print the resolved config.toml path

```
USAGE
  $ objectified config path [--api-key <value>] [--base-url <value>] [--config <value>] [--json] [--color]
    [--profile <value>] [-q] [--verbose]

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

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>  API key for direct authentication (bypasses login token).

SEE ALSO
  objectified config get

  objectified config list
```

## `objectified config set KEY VALUE`

Set a config value by dotted key and persist config.toml

```
USAGE
  $ objectified config set KEY VALUE [--api-key <value>] [--base-url <value>] [--config <value>] [--json]
    [--color] [--profile <value>] [-q] [--verbose]

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

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>  API key for direct authentication (bypasses login token).

SEE ALSO
  objectified config get

  objectified docs profiles
```

## `objectified docs`

List documentation topics (`objectified docs`) or open one with `objectified docs <topic>`.

```
USAGE
  $ objectified docs [--api-key <value>] [--base-url <value>] [--config <value>] [--json] [--color]
    [--profile <value>] [-q] [--verbose]

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

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>  API key for direct authentication (bypasses login token).

SEE ALSO
  objectified docs errors

  objectified hello

  objectified config path
```

## `objectified docs completions`

Shell completions (install/show/uninstall, static manifest + cached REST suggestions)

```
USAGE
  $ objectified docs completions [--api-key <value>] [--base-url <value>] [--config <value>] [--json] [--color]
    [--profile <value>] [-q] [--verbose]

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

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>  API key for direct authentication (bypasses login token).

SEE ALSO
  objectified docs

  objectified docs output
```

## `objectified docs errors`

Exit codes, hints, and error-handling reference

```
USAGE
  $ objectified docs errors [--api-key <value>] [--base-url <value>] [--config <value>] [--json] [--color]
    [--profile <value>] [-q] [--verbose]

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

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>  API key for direct authentication (bypasses login token).

SEE ALSO
  objectified docs

  objectified docs output

  objectified hello
```

## `objectified docs output`

TTY vs JSON output, quiet mode, verbose logs, and color

```
USAGE
  $ objectified docs output [--api-key <value>] [--base-url <value>] [--config <value>] [--json] [--color]
    [--profile <value>] [-q] [--verbose]

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

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>  API key for direct authentication (bypasses login token).

SEE ALSO
  objectified docs

  objectified docs errors

  objectified hello
```

## `objectified docs plugins`

Future oclif plugin extensibility for Objectified

```
USAGE
  $ objectified docs plugins [--api-key <value>] [--base-url <value>] [--config <value>] [--json] [--color]
    [--profile <value>] [-q] [--verbose]

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

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>  API key for direct authentication (bypasses login token).

SEE ALSO
  objectified docs

  objectified docs telemetry
```

## `objectified docs profiles`

config.toml profiles, defaults, and precedence rules

```
USAGE
  $ objectified docs profiles [--api-key <value>] [--base-url <value>] [--config <value>] [--json] [--color]
    [--profile <value>] [-q] [--verbose]

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

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>  API key for direct authentication (bypasses login token).

SEE ALSO
  objectified docs

  objectified config path

  objectified config get
```

## `objectified docs telemetry`

Telemetry posture and safe verbose debugging

```
USAGE
  $ objectified docs telemetry [--api-key <value>] [--base-url <value>] [--config <value>] [--json] [--color]
    [--profile <value>] [-q] [--verbose]

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

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>  API key for direct authentication (bypasses login token).

SEE ALSO
  objectified docs errors

  objectified docs output
```

## `objectified hello [NAME]`

Smoke-test greeting for the Objectified CLI

```
USAGE
  $ objectified hello [NAME] [--api-key <value>] [--base-url <value>] [--config <value>] [--json] [--color]
    [--profile <value>] [-q] [--verbose]

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

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>  API key for direct authentication (bypasses login token).

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

## `objectified projects list`

List Objectified projects

```
USAGE
  $ objectified projects list [--api-key <value>] [--base-url <value>] [--config <value>] [--json] [--color]
    [--profile <value>] [-q] [--verbose]

DESCRIPTION
  List Objectified projects

EXAMPLES
  $ objectified projects list

  $ objectified --json projects list

  $ objectified --profile staging projects list

COMMON
  --base-url=<value>  Root REST API URL.
  --config=<value>    Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified
                      config path`).
  --profile=<value>   Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.

OUTPUT
  --[no-]color  Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).
      --[no-]json   Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).
  -q, --quiet       Suppress non-error stdout (spinners, banners, tips).
      --verbose     Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).

AUTH
  --api-key=<value>  API key for direct authentication (bypasses login token).

SEE ALSO
  objectified config path

  objectified docs errors

  objectified hello
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
<!-- commandsstop -->

Global flags apply to every command (see **`objectified --help`**): `--api-key`, `--base-url`, `--config`, `--json`, `--no-color`, `--profile`, `--quiet`/`-q`, `--verbose`, plus env vars `OBJECTIFIED_*` and `NO_COLOR`. Effective API URL and optional API key resolve in order: **CLI flag → environment → `[profile.NAME]` in config → `[default]` in config → built-in default** (`https://api.objectified.dev` for the URL). Config file default path: `~/.config/objectified/config.toml`.

You may place global flags before the subcommand (for example `objectified --json projects list`); the runtime reorders them for oclif.

Longer prose lives under **`objectified docs <topic>`** (`output`, `errors`, `profiles`, `completions`, `plugins`, `telemetry`).

# Performance

`objectified --version` and `objectified --help` are sized for sub‑200 ms cold start on typical developer hardware (see integration test budgets).
