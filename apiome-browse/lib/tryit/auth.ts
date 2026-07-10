/**
 * Try It auth helpers — SIM-3.6 (#4452).
 *
 * Scheme-aware credential inputs for the Try It panel: read `components.securitySchemes` and the
 * operation's (or document's) `security` requirements, render bearer / apiKey / basic helpers, and
 * apply the filled values to the composed request. Values live in `sessionStorage` only — never
 * localStorage, never server-side, never posted to Apiome's own APIs beyond the SIM-3.2 relay
 * envelope the user already confirmed for custom hosts.
 *
 * OAuth2 / OpenID Connect flows are explicitly out of scope (future work); those schemes are
 * surfaced as unsupported so the panel does not pretend to handle them.
 *
 * Framework-free (sessionStorage is injectable) so it is unit-testable under the browse Vitest
 * setup. The React panel (`AuthHelpers.tsx`) is a thin view over these helpers.
 */

import { resolveRef } from './operation';
import {
  placeholderForHeader,
  placeholderForQueryParam,
  type SecretPlaceholderMap,
} from './secrets';

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Where an apiKey scheme places its credential. */
export type ApiKeyLocation = 'header' | 'query' | 'cookie';

/** A security scheme the Try It panel can collect credentials for. */
export type SupportedAuthScheme =
  | {
      name: string;
      kind: 'bearer';
      /** Optional `bearerFormat` hint from the spec (e.g. `JWT`). */
      bearerFormat?: string;
      description?: string;
    }
  | {
      name: string;
      kind: 'apiKey';
      /** Parameter / header / cookie name declared by the scheme. */
      paramName: string;
      location: ApiKeyLocation;
      description?: string;
    }
  | {
      name: string;
      kind: 'basic';
      description?: string;
    };

/** A scheme declared in the spec that the panel cannot collect credentials for. */
export interface UnsupportedAuthScheme {
  name: string;
  /** Spec `type` (e.g. `oauth2`, `openIdConnect`, `http`). */
  type: string;
  /** Extra detail when useful (e.g. `http` scheme name `digest`). */
  detail?: string;
  description?: string;
}

/** One OR-alternative from a Security Requirement Object list. */
export interface AuthRequirementAlternative {
  /** Scheme names that must all be satisfied for this alternative (AND). */
  schemes: string[];
}

/** Resolved security for one operation. */
export interface OperationAuth {
  /** Supported schemes referenced by the effective security requirements. */
  schemes: SupportedAuthScheme[];
  /** Unsupported schemes referenced by the effective security requirements. */
  unsupported: UnsupportedAuthScheme[];
  /**
   * OR-list of AND-groups. Empty when the operation declares no security (or an empty array
   * overriding document-level security). A single empty alternative means security is optional.
   */
  alternatives: AuthRequirementAlternative[];
  /** True when at least one supported scheme applies to this operation. */
  applies: boolean;
}

/** Session-stored credential values keyed by scheme name. */
export interface AuthCredentialValues {
  /** Bearer token (without the `Bearer ` prefix). */
  bearerToken?: string;
  /** apiKey value. */
  apiKey?: string;
  /** Basic-auth username. */
  username?: string;
  /** Basic-auth password. */
  password?: string;
}

/** Map of scheme name → credential fields. */
export type AuthCredentialsMap = Record<string, AuthCredentialValues>;

/** Minimal Storage surface used by the session helpers (browser `sessionStorage`). */
export interface AuthStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

/** Prefix for all Try It auth keys in sessionStorage. */
export const AUTH_STORAGE_PREFIX = 'apiome.tryit.auth.';

/**
 * Encode `username:password` as Base64 for an `Authorization: Basic …` header.
 *
 * Uses UTF-8 bytes so non-ASCII credentials round-trip correctly in both the browser (`btoa`)
 * and Node (Vitest / `Buffer`).
 *
 * @param username - Basic-auth username.
 * @param password - Basic-auth password.
 */
export function encodeBasicCredentials(username: string, password: string): string {
  const raw = `${username}:${password}`;
  const bytes = new TextEncoder().encode(raw);
  if (typeof btoa === 'function') {
    let binary = '';
    for (const byte of bytes) binary += String.fromCharCode(byte);
    return btoa(binary);
  }
  return Buffer.from(bytes).toString('base64');
}

