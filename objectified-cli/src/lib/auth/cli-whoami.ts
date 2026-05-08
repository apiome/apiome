import type { ActiveCredentialKind } from "../active-credential.js";
import type { ApiAuthSnapshot } from "../client.js";
import { httpStatusToCliError, ObjectifiedCliError } from "../errors.js";
import { EXIT_CODES } from "../exit-codes.js";
import {
  CLI_WHOAMI_PATH,
  displayIdentityFromAccessToken,
  exchangeCliRefreshToken,
} from "./cli-oauth.js";

function trimTrailingSlash(url: string): string {
  return url.replace(/\/+$/, "");
}

/** Best-effort JWT `exp` → ISO UTC (no signature verification). */
export function accessTokenExpiresAtIsoUtc(accessToken: string): string | null {
  const parts = accessToken.split(".");
  if (parts.length !== 3) return null;
  try {
    const payload = parts[1];
    if (payload === undefined) return null;
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    const pad = normalized.length % 4 === 0 ? "" : "=".repeat(4 - (normalized.length % 4));
    const json = Buffer.from(normalized + pad, "base64").toString("utf8");
    const o = JSON.parse(json) as Record<string, unknown>;
    const exp = o.exp;
    if (typeof exp === "number" && Number.isFinite(exp)) {
      return new Date(exp * 1000).toISOString();
    }
  } catch {
    /* ignore */
  }
  return null;
}

export type CliWhoamiApiModel = {
  tenant: { slug: string; name?: string | null } | null;
  user: { id: string | null; email: string | null };
  plan: string | null;
  auth: {
    type: string | null;
    expires_at: string | null;
    refresh_valid: boolean | null;
  };
};

export function parseCliWhoamiBody(data: unknown): CliWhoamiApiModel {
  const empty: CliWhoamiApiModel = {
    tenant: null,
    user: { id: null, email: null },
    plan: null,
    auth: { type: null, expires_at: null, refresh_valid: null },
  };
  if (!data || typeof data !== "object") return empty;
  const o = data as Record<string, unknown>;

  let tenant: CliWhoamiApiModel["tenant"] = null;
  const tr = o.tenant;
  if (tr && typeof tr === "object") {
    const t = tr as Record<string, unknown>;
    if (typeof t.slug === "string" && t.slug.trim() !== "") {
      const name =
        t.name === null
          ? null
          : typeof t.name === "string"
            ? t.name
            : t.name === undefined
              ? undefined
              : null;
      tenant = { slug: t.slug.trim(), name };
    }
  }

  let userId: string | null = null;
  let userEmail: string | null = null;
  const ur = o.user;
  if (ur && typeof ur === "object") {
    const u = ur as Record<string, unknown>;
    if (typeof u.id === "string") userId = u.id;
    if (typeof u.email === "string") userEmail = u.email;
  }

  const plan = typeof o.plan === "string" ? o.plan : null;

  let authType: string | null = null;
  let expiresAt: string | null = null;
  let refreshValid: boolean | null = null;
  const ar = o.auth;
  if (ar && typeof ar === "object") {
    const a = ar as Record<string, unknown>;
    if (typeof a.type === "string") authType = a.type;
    if (typeof a.expires_at === "string") expiresAt = a.expires_at;
    else if (a.expires_at === null) expiresAt = null;
    if (typeof a.refresh_valid === "boolean") refreshValid = a.refresh_valid;
  }

  return {
    tenant,
    user: { id: userId, email: userEmail },
    plan,
    auth: { type: authType, expires_at: expiresAt, refresh_valid: refreshValid },
  };
}

export type AuthStatusJsonAuthType = "oauth" | "api_key";

export function authTypeForJson(kind: ActiveCredentialKind): AuthStatusJsonAuthType {
  if (kind === "oauth_keychain" || kind === "bearer_env") return "oauth";
  return "api_key";
}

export type BuildAuthStatusJsonOpts = {
  profile: string;
  baseUrl: string;
  profileTenantSlug: string | undefined;
  model: CliWhoamiApiModel;
  activeCredentialKind: ActiveCredentialKind;
  bearer?: string;
};

