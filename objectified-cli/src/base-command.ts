import os from "node:os";

import { Command, Flags } from "@oclif/core";
import { ExitError } from "@oclif/core/errors";
import type { CommandError } from "@oclif/core/interfaces";
import supportsColor from "supports-color";

import { describeActiveCredential, type ActiveCredential } from "./lib/active-credential.js";
import { readApiKeyFromFile } from "./lib/api-key-file.js";
import { createApiClient, type ApiAuthSnapshot, type ObjectifiedApi } from "./lib/client.js";
import {
  buildObjectifiedContext,
  type GlobalCliFlags,
  type ObjectifiedContext,
  resolveAllowColor,
} from "./lib/cli-context.js";
import { loadCliStoredAuth } from "./lib/credentials/store.js";
import { ObjectifiedCliError } from "./lib/errors.js";
import { EXIT_CODES } from "./lib/exit-codes.js";
import {
  ensureDefaultConfigFile,
  loadTomlConfigFile,
  resolveConfigFilePath,
  type ParsedTomlConfig,
} from "./lib/config.js";
import {
  cliFailureJsonEnvelope,
  formatAndReportCliFailure,
  resolveDebugStacks,
  resolveEffectiveExitCode,
} from "./lib/handle-error.js";
import { createCliOutput, localePrefersAsciiTable, type CliOutput } from "./lib/output.js";
import { normalizeCliArgv } from "./lib/normalize-argv.js";

export abstract class BaseCommand extends Command {
  static baseFlags = {
    "api-key": Flags.string({
      description:
        "API key for direct authentication (OBJECTIFIED_API_KEY); overrides config.toml api_key. Not persisted unless you run `auth login --api-key`.",
      helpGroup: "Auth",
      env: "OBJECTIFIED_API_KEY",
    }),
    "api-key-file": Flags.string({
      description: "Read API key from a file (single line; avoids shell history).",
      helpGroup: "Auth",
    }),
    "base-url": Flags.string({
      description: "Root REST API URL.",
      helpGroup: "Common",
    }),
    config: Flags.string({
      description:
        "Path to config file (default: XDG config dir / Objectified AppData on Windows — see `objectified config path`).",
      helpGroup: "Common",
    }),
    json: Flags.boolean({
      description:
        "Emit machine-readable JSON (OBJECTIFIED_JSON=1; auto-enabled when stdout is not a TTY).",
      allowNo: true,
      helpGroup: "Output",
    }),
    color: Flags.boolean({
      description:
        "Enable/disable ANSI colors (--no-color sets NO_COLOR; colors are off when stdout is not a TTY).",
      allowNo: true,
      helpGroup: "Output",
    }),
    profile: Flags.string({
      description:
        "Named credentials profile (OBJECTIFIED_PROFILE); falls back to default_profile in config.",
      helpGroup: "Common",
    }),
    tenant: Flags.string({
      description:
        "Tenant slug for this run only (overrides OBJECTIFIED_TENANT and config tenant_slug).",
      helpGroup: "Common",
      env: "OBJECTIFIED_TENANT",
    }),
    quiet: Flags.boolean({
      char: "q",
      description: "Suppress non-error stdout (spinners, banners, tips).",
      helpGroup: "Output",
    }),
    verbose: Flags.boolean({
      description: "Verbose logging on stderr (OBJECTIFIED_VERBOSE=1).",
      helpGroup: "Output",
    }),
  };

  /** Parsed flags including globals and command-specific options. */
  declare flags: GlobalCliFlags & Record<string, unknown>;

  private cliOutput?: CliOutput;

  /** Shared renderers: tables, JSON/YAML, spinners, stderr warnings (TTY / --json / --quiet aware). */
  protected get output(): CliOutput {
    this.cliOutput ??= createCliOutput({
      json: this.context.json,
      color: this.context.color,
      quiet: Boolean(this.flags.quiet),
      stdoutIsTTY: process.stdout.isTTY,
      stderrIsTTY: process.stderr.isTTY,
      langAscii: localePrefersAsciiTable(process.env),
      stdoutWrite: (chunk) => process.stdout.write(chunk),
      stderrWrite: (chunk) => process.stderr.write(chunk),
    });
    return this.cliOutput;
  }

  /** Resolved API/client context (URLs/slugs: flag > env > profile > [default]; API key also reads api_key from config before stored credentials). */
  context!: ObjectifiedContext;

  /** argv after global promotion + auth login sentinel normalization (matches oclif input). */
  protected normalizedArgv!: string[];

  /** API key from flags/env/file only (before OS keychain merge). */
  protected transientApiKey!: string | undefined;

  /** Effective credential classification for `auth status` and UX. */
  protected activeCredential!: ActiveCredential;

  /** Parsed config document after loading `config.toml`. */
  protected configDoc!: ParsedTomlConfig;

  /** True when --verbose or OBJECTIFIED_VERBOSE=1. */
  protected verboseEffective!: boolean;

  /** Config file path after flag/env/default resolution. */
  protected resolvedConfigPath!: string;

  /** Command arguments after parse (subcommands read typed fields from here). */
  protected commandArgs!: Record<string, unknown>;

  protected parsedGlobalFlags?: GlobalCliFlags;

  /** Mutable snapshot passed to the REST wrapper (401 hook may refresh credentials). */
  protected readonly apiAuth: ApiAuthSnapshot = {};

  protected api!: ObjectifiedApi;