/** Parse one `components.securitySchemes` entry into a supported or unsupported scheme. */
function parseScheme(
  name: string,
  node: Record<string, unknown>
): { supported?: SupportedAuthScheme; unsupported?: UnsupportedAuthScheme } {
  const type = typeof node.type === 'string' ? node.type : '';
  const description = typeof node.description === 'string' ? node.description : undefined;

  if (type === 'http') {
    const scheme = typeof node.scheme === 'string' ? node.scheme.toLowerCase() : '';
    if (scheme === 'bearer') {
      return {
        supported: {
          name,
          kind: 'bearer',
          bearerFormat: typeof node.bearerFormat === 'string' ? node.bearerFormat : undefined,
          description,
        },
      };
    }
    if (scheme === 'basic') {
      return { supported: { name, kind: 'basic', description } };
    }
    return {
      unsupported: { name, type: 'http', detail: scheme || undefined, description },
    };
  }

  if (type === 'apiKey') {
    const paramName = typeof node.name === 'string' ? node.name : '';
    const location = typeof node.in === 'string' ? node.in : '';
    if (
      paramName &&
      (location === 'header' || location === 'query' || location === 'cookie')
    ) {
      return {
        supported: {
          name,
          kind: 'apiKey',
          paramName,
          location,
          description,
        },
      };
    }
    return {
      unsupported: {
        name,
        type: 'apiKey',
        detail: location || undefined,
        description,
      },
    };
  }

  if (type === 'oauth2' || type === 'openIdConnect' || type === 'mutualTLS') {
    return { unsupported: { name, type, description } };
  }

  if (type) {
    return { unsupported: { name, type, description } };
  }
  return {};
}

/**
 * Extract every security scheme declared on the document.
 *
 * @param spec - The parsed OpenAPI document.
 * @returns Supported and unsupported schemes from `components.securitySchemes`.
 */
export function extractSecuritySchemes(spec: unknown): {
  supported: SupportedAuthScheme[];
  unsupported: UnsupportedAuthScheme[];
} {
  const supported: SupportedAuthScheme[] = [];
  const unsupported: UnsupportedAuthScheme[] = [];
  if (!isObject(spec) || !isObject(spec.components)) {
    return { supported, unsupported };
  }
  const schemesNode = spec.components.securitySchemes;
  if (!isObject(schemesNode)) return { supported, unsupported };

  for (const [name, raw] of Object.entries(schemesNode)) {
    const resolved = resolveRef(spec, raw);
    if (!resolved) continue;
    const parsed = parseScheme(name, resolved);
    if (parsed.supported) supported.push(parsed.supported);
    if (parsed.unsupported) unsupported.push(parsed.unsupported);
  }
  return { supported, unsupported };
}

/**
 * Parse a Security Requirement Object list into OR-alternatives of AND-grouped scheme names.
 *
 * @param security - The `security` array from the operation or document, or undefined.
 * @returns Alternatives; `null` when `security` is absent (caller should fall back).
 */
export function parseSecurityRequirements(
  security: unknown
): AuthRequirementAlternative[] | null {
  if (security === undefined) return null;
  if (!Array.isArray(security)) return [];
  return security.map((entry) => {
    if (!isObject(entry)) return { schemes: [] };
    return { schemes: Object.keys(entry) };
  });
}

/**
 * Resolve the security schemes that apply to one operation.
 *
 * Uses the operation's `security` when present (including an empty array that clears document
 * security); otherwise falls back to the document-level `security`. Only schemes referenced by
 * the effective requirements are returned.
 *
 * @param spec - The parsed OpenAPI document.
 * @param method - HTTP method of the operation (any case).
 * @param path - The templated path key, e.g. `/pets/{petId}`.
 */
export function resolveOperationAuth(
  spec: unknown,
  method: string,
  path: string
): OperationAuth {
  const empty: OperationAuth = {
    schemes: [],
    unsupported: [],
    alternatives: [],
    applies: false,
  };
  if (!isObject(spec) || !isObject(spec.paths)) return empty;

  const pathItem = resolveRef(spec, spec.paths[path]);
  if (!pathItem) return empty;
  const op = resolveRef(spec, pathItem[method.toLowerCase()]);
  if (!op) return empty;

  const opSecurity = parseSecurityRequirements(op.security);
  const docSecurity = parseSecurityRequirements(spec.security);
  const alternatives = opSecurity ?? docSecurity ?? [];

  // Empty array = no auth required. A lone empty alternative = optional (still no required schemes).
  const requiredNames = new Set<string>();
  for (const alt of alternatives) {
    for (const name of alt.schemes) requiredNames.add(name);
  }
  if (requiredNames.size === 0) {
    return { ...empty, alternatives };
  }

  const { supported: allSupported, unsupported: allUnsupported } = extractSecuritySchemes(spec);
  const schemes = allSupported.filter((s) => requiredNames.has(s.name));
  const unsupported = allUnsupported.filter((s) => requiredNames.has(s.name));
  // Schemes named in security but missing from components.securitySchemes.
  const known = new Set([
    ...allSupported.map((s) => s.name),
    ...allUnsupported.map((s) => s.name),
  ]);
  for (const name of requiredNames) {
    if (!known.has(name)) {
      unsupported.push({ name, type: 'unknown', detail: 'not declared in components.securitySchemes' });
    }
  }

  return {
    schemes,
    unsupported,
    alternatives,
    applies: schemes.length > 0,
  };
}