function toIsoUtcOrNull(iso: string | null | undefined): string | null {
  if (iso === null || iso === undefined || iso === "") return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  return new Date(t).toISOString();
}

/** Stable `objectified auth status --json` document (#3196). Keys are sorted at emit time via `output.json`. */
export function buildAuthStatusStableJson(opts: BuildAuthStatusJsonOpts): Record<string, unknown> {
  const jsonAuthType = authTypeForJson(opts.activeCredentialKind);
  const jwtExpires = opts.bearer ? accessTokenExpiresAtIsoUtc(opts.bearer) : null;
  const rawExpires =
    jsonAuthType === "oauth"
      ? opts.model.auth.expires_at && opts.model.auth.expires_at !== ""
        ? opts.model.auth.expires_at
        : jwtExpires
      : null;
  const expiresAt = rawExpires !== null && rawExpires !== "" ? toIsoUtcOrNull(rawExpires) : null;

  const mergedSlug = opts.model.tenant?.slug ?? opts.profileTenantSlug;
  const tenant =
    mergedSlug !== undefined && mergedSlug !== ""
      ? {
          slug: mergedSlug,
          name: opts.model.tenant?.name ?? null,
        }
      : null;

  const email =
    opts.model.user.email ??
    (opts.bearer ? (displayIdentityFromAccessToken(opts.bearer) ?? null) : null);

  const user = {
    id: opts.model.user.id,
    email,
  };

  const auth: Record<string, unknown> = { type: jsonAuthType };
  if (jsonAuthType === "oauth") {
    auth.expires_at = expiresAt;
  }

  return {
    profile: opts.profile,
    base_url: opts.baseUrl,
    tenant,
    user,
    auth,
    plan: opts.model.plan,
  };
}

export type FormatAuthStatusHumanOpts = {
  profile: string;
  baseUrl: string;
  profileTenantSlug: string | undefined;
  model: CliWhoamiApiModel;
  activeCredentialKind: ActiveCredentialKind;
  bearer?: string;
  /** Fixed clock for tests. */
  now?: Date;
};

function titleCasePlan(plan: string): string {
  if (plan.trim() === "") return plan;
  return plan
    .split(/[\s_-]+/)
    .map((w) => {
      if (w.length === 0) return w;
      const first = w[0];
      if (first === undefined) return w;
      return first.toUpperCase() + w.slice(1).toLowerCase();
    })
    .join(" ");
}

function formatRelativeExpiry(isoUtc: string, now: Date): string {
  const t = Date.parse(isoUtc);
  if (Number.isNaN(t)) return "unknown";
  const ms = t - now.getTime();
  if (ms <= 0) return "expired";
  const totalMins = Math.floor(ms / 60_000);
  const hours = Math.floor(totalMins / 60);
  const mins = totalMins % 60;
  const days = Math.floor(hours / 24);
  if (days > 0) return `in ${String(days)}d ${String(hours % 24)}h`;
  if (hours > 0) return `in ${String(hours)}h ${String(mins)}m`;
  return `in ${String(Math.max(1, mins))}m`;
}

function humanAuthLabel(kind: ActiveCredentialKind): string {
  switch (kind) {
    case "oauth_keychain":
      return "OAuth (PKCE)";
    case "bearer_env":
      return "OAuth (env bearer)";
    case "api_key_flag":
    case "api_key_env":
    case "api_key_file":
    case "api_key_keychain":
      return "API key";
    default:
      return "unknown";
  }
}

function padLine(label: string, value: string): string {
  const withColon = `${label}:`;
  return `  ${withColon.padEnd(13)} ${value}`;
}

