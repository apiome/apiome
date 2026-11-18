/**
 * Sign in with Apple — engine-neutral core (OLO-9.30, #5043).
 *
 * Apple differs from every other catalog provider in three ways, and each one lives here so the
 * Better Auth generic-OAuth wiring (`better-auth-oauth-providers.ts`) stays a thin config entry:
 *
 *  1. **The client secret is a signed JWT, not a static string.** Apple issues a `.p8` private key
 *     (an EC P-256 key in PKCS#8) with a Key ID; the client secret sent to the token endpoint is an
 *     ES256 JWT signed with that key, whose `iss` is the Team ID, `sub` the Services ID (the OAuth
 *     client id) and `aud` Apple's issuer. {@link createAppleClientSecret} mints a short-lived one
 *     for **each** code exchange, so there is no long-lived secret to expire or rotate — rotation
 *     means rotating the key itself (see `docs/AUTH_PROVIDER_SETUP.md`). The private key is stored
 *     in the sealed, write-only client-secret slot (`APPLE_PRIVATE_KEY`); the Team ID and Key ID are
 *     plain admin extras (`APPLE_TEAM_ID`, `APPLE_KEY_ID`).
 *  2. **The callback is a cross-site `form_post`.** Requesting the `name` and `email` scopes obliges
 *     `response_mode=form_post`, so Apple POSTs `code`/`state`/`user` to the redirect URI. Better
 *     Auth's generic callback (`/oauth2/callback/:id`) answers GET only, so
 *     {@link appleFormPostRedirect} turns that POST into a same-path `303` GET — the same bridge
 *     Better Auth's own `/callback/:id` route performs. The browser follows it as a top-level GET,
 *     which carries the `SameSite=Lax` state cookie the cross-site POST could not.
 *  3. **The name arrives only on first consent.** Apple sends the `user` form field (the person's
 *     first and last name) on the first authorization only, and never in the id token. The bridge
 *     keeps just the name from it (never the unsigned email — the email always comes from the
 *     id token), and {@link runWithAppleCallbackScope} exposes that name to the provider's
 *     normalizer for the one GET it travels on, so the resolution engine stores it on the account,
 *     the pending sign-up or the linked identity at that moment. A repeat sign-in has no name and
 *     resolves through the bound identity (`sub`).
 *
 * Kept free of better-auth imports so the wiring and the tests share one implementation.
 */

import { AsyncLocalStorage } from 'node:async_hooks';
import { createPrivateKey, sign as signWithKey, type KeyObject } from 'node:crypto';

/**
 * The provider slug — the value stored in `external_auth_providers.provider` (the OLO-2.2
 * vocabulary) AND the Better Auth generic-OAuth `providerId`. Never rename.
 */
export const APPLE_PROVIDER_ID = 'apple';

/** Apple's OIDC issuer: the `iss` of every Apple id token and the `aud` of the client secret. */
export const APPLE_ISSUER = 'https://appleid.apple.com';

/** Apple's fixed authorization endpoint. */
export const APPLE_AUTHORIZE_URL = 'https://appleid.apple.com/auth/authorize';

/** Apple's fixed token endpoint. */
export const APPLE_TOKEN_URL = 'https://appleid.apple.com/auth/token';

/** The scopes Apiome requests. Either one obliges `response_mode=form_post`. */
export const APPLE_SCOPES: readonly string[] = ['name', 'email'];

/** The Better Auth generic-OAuth callback path Apple posts to (under `/api/auth`). */
export const APPLE_CALLBACK_PATH_SUFFIX = `/oauth2/callback/${APPLE_PROVIDER_ID}`;

/**
 * Lifetime of a minted client secret, in seconds. Apple accepts up to six months; one exchange
 * needs a few seconds, so five minutes keeps a leaked secret nearly worthless.
 */
export const APPLE_CLIENT_SECRET_TTL_SECONDS = 300;