  async init(): Promise<void> {
    await super.init();
    const Cmd = this.constructor as typeof Command;
    const parsed = await this.parse(Cmd);
    const parsedFlags = parsed.flags as Record<string, unknown>;
    // Keep camelCase fallback for compatibility while normalize-argv continues accepting legacy aliases.
    const apiKeyFlag =
      (parsedFlags["api-key"] as string | undefined) ?? (parsedFlags.apiKey as string | undefined);
    const apiKeyFileFlag =
      (parsedFlags["api-key-file"] as string | undefined) ??
      (parsedFlags.apiKeyFile as string | undefined);

    let apiKey = apiKeyFlag;
    if (
      (apiKey === undefined || apiKey === "") &&
      apiKeyFileFlag !== undefined &&
      apiKeyFileFlag.trim() !== ""
    ) {
      apiKey = readApiKeyFromFile(apiKeyFileFlag.trim());
    }

    const globalPart: GlobalCliFlags = {
      apiKey,
      apiKeyFile: apiKeyFileFlag,
      baseUrl:
        (parsedFlags["base-url"] as string | undefined) ??
        (parsedFlags.baseUrl as string | undefined),
      config: parsedFlags.config as string | undefined,
      json: parsedFlags.json as boolean | undefined,
      color: parsedFlags.color as boolean | undefined,
      profile: parsedFlags.profile as string | undefined,
      tenant: parsedFlags.tenant as string | undefined,
      quiet: parsedFlags.quiet as boolean | undefined,
      verbose: parsedFlags.verbose as boolean | undefined,
    };
    this.parsedGlobalFlags = globalPart;
    this.commandArgs = parsed.args as Record<string, unknown>;
    this.normalizedArgv = normalizeCliArgv(process.argv.slice(2));

    this.resolvedConfigPath = resolveConfigFilePath(globalPart.config, process.env, os.homedir);
    await ensureDefaultConfigFile(this.resolvedConfigPath);
    this.configDoc = loadTomlConfigFile(this.resolvedConfigPath);

    const built = buildObjectifiedContext({
      flags: globalPart,
      env: process.env,
      stdoutIsTTY: process.stdout.isTTY,
      supportsColorStdout: typeof supportsColor.stdout === "object",
      configDoc: this.configDoc,
      configPath: this.resolvedConfigPath,
    });

    this.context = built.context;
    this.verboseEffective = built.verboseEffective;
    this.flags = {
      ...parsed.flags,
      verboseEffective: built.verboseEffective,
    } as BaseCommand["flags"];
    this.transientApiKey = this.context.apiKey;

    let storedApiKey: string | undefined;
    let storedBearer: string | undefined;
    try {
      const stored = await loadCliStoredAuth(this.context.profile);
      if (stored?.kind === "api_key") storedApiKey = stored.apiKey;
      else if (stored?.kind === "oauth") storedBearer = stored.accessToken;
    } catch (err: unknown) {
      if (this.verboseEffective) {
        const msg = err instanceof Error ? err.message : String(err);
        process.stderr.write(`objectified: could not read CLI credentials: ${msg}\n`);
      }
    }

    this.apiAuth.apiKey = this.context.apiKey ?? storedApiKey;
    this.apiAuth.bearer = this.context.accessToken ?? storedBearer;
    if (this.apiAuth.apiKey) this.apiAuth.bearer = undefined;

    this.activeCredential = describeActiveCredential({
      argv: this.normalizedArgv,
      env: process.env,
      transientApiKey: this.transientApiKey,
      apiKeyFromConfig: Boolean(this.context.apiKeyFromConfig),
      effectiveApiKey: this.apiAuth.apiKey,
      effectiveBearer: this.apiAuth.bearer,
    });

    this.api = createApiClient({
      baseUrl: this.context.baseUrl,
      auth: this.apiAuth,
      verbose: this.verboseEffective,
      stderrWrite: (line) => process.stderr.write(`${line}\n`),
    });
  }

  /** Throws exit code 3 when no API key or bearer is available (#3195). */
  protected ensureAuthenticated(): void {
    if (!this.apiAuth.apiKey && !this.apiAuth.bearer) {
      throw new ObjectifiedCliError({
        message: "No API key or OAuth token available for this command.",
        exitCode: EXIT_CODES.NOT_AUTHENTICATED,
        title: "Not authenticated",
        hint: "Run `objectified auth login`, set OBJECTIFIED_API_KEY, add api_key under [default] or [profile] in config.toml, or pass --api-key / --api-key-file.",
      });
    }
  }

  protected override catch(err: CommandError): Promise<void> {
    if (this.jsonEnabled()) {
      // `api` is assigned late in `init()`; failures before `createApiClient` must not crash JSON rendering.
      // eslint-disable-next-line @typescript-eslint/no-unnecessary-condition -- optional when init aborted early
      this.logJson(cliFailureJsonEnvelope(err, this.api?.lastRequestId));
      return Promise.reject(new ExitError(resolveEffectiveExitCode(err)));
    }

    const debugStacks = resolveDebugStacks(process.argv, process.env);
    const colorFromContext = (this as { context?: ObjectifiedContext }).context?.color;
    const color =
      colorFromContext ??
      resolveAllowColor(
        this.parsedGlobalFlags?.color,
        process.env,
        process.stderr.isTTY,
        typeof supportsColor.stderr === "object",
      );
    const code = formatAndReportCliFailure(err, { debugStacks, color });
    return Promise.reject(new ExitError(code));
  }
}
