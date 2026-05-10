import { CliError } from "./errors.js";
import type { ParsedTomlConfig } from "./config.js";
import { DEFAULT_BASE_URL } from "./constants.js";

/** Parsed global flags (oclif uses camelCase keys). */
export type GlobalCliFlags = {
  apiKey?: string;
  apiKeyFile?: string;
  baseUrl?: string;
  config?: string;
  json?: boolean;
  color?: boolean;
  profile?: string;
  /** Per-invocation tenant override (`--tenant` / OBJECTIFIED_TENANT). */
  tenant?: string;
  quiet?: boolean;
  verbose?: boolean;
  /** Set by BaseCommand after parsing (includes OBJECTIFIED_VERBOSE=1). */
  verboseEffective?: boolean;
};

export type ObjectifiedContext = {
  baseUrl: string;
  profile: string;
  apiKey: string | undefined;
  /** True when apiKey came from config.toml api_key (not flag/env). */
  apiKeyFromConfig?: boolean;
  /** Bearer token when set (env-only until login stores credentials elsewhere). */
  accessToken: string | undefined;
  tenantSlug: string | undefined;
  json: boolean;
  color: boolean;
};

function firstNonEmpty(...vals: (string | undefined)[]): string | undefined {
  for (const v of vals) {
    if (v !== undefined && v !== "") return v;
  }
  return undefined;
}

function envTruthy(env: NodeJS.ProcessEnv, key: string): boolean {
  const v = env[key];
  return v === "1" || v === "true" || v === "yes";
}

export function listAvailableProfileNames(doc: ParsedTomlConfig): string[] {
  const names = new Set<string>(["default"]);
  for (const k of Object.keys(doc.profiles)) names.add(k);
  return [...names].sort((a, b) => a.localeCompare(b));
}

export function assertProfileExists(doc: ParsedTomlConfig, profileName: string): void {
  if (profileName === "default") return;
  if (doc.profiles[profileName] !== undefined) return;
  const available = listAvailableProfileNames(doc);
  throw new CliError(
    `Profile '${profileName}' not found. Available: ${available.join(", ")}. Run \`objectified config set …\` to add one.`,
    11,
  );
}

/** Flag → env → `default_profile` in file → literal `"default"`. */
export function resolveEffectiveProfile(
  flag: string | undefined,
  env: NodeJS.ProcessEnv,
  doc: ParsedTomlConfig,
): string {
  return firstNonEmpty(flag, env.OBJECTIFIED_PROFILE, doc.defaultProfile) ?? "default";
}

/** Profile-specific values overlay `[default]` (issue #3187 / #3188). */
export function configLayerForProfile(
  doc: ParsedTomlConfig,
  profileName: string,
): { baseUrl?: string; tenantSlug?: string; apiKey?: string } {
  const prof = doc.profiles[profileName];
  return {
    baseUrl: firstNonEmpty(prof?.baseUrl, doc.default.baseUrl),
    tenantSlug: firstNonEmpty(prof?.tenantSlug, doc.default.tenantSlug),
    apiKey: firstNonEmpty(prof?.apiKey, doc.default.apiKey),
  };
}

export function resolveBaseUrl(
  flag: string | undefined,
  env: NodeJS.ProcessEnv,
  cfg: { baseUrl?: string },
): string {
  return firstNonEmpty(flag, env.OBJECTIFIED_BASE_URL, cfg.baseUrl) ?? DEFAULT_BASE_URL;
}

/** Profile-layer base URL from config only (no env); used for auth revoke across profiles. */
export function resolveProfileConfigBaseUrl(doc: ParsedTomlConfig, profileName: string): string {
  const layer = configLayerForProfile(doc, profileName);
  return layer.baseUrl ?? DEFAULT_BASE_URL;
}

/** Flag → OBJECTIFIED_API_KEY → optional api_key from profile layer ([profile] over [default]). */
export function resolveApiKey(
  flag: string | undefined,
  env: NodeJS.ProcessEnv,
  cfg?: { apiKey?: string },
): string | undefined {
  return firstNonEmpty(flag, env.OBJECTIFIED_API_KEY, cfg?.apiKey);
}

export function resolveAccessToken(env: NodeJS.ProcessEnv): string | undefined {
  return firstNonEmpty(env.OBJECTIFIED_ACCESS_TOKEN);
}

export function resolveTenantSlug(
  flag: string | undefined,
  env: NodeJS.ProcessEnv,
  cfg: { tenantSlug?: string },
): string | undefined {
  return firstNonEmpty(flag, env.OBJECTIFIED_TENANT, cfg.tenantSlug);
}

export function resolveJson(
  flag: boolean | undefined,
  env: NodeJS.ProcessEnv,
  stdoutIsTTY: boolean,
): boolean {
  if (flag === true) return true;
  if (flag === false) return false;
  if (envTruthy(env, "OBJECTIFIED_JSON")) return true;
  return !stdoutIsTTY;
}

export function resolveVerbose(flag: boolean | undefined, env: NodeJS.ProcessEnv): boolean {
  if (flag === true) return true;
  if (flag === false) return false;
  return envTruthy(env, "OBJECTIFIED_VERBOSE");
}

export function resolveAllowColor(
  colorFlag: boolean | undefined,
  env: NodeJS.ProcessEnv,
  stdoutIsTTY: boolean,
  supportsStdout: boolean,
): boolean {
  if (colorFlag === false) return false;
  if (colorFlag === true) return true;
  if (env.NO_COLOR !== undefined && env.NO_COLOR !== "") return false;
  return supportsStdout && stdoutIsTTY;
}

export function buildObjectifiedContext(opts: {
  flags: GlobalCliFlags;
  env: NodeJS.ProcessEnv;
  stdoutIsTTY: boolean;
  supportsColorStdout: boolean;
  configDoc: ParsedTomlConfig;
  configPath: string;
}): { context: ObjectifiedContext; verboseEffective: boolean; configPath: string } {
  const profile = resolveEffectiveProfile(opts.flags.profile, opts.env, opts.configDoc);
  assertProfileExists(opts.configDoc, profile);

  const cfgLayer = configLayerForProfile(opts.configDoc, profile);

  const baseUrl = resolveBaseUrl(opts.flags.baseUrl, opts.env, cfgLayer);
  const fromFlagOrEnv = firstNonEmpty(opts.flags.apiKey, opts.env.OBJECTIFIED_API_KEY);
  const apiKey = resolveApiKey(opts.flags.apiKey, opts.env, cfgLayer);
  const apiKeyFromConfig =
    (fromFlagOrEnv === undefined || fromFlagOrEnv === "") &&
    cfgLayer.apiKey !== undefined &&
    cfgLayer.apiKey !== "";
  const accessToken = resolveAccessToken(opts.env);
  const tenantSlug = resolveTenantSlug(opts.flags.tenant, opts.env, cfgLayer);

  const json = resolveJson(opts.flags.json, opts.env, opts.stdoutIsTTY);
  const color = resolveAllowColor(
    opts.flags.color,
    opts.env,
    opts.stdoutIsTTY,
    opts.supportsColorStdout,
  );

  const verboseEffective = resolveVerbose(opts.flags.verbose, opts.env);

  return {
    context: {
      baseUrl,
      profile,
      apiKey,
      ...(apiKeyFromConfig ? { apiKeyFromConfig: true } : {}),
      accessToken,
      tenantSlug,
      json,
      color,
    },
    verboseEffective,
    configPath: opts.configPath,
  };
}