/** The env vars (and `config` extras) Apple sign-in reads. */
export const APPLE_ENV_KEYS = {
  clientId: 'APPLE_CLIENT_ID',
  privateKey: 'APPLE_PRIVATE_KEY',
  teamId: 'APPLE_TEAM_ID',
  keyId: 'APPLE_KEY_ID',
} as const;

/** A client-secret input that cannot be used; the message never contains key material. */
export class AppleClientSecretError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'AppleClientSecretError';
  }
}

/**
 * Read a trimmed env string, or null when unset/blank.
 *
 * @param env Environment map to read.
 * @param key Env var name.
 * @returns The trimmed value, or null when unset or blank.
 */
function readEnvString(env: Record<string, string | undefined>, key: string): string | null {
  const raw = env[key];
  if (typeof raw !== 'string') return null;
  const trimmed = raw.trim();
  return trimmed.length > 0 ? trimmed : null;
}

/** The four values Apple sign-in needs, read from the resolved (DB-over-env) config. */
export interface AppleCredentials {
  /** The Services ID — Apple's OAuth client id. */
  clientId: string;
  /** The 10-character Apple Developer Team ID (`iss` of the client secret). */
  teamId: string;
  /** The Key ID of the `.p8` key (`kid` of the client secret). */
  keyId: string;
  /** The `.p8` private key as stored (PEM, PEM without line breaks, or the bare base64 body). */
  privateKey: string;
}

/**
 * Read Apple's credentials from the resolved config.
 *
 * @param env Environment to read (the DB-over-env overlay in production).
 * @returns The credentials, with `''` for anything unset (the registry keeps a partly configured
 *   provider disabled, so a build never sees blanks in practice).
 */
export function appleCredentials(
  env: Record<string, string | undefined> = process.env,
): AppleCredentials {
  return {
    clientId: readEnvString(env, APPLE_ENV_KEYS.clientId) ?? '',
    teamId: readEnvString(env, APPLE_ENV_KEYS.teamId) ?? '',
    keyId: readEnvString(env, APPLE_ENV_KEYS.keyId) ?? '',
    privateKey: readEnvString(env, APPLE_ENV_KEYS.privateKey) ?? '',
  };
}

/** The PEM armour of a PKCS#8 private key, as Apple's `.p8` download carries it. */
const PEM_PRIVATE_KEY = /-----BEGIN PRIVATE KEY-----([\s\S]*?)-----END PRIVATE KEY-----/;

/**
 * Parse Apple's `.p8` private key, however it was pasted.
 *
 * A single-line admin input drops the PEM's line breaks, and a `.env` value often carries them as
 * literal `\n`; both are accepted, as is the bare base64 body. The key must be an EC P-256 key —
 * what Apple issues and what ES256 needs.
 *
 * @param raw The stored key text.
 * @returns The parsed private key.
 * @throws AppleClientSecretError when the text is not a P-256 PKCS#8 private key.
 */
export function parseApplePrivateKey(raw: string): KeyObject {
  const text = raw.replace(/\\n/g, '\n');
  const armoured = PEM_PRIVATE_KEY.exec(text);
  const body = (armoured ? armoured[1] : text).replace(/\s+/g, '');
  if (body.length === 0 || !/^[A-Za-z0-9+/]+={0,2}$/.test(body)) {
    throw new AppleClientSecretError(
      'APPLE_PRIVATE_KEY is not a PKCS#8 private key (paste the whole .p8 file).',
    );
  }
  let key: KeyObject;
  try {
    key = createPrivateKey({
      key: Buffer.from(body, 'base64'),
      format: 'der',
      type: 'pkcs8',
    });
  } catch {
    throw new AppleClientSecretError(
      'APPLE_PRIVATE_KEY could not be read as a PKCS#8 private key (paste the whole .p8 file).',
    );
  }
  if (key.asymmetricKeyType !== 'ec' || key.asymmetricKeyDetails?.namedCurve !== 'prime256v1') {
    throw new AppleClientSecretError(
      'APPLE_PRIVATE_KEY is not an EC P-256 key; use the .p8 key Apple issued for Sign in with Apple.',
    );
  }
  return key;
}

