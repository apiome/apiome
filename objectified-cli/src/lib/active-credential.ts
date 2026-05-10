import { API_KEY_PROMPT_SENTINEL } from "./constants.js";

export type ActiveCredentialKind =
  | "none"
  | "api_key_flag"
  | "api_key_env"
  | "api_key_file"
  | "api_key_config"
  | "api_key_keychain"
  | "oauth_keychain"
  | "bearer_env";

export type ActiveCredential = {
  kind: ActiveCredentialKind;
  /** True when an API request would send credentials (API key or bearer). */
  authenticated: boolean;
};

function readExplicitApiKeyFromArgv(argv: string[]): string | undefined {
  for (let i = 0; i < argv.length; i++) {
    const t = argv[i];
    if (t?.startsWith("--api-key=")) {
      const v = t.slice("--api-key=".length);
      if (v !== "" && v !== API_KEY_PROMPT_SENTINEL) return v;
      continue;
    }
    if (t === "--api-key") {
      const next = argv[i + 1];
      if (next !== undefined && !next.startsWith("-") && next !== API_KEY_PROMPT_SENTINEL) {
        return next;
      }
    }
  }
  return undefined;
}

function argvReferencesApiKeyFile(argv: string[]): boolean {
  return argv.some((t) => t === "--api-key-file" || t.startsWith("--api-key-file="));
}

/** Describes how the CLI is authenticated after BaseCommand.init(). */
export function describeActiveCredential(opts: {
  argv: string[];
  env: NodeJS.ProcessEnv;
  /** Transient API key from flags/env/file/config before keychain merge (undefined if none). */
  transientApiKey?: string;
  /** True when transient API key was read from config.toml api_key. */
  apiKeyFromConfig?: boolean;
  effectiveApiKey?: string;
  effectiveBearer?: string;
}): ActiveCredential {
  const { argv, env, transientApiKey, apiKeyFromConfig, effectiveApiKey, effectiveBearer } = opts;

  if (effectiveApiKey) {
    const explicitFlag = readExplicitApiKeyFromArgv(argv);
    if (explicitFlag !== undefined && explicitFlag === effectiveApiKey) {
      return { kind: "api_key_flag", authenticated: true };
    }
    if (
      transientApiKey &&
      env.OBJECTIFIED_API_KEY &&
      env.OBJECTIFIED_API_KEY === transientApiKey &&
      transientApiKey === effectiveApiKey
    ) {
      return { kind: "api_key_env", authenticated: true };
    }
    if (transientApiKey && argvReferencesApiKeyFile(argv) && transientApiKey === effectiveApiKey) {
      return { kind: "api_key_file", authenticated: true };
    }
    if (
      apiKeyFromConfig &&
      transientApiKey &&
      transientApiKey === effectiveApiKey
    ) {
      return { kind: "api_key_config", authenticated: true };
    }
    return { kind: "api_key_keychain", authenticated: true };
  }

  if (effectiveBearer) {
    if (env.OBJECTIFIED_ACCESS_TOKEN && env.OBJECTIFIED_ACCESS_TOKEN === effectiveBearer) {
      return { kind: "bearer_env", authenticated: true };
    }
    return { kind: "oauth_keychain", authenticated: true };
  }

  return { kind: "none", authenticated: false };
}

export function credentialKindLabel(kind: ActiveCredentialKind): string {
  switch (kind) {
    case "api_key_flag":
      return "API key (--api-key)";
    case "api_key_env":
      return "API key (OBJECTIFIED_API_KEY)";
    case "api_key_file":
      return "API key (--api-key-file)";
    case "api_key_config":
      return "API key (config.toml)";
    case "api_key_keychain":
      return "API key (stored for profile)";
    case "oauth_keychain":
      return "OAuth token (stored for profile)";
    case "bearer_env":
      return "Bearer token (OBJECTIFIED_ACCESS_TOKEN)";
    default:
      return "none";
  }
}