/**
 * True when any credential field for the given schemes is non-empty.
 *
 * @param schemes - Schemes the panel is collecting for.
 * @param credentials - Current credential map.
 */
export function hasFilledCredentials(
  schemes: SupportedAuthScheme[],
  credentials: AuthCredentialsMap
): boolean {
  for (const scheme of schemes) {
    const values = credentials[scheme.name];
    if (!values) continue;
    if (scheme.kind === 'bearer' && values.bearerToken?.trim()) return true;
    if (scheme.kind === 'apiKey' && values.apiKey?.trim()) return true;
    if (
      scheme.kind === 'basic' &&
      (values.username?.trim() || values.password?.trim())
    ) {
      return true;
    }
  }
  return false;
}

/**
 * True when the red "credentials leave via proxy" notice should show: custom host selected and
 * at least one auth field filled.
 *
 * @param isCustomHost - Whether the server picker is on the custom-URL slot.
 * @param schemes - Schemes the panel is collecting for.
 * @param credentials - Current credential map.
 */
export function shouldWarnProxyCredentials(
  isCustomHost: boolean,
  schemes: SupportedAuthScheme[],
  credentials: AuthCredentialsMap
): boolean {
  return isCustomHost && hasFilledCredentials(schemes, credentials);
}

/**
 * Apply filled auth credentials to a composed request's URL and headers.
 *
 * Auth headers overwrite same-named headers from the parameter form / extra-header rows so the
 * scheme-aware helper is the source of truth. Query apiKeys are appended (or replaced when the
 * same name is already present). Cookie apiKeys are written as a `Cookie` header — the SIM-3.2
 * relay strips cookies for credential hygiene, so cookie schemes only reach same-origin targets.
 *
 * @param url - Absolute request URL (may already include query params).
 * @param headers - Request headers (mutated copy returned).
 * @param schemes - Schemes to apply (typically the operation's supported schemes).
 * @param credentials - Filled credential values keyed by scheme name.
 */
export function applyAuthToRequest(
  url: string,
  headers: Record<string, string>,
  schemes: SupportedAuthScheme[],
  credentials: AuthCredentialsMap
): { url: string; headers: Record<string, string> } {
  const nextHeaders = { ...headers };
  let nextUrl = url;

  for (const scheme of schemes) {
    const values = credentials[scheme.name];
    if (!values) continue;

    if (scheme.kind === 'bearer') {
      const token = values.bearerToken?.trim() ?? '';
      if (token === '') continue;
      nextHeaders.Authorization = `Bearer ${token}`;
      continue;
    }

    if (scheme.kind === 'basic') {
      const username = values.username ?? '';
      const password = values.password ?? '';
      if (username.trim() === '' && password.trim() === '') continue;
      nextHeaders.Authorization = `Basic ${encodeBasicCredentials(username, password)}`;
      continue;
    }

    if (scheme.kind === 'apiKey') {
      const key = values.apiKey?.trim() ?? '';
      if (key === '') continue;
      if (scheme.location === 'header') {
        nextHeaders[scheme.paramName] = key;
      } else if (scheme.location === 'query') {
        try {
          const parsed = new URL(nextUrl);
          parsed.searchParams.set(scheme.paramName, key);
          nextUrl = parsed.toString();
        } catch {
          // Leave the URL unchanged when it cannot be parsed.
        }
      } else if (scheme.location === 'cookie') {
        const existing = nextHeaders.Cookie ?? nextHeaders.cookie;
        const pair = `${scheme.paramName}=${key}`;
        // Prefer canonical `Cookie` casing; drop a lowercase duplicate if present.
        delete nextHeaders.cookie;
        nextHeaders.Cookie = existing ? `${existing}; ${pair}` : pair;
      }
    }
  }

  return { url: nextUrl, headers: nextHeaders };
}