/**
 * Base64url-encode a JSON value (a JWT header or claim set).
 *
 * @param value The value to encode.
 * @returns The unpadded base64url string.
 */
function base64UrlJson(value: unknown): string {
  return Buffer.from(JSON.stringify(value), 'utf8').toString('base64url');
}

/**
 * Mint the ES256 client-secret JWT Apple's token endpoint requires.
 *
 * Header `{ alg: ES256, kid: <Key ID> }`; claims `iss` = Team ID, `iat` = now, `exp` = now + `ttl`,
 * `aud` = {@link APPLE_ISSUER}, `sub` = Services ID. The signature is the raw `r || s` pair JOSE
 * requires (`ieee-p1363`), not DER.
 *
 * @param credentials The Services ID, Team ID, Key ID and private key.
 * @param nowSeconds The issue time in epoch seconds (injectable for tests).
 * @param ttlSeconds Lifetime in seconds (default {@link APPLE_CLIENT_SECRET_TTL_SECONDS}).
 * @returns The compact-serialized JWT.
 * @throws AppleClientSecretError when a value is missing or the key is unusable.
 */
export function createAppleClientSecret(
  credentials: AppleCredentials,
  nowSeconds: number = Math.floor(Date.now() / 1000),
  ttlSeconds: number = APPLE_CLIENT_SECRET_TTL_SECONDS,
): string {
  const { clientId, teamId, keyId, privateKey } = credentials;
  const missing = (
    [
      [APPLE_ENV_KEYS.clientId, clientId],
      [APPLE_ENV_KEYS.teamId, teamId],
      [APPLE_ENV_KEYS.keyId, keyId],
      [APPLE_ENV_KEYS.privateKey, privateKey],
    ] as const
  )
    .filter(([, value]) => value.trim().length === 0)
    .map(([name]) => name);
  if (missing.length > 0) {
    throw new AppleClientSecretError(`Apple sign-in is missing ${missing.join(', ')}.`);
  }
  const key = parseApplePrivateKey(privateKey);
  const signingInput = [
    base64UrlJson({ alg: 'ES256', kid: keyId }),
    base64UrlJson({
      iss: teamId,
      iat: nowSeconds,
      exp: nowSeconds + ttlSeconds,
      aud: APPLE_ISSUER,
      sub: clientId,
    }),
  ].join('.');
  const signature = signWithKey('sha256', Buffer.from(signingInput, 'utf8'), {
    key,
    dsaEncoding: 'ieee-p1363',
  });
  return `${signingInput}.${signature.toString('base64url')}`;
}

/* ── First-consent name ────────────────────────────────────────────────────────────────────── */

/** The longest name part kept from Apple's `user` field; anything longer is truncated. */
const MAX_NAME_PART_LENGTH = 100;

/**
 * Read one name part from Apple's `user.name` object.
 *
 * @param value The raw `firstName` / `lastName` value.
 * @returns The trimmed, length-capped string, or null when absent or not a string.
 */
function namePart(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim().slice(0, MAX_NAME_PART_LENGTH);
  return trimmed.length > 0 ? trimmed : null;
}

/**
 * The display name from Apple's first-consent `user` form field.
 *
 * Apple sends `{"name":{"firstName":…,"lastName":…},"email":…}` on the first authorization only.
 * The field is unsigned, so only the name is read from it — never the email.
 *
 * @param raw The `user` field (a JSON string), or null/undefined when Apple sent none.
 * @returns `"<first> <last>"` (or whichever part is present), or null when there is no name.
 */
export function appleFirstConsentName(raw: string | null | undefined): string | null {
  if (typeof raw !== 'string' || raw.length === 0) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== 'object') return null;
  const name = (parsed as Record<string, unknown>).name;
  if (!name || typeof name !== 'object') return null;
  const first = namePart((name as Record<string, unknown>).firstName);
  const last = namePart((name as Record<string, unknown>).lastName);
  const full = [first, last].filter((part): part is string => part !== null).join(' ');
  return full.length > 0 ? full : null;
}