export function formatAuthStatusHumanLines(opts: FormatAuthStatusHumanOpts): string[] {
  const now = opts.now ?? new Date();
  const jsonKind = authTypeForJson(opts.activeCredentialKind);
  const jwtExpires = opts.bearer ? accessTokenExpiresAtIsoUtc(opts.bearer) : null;
  const expiresIso =
    jsonKind === "oauth"
      ? opts.model.auth.expires_at && opts.model.auth.expires_at !== ""
        ? opts.model.auth.expires_at
        : jwtExpires
      : null;

  const slug = opts.model.tenant?.slug ?? opts.profileTenantSlug;
  const name = opts.model.tenant?.name;
  let tenantHuman: string;
  if (slug !== undefined && slug !== "") {
    tenantHuman = name !== undefined && name !== null && name !== "" ? `${slug} (${name})` : slug;
  } else {
    tenantHuman = "(not set)";
  }

  const userHuman =
    opts.model.user.email ??
    (opts.bearer ? displayIdentityFromAccessToken(opts.bearer) : undefined) ??
    "(unknown)";

  const lines: string[] = [
    padLine("Profile", opts.profile),
    padLine("Base URL", opts.baseUrl),
    padLine("Tenant", tenantHuman),
    padLine("User", userHuman),
    padLine("Auth type", humanAuthLabel(opts.activeCredentialKind)),
  ];

  if (jsonKind === "oauth") {
    const expLine =
      expiresIso !== null && expiresIso !== "" ? formatRelativeExpiry(expiresIso, now) : "unknown";
    let refreshNote = "";
    if (
      opts.model.auth.refresh_valid === true ||
      (opts.model.auth.refresh_valid === null && opts.activeCredentialKind === "oauth_keychain")
    ) {
      refreshNote = " (refresh token valid)";
    }
    lines.push(padLine("Expires", `${expLine}${refreshNote}`));
  } else {
    lines.push(padLine("Expires", "-"));
  }

  const planHuman =
    opts.model.plan !== null && opts.model.plan !== "" ? titleCasePlan(opts.model.plan) : "-";
  lines.push(padLine("Plan", planHuman));

  return lines;
}

export type FetchCliWhoamiOptions = {
  baseUrl: string;
  auth: ApiAuthSnapshot;
  activeCredentialKind: ActiveCredentialKind;
  oauthRefresh?: {
    refreshToken: string;
    onRotated: (accessToken: string, refreshToken: string) => Promise<void>;
  };
  fetchImpl?: typeof fetch;
};

export async function fetchCliWhoami(opts: FetchCliWhoamiOptions): Promise<CliWhoamiApiModel> {
  const fetchFn = opts.fetchImpl ?? globalThis.fetch;
  const url = `${trimTrailingSlash(opts.baseUrl)}${CLI_WHOAMI_PATH}`;

  const getOnce = async (): Promise<Response> => {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (opts.auth.apiKey) {
      headers["X-API-Key"] = opts.auth.apiKey;
    } else if (opts.auth.bearer) {
      headers.Authorization = `Bearer ${opts.auth.bearer}`;
    }
    return fetchFn(url, { method: "GET", headers });
  };

  let res = await getOnce();

  if (res.status === 401 && opts.oauthRefresh) {
    const tokens = await exchangeCliRefreshToken({
      apiBaseUrl: opts.baseUrl,
      refreshToken: opts.oauthRefresh.refreshToken,
      fetchImpl: opts.fetchImpl,
    });
    opts.auth.apiKey = undefined;
    opts.auth.bearer = tokens.access_token;
    await opts.oauthRefresh.onRotated(tokens.access_token, tokens.refresh_token);
    res = await getOnce();
  }

  const rid = res.headers.get("x-request-id") ?? res.headers.get("X-Request-Id") ?? undefined;
  const text = await res.text();

  if (!res.ok) {
    throw httpStatusToCliError(res.status, text.slice(0, 800), {
      requestId: rid,
      credentialsWereSent: Boolean(opts.auth.apiKey || opts.auth.bearer),
    });
  }

  let parsed: unknown;
  try {
    parsed = text.trim() === "" ? null : (JSON.parse(text) as unknown);
  } catch {
    throw new ObjectifiedCliError({
      message: "Whoami response was not valid JSON.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "Upgrade the CLI or verify `--base-url` points at a compatible API.",
      requestId: rid,
    });
  }

  return parseCliWhoamiBody(parsed);
}