/**
 * Build explicit secret placeholders for filled auth schemes (merged over inferred ones by
 * snippet generators).
 *
 * @param schemes - Schemes the panel is collecting for.
 * @param credentials - Current credential map (only filled schemes contribute placeholders).
 */
export function authSecretPlaceholders(
  schemes: SupportedAuthScheme[],
  credentials: AuthCredentialsMap
): SecretPlaceholderMap {
  const map: SecretPlaceholderMap = {};
  for (const scheme of schemes) {
    const values = credentials[scheme.name];
    if (!values) continue;

    if (scheme.kind === 'bearer' && values.bearerToken?.trim()) {
      map.authorization = placeholderForHeader('Authorization');
    } else if (scheme.kind === 'basic' && (values.username?.trim() || values.password?.trim())) {
      map.authorization = placeholderForHeader('Authorization');
    } else if (scheme.kind === 'apiKey' && values.apiKey?.trim()) {
      if (scheme.location === 'header') {
        map[scheme.paramName.toLowerCase()] = placeholderForHeader(scheme.paramName);
      } else if (scheme.location === 'query') {
        map[`query:${scheme.paramName}`] = placeholderForQueryParam(scheme.paramName);
      } else if (scheme.location === 'cookie') {
        map.cookie = '$COOKIE';
      }
    }
  }
  return map;
}

/**
 * sessionStorage key for one scheme's credentials.
 *
 * @param schemeName - The OpenAPI security scheme name.
 */
export function authStorageKey(schemeName: string): string {
  return `${AUTH_STORAGE_PREFIX}${schemeName}`;
}

/**
 * Load credential values for the given schemes from session storage.
 *
 * @param schemeNames - Scheme names to load.
 * @param storage - Storage backend; defaults to `sessionStorage` when available.
 */
export function loadAuthCredentials(
  schemeNames: string[],
  storage?: AuthStorage | null
): AuthCredentialsMap {
  const store = storage ?? getDefaultSessionStorage();
  const out: AuthCredentialsMap = {};
  if (!store) return out;

  for (const name of schemeNames) {
    try {
      const raw = store.getItem(authStorageKey(name));
      if (!raw) continue;
      const parsed: unknown = JSON.parse(raw);
      if (!isObject(parsed)) continue;
      const values: AuthCredentialValues = {};
      if (typeof parsed.bearerToken === 'string') values.bearerToken = parsed.bearerToken;
      if (typeof parsed.apiKey === 'string') values.apiKey = parsed.apiKey;
      if (typeof parsed.username === 'string') values.username = parsed.username;
      if (typeof parsed.password === 'string') values.password = parsed.password;
      if (Object.keys(values).length > 0) out[name] = values;
    } catch {
      // Ignore corrupt entries; the next save will overwrite them.
    }
  }
  return out;
}

/**
 * Persist one scheme's credentials to session storage (or remove the key when all fields empty).
 *
 * @param schemeName - The OpenAPI security scheme name.
 * @param values - Credential fields for the scheme.
 * @param storage - Storage backend; defaults to `sessionStorage` when available.
 */
export function saveAuthCredentials(
  schemeName: string,
  values: AuthCredentialValues,
  storage?: AuthStorage | null
): void {
  const store = storage ?? getDefaultSessionStorage();
  if (!store) return;

  const trimmed: AuthCredentialValues = {};
  if (values.bearerToken?.trim()) trimmed.bearerToken = values.bearerToken;
  if (values.apiKey?.trim()) trimmed.apiKey = values.apiKey;
  if (values.username != null && values.username !== '') trimmed.username = values.username;
  if (values.password != null && values.password !== '') trimmed.password = values.password;

  const key = authStorageKey(schemeName);
  if (Object.keys(trimmed).length === 0) {
    store.removeItem(key);
    return;
  }
  store.setItem(key, JSON.stringify(trimmed));
}

/**
 * Remove stored credentials for the given schemes.
 *
 * @param schemeNames - Scheme names to clear.
 * @param storage - Storage backend; defaults to `sessionStorage` when available.
 */
export function clearAuthCredentials(
  schemeNames: string[],
  storage?: AuthStorage | null
): void {
  const store = storage ?? getDefaultSessionStorage();
  if (!store) return;
  for (const name of schemeNames) {
    store.removeItem(authStorageKey(name));
  }
}

/** Browser `sessionStorage`, or null outside a browser / when access is denied. */
function getDefaultSessionStorage(): AuthStorage | null {
  try {
    if (typeof sessionStorage === 'undefined') return null;
    return sessionStorage;
  } catch {
    return null;
  }
}
