/** Long-form prose for `objectified docs <topic>` (single source with command classes). */

export const docsTopicOutput = `
OUTPUT FORMATTING

Human vs machine
  When stdout is a terminal, commands print tables, hints, and optional color (unless NO_COLOR or --no-color applies). When stdout is not a TTY, JSON mode is chosen automatically unless you pass --no-json.

Stable JSON
  With --json (or non-TTY stdout), emitted JSON is sorted by key where applicable and avoids decorative fields. Pipe output to jq or similar tools.

auth status --json (stable schema, #3196)
  Keys: base_url (string), profile (string), tenant ({ slug, name } | null, where name may be null), user ({ id: string | null, email: string | null }), plan (string | null), auth ({ type: "oauth" | "api_key", expires_at?: string | null }). expires_at is access-token expiry as ISO 8601 UTC when type is oauth (from GET /v1/auth/cli/whoami, or JWT exp fallback). Omitted for api_key auth. Human-facing status fetches GET /v1/auth/cli/whoami, and for stored OAuth may silently perform POST /v1/auth/cli/token then retry whoami once after a 401.

Quiet and verbose
  --quiet (-q) hides non-error stdout such as banners and spinners while keeping errors on stderr. --verbose adds diagnostic detail on stderr without changing stdout payloads.

Color
  Color follows --color / --no-color, NO_COLOR, TTY detection, and terminal capability. Help output uses the same rules.

YAML and tables
  Some commands may offer YAML for debugging; tables use cli-table3 with ASCII-friendly borders when LANG suggests C/POSIX locales.
`.trim();

export const docsTopicProfiles = `
CONFIG PROFILES

config.toml
  The CLI reads ~/.config/objectified/config.toml by default (or OBJECTIFIED_CONFIG / --config). Profiles live under [profile.NAME] with defaults under [default].

default_profile
  default_profile selects which profile is active when --profile is omitted. Use objectified config get default_profile or objectified config set default_profile staging.

Resolution order
  Base URL and tenant slug resolve per profile: explicit flags and env vars override profile values, which override [default]. API keys resolve in order: --api-key, OBJECTIFIED_API_KEY, --api-key-file, then optional api_key in config.toml ([profile.NAME] over [default]), then a key stored with objectified auth login --api-key (#3195). Prefer env or keychain over plain config files on shared machines (see cli-security.md).

Stored credentials (#3197)
  OAuth and API keys from auth login are stored in the OS keychain when available; otherwise in an AES-256-GCM encrypted file next to config (threat model: https://github.com/KenSuenobu/objectified-commercial/blob/main/objectified-cli/docs/cli-security.md). Environment overrides: OBJECTIFIED_CLI_CREDENTIAL_VAULT_DIR, OBJECTIFIED_CLI_CREDENTIAL_VAULT_RESET, OBJECTIFIED_CLI_CREDENTIAL_DISABLE_FILE_FALLBACK.

Switching profiles
  Pass --profile <name> for a single invocation or change default_profile for every command.
`.trim();

export const docsTopicCompletions = `
SHELL COMPLETIONS

Commands
  objectified completion install [bash|zsh|fish|powershell] — append a small wrapper to your shell startup file (bash ~/.bashrc, zsh ~/.zshrc, fish ~/.config/fish/completions/<bin>.fish, PowerShell profile). It prints a one-liner to source or dot the file in the current session.
  objectified completion show [shell] — print the same managed block to stdout (for packaging or manual install).
  objectified completion uninstall — remove only the marked block we added.

Static vs dynamic
  Topics, subcommands, and flags are completed offline from the CLI manifest.
  Tenant slugs from config profiles, project slugs, version identifiers, class names, and primitive names are loaded from the REST API when online, cached for five minutes per profile under ~/.cache/objectified/completion/, and omitted when the API is unreachable.

Examples
  objectified projects show pay<TAB> completes project slugs for the active tenant profile.
  objectified versions list my-api v<TAB> completes version_id / revision ids after the project slug.
  objectified versions show my-api v<TAB> completes semver / revision ids / tag names after the project slug.

Linting
  Generated bash/zsh/fish snippets are written for portability; run shellcheck or fish --no-execute in CI when available.
`.trim();

export const docsTopicPlugins = `
PLUGINS

Status
  An oclif plugin ecosystem for Objectified is planned for post-MVP releases. This CLI currently ships core commands only.

Extensibility
  Future builds may expose objectified plugins:* commands for third-party commands alongside versioned API compatibility guarantees.
`.trim();

export const docsTopicTelemetry = `
TELEMETRY

Default posture
  The open-source CLI does not phone home by default. Any future telemetry would be opt-in, documented per release, and scoped to aggregate usage without secrets.

Verbose diagnostics
  Use --verbose or OBJECTIFIED_VERBOSE=1 for stderr diagnostics. OBJECTIFIED_DEBUG=1 may include stack traces for unexpected failures—avoid enabling in CI logs that are world-readable.
`.trim();