/**
 * The request method, upper-cased (`GET` when a caller's request object carries none).
 *
 * @param request The incoming request.
 * @returns The method, e.g. `POST`.
 */
function requestMethod(request: Request): string {
  return typeof request.method === 'string' ? request.method.toUpperCase() : 'GET';
}

/**
 * Whether a request targets Apple's generic-OAuth callback.
 *
 * @param request The incoming request.
 * @returns True for `…/oauth2/callback/apple` (any method).
 */
function isAppleCallback(request: Request): boolean {
  if (typeof request.url !== 'string') return false;
  try {
    return new URL(request.url).pathname.endsWith(APPLE_CALLBACK_PATH_SUFFIX);
  } catch {
    return false;
  }
}

/** The form fields the bridge forwards to the GET callback, in order. */
const FORWARDED_FIELDS = ['code', 'state', 'error', 'error_description'] as const;

/**
 * Turn Apple's cross-site `form_post` callback into a same-path `303` GET Better Auth can serve.
 *
 * Forwards `code`, `state`, `error` and `error_description`, plus — on first consent — the name
 * alone, re-serialized as `user={"name":{…}}` so the unsigned email Apple echoes there never
 * travels further. The `Location` is relative, so a proxied deployment keeps its public host.
 *
 * @param request The incoming request.
 * @returns The `303` response for a POST to Apple's callback, or null for any other request.
 */
export async function appleFormPostRedirect(request: Request): Promise<Response | null> {
  if (requestMethod(request) !== 'POST' || !isAppleCallback(request)) return null;

  let form: URLSearchParams;
  try {
    form = new URLSearchParams(await request.text());
  } catch {
    form = new URLSearchParams();
  }

  const params = new URLSearchParams();
  for (const field of FORWARDED_FIELDS) {
    const value = form.get(field);
    if (value) params.set(field, value);
  }
  const name = appleFirstConsentName(form.get('user'));
  if (name) params.set('user', JSON.stringify({ name: { fullName: name } }));

  const { pathname } = new URL(request.url);
  return new Response(null, {
    status: 303,
    headers: {
      Location: `${pathname}?${params.toString()}`,
      'Cache-Control': 'no-store',
    },
  });
}

/**
 * The name forwarded by {@link appleFormPostRedirect}: `{"name":{"fullName":…}}`.
 *
 * @param raw The `user` query parameter of the GET callback.
 * @returns The name, or null when absent or malformed.
 */
function forwardedName(raw: string | null): string | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as { name?: { fullName?: unknown } } | null;
    return namePart(parsed?.name?.fullName);
  } catch {
    return null;
  }
}

/** Request-scoped first-consent name, read by the Apple normalizer during the GET callback. */
const appleCallbackStore = new AsyncLocalStorage<{
  firstConsentName: string | null;
}>();

/**
 * Run `fn` with this request's first-consent name available to {@link currentAppleFirstConsentName}.
 *
 * Only a GET to Apple's callback opens a scope; every other request runs `fn` unchanged.
 *
 * @param request The incoming request.
 * @param fn The work to run (the Better Auth handler).
 * @returns Whatever `fn` resolves to.
 */
export function runWithAppleCallbackScope<T>(request: Request, fn: () => Promise<T>): Promise<T> {
  if (requestMethod(request) !== 'GET' || !isAppleCallback(request)) return fn();
  let firstConsentName: string | null = null;
  try {
    firstConsentName = forwardedName(new URL(request.url).searchParams.get('user'));
  } catch {
    firstConsentName = null;
  }
  return appleCallbackStore.run({ firstConsentName }, fn);
}

/**
 * The first-consent name of the Apple callback being served.
 *
 * @returns The name, or null on a repeat sign-in or outside an Apple callback.
 */
export function currentAppleFirstConsentName(): string | null {
  return appleCallbackStore.getStore()?.firstConsentName ?? null;
}
