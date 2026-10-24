/**
 * Installation sign-up policy — who may create an account (SGN-1.4, #5653).
 *
 * One policy decides whether a new person may create an account, for **every** sign-up path: the
 * email form and each OAuth provider. It replaces the single `AUTH_SIGNUP_DISABLED` env flag with
 * a database-stored setting a super-admin changes from the admin console, keeping the env flag as
 * the fallback (the OLO-8 DB-first pattern):
 *
 *   - **No stored policy** ⇒ env governs, exactly as before: `AUTH_SIGNUP_DISABLED=true|1` reads
 *     as `closed`, anything else as `open`.
 *   - **Stored policy** (`apiome.signup_policy`, V274) ⇒ its mode and allowed domains win.
 *
 * Modes:
 *
 *   - `open` — anyone may create an account; when `allowedEmailDomains` is non-empty, only an
 *     address at one of those domains may.
 *   - `invite_only` — no self-service account creation. Tenant invitations go to people who
 *     already hold an account, so they sign in (and activate their pending membership) as usual;
 *     a person with no account is refused with `signup-invite-only`.
 *   - `closed` — no self-service account creation at all (`signup-disabled`).
 *
 * The policy only ever gates **creating** an account. It never stops an existing user signing in.
 *
 * The stored row also carries `blockedEmailDomains` (V317, SGN-1.5 #5654): extra disposable domains
 * refused for **email** sign-up, on top of the bundled list in `disposable-email-domains.ts`. It is
 * not part of {@link signupRejectionCode} — only the email sign-up action applies it, because an
 * OAuth provider has already verified the address it hands over.
 *
 * This module is pure (no I/O, no imports) so the whole matrix is testable in isolation and it can
 * be imported from client components; the cached database read lives in
 * `signup-policy-resolver.ts`. It is the TypeScript mirror of
 * `apiome-rest/src/app/signup_policy.py` — any behavioural change here MUST be made there as well.
 */

/** Who may create an account. */
export type SignupMode = 'open' | 'invite_only' | 'closed';

/** Every mode, in the order the admin console lists them. */
export const SIGNUP_MODES: readonly SignupMode[] = ['open', 'invite_only', 'closed'];

/** Where the effective policy came from: the database row, or the env fallback. */
export type SignupPolicySource = 'db' | 'env';

/** The installation's effective sign-up policy. */
export interface SignupPolicy {
  /** Who may create an account. */
  mode: SignupMode;
  /**
   * Lower-case email domains allowed to sign up while `mode` is `open`; empty means any domain.
   * Ignored by the other modes.
   */
  allowedEmailDomains: readonly string[];
  /** `db` when the policy is stored, `env` when it is the `AUTH_SIGNUP_DISABLED` fallback. */
  source: SignupPolicySource;
  /**
   * Extra lower-case domains refused for email sign-up, on top of the bundled disposable list
   * (SGN-1.5). Absent or empty ⇒ only the bundled list applies.
   */
  blockedEmailDomains?: readonly string[];
}

/**
 * The stable rejection codes the policy emits. Each is also a member of `AUTH_ERROR_CODES`
 * (`account-resolution.ts`) and mirrored in `apiome-rest/src/app/signup_policy.py`; never change
 * or reuse a value.
 */
export const SIGNUP_REJECTION_CODES = {
  /** Self-signup is disabled on this deployment (mode `closed`). */
  SIGNUP_DISABLED: 'signup-disabled',
  /** Sign-up is by invitation only and this address has no account (mode `invite_only`). */
  SIGNUP_INVITE_ONLY: 'signup-invite-only',
  /** Sign-up is open, but not to this address's email domain. */
  SIGNUP_DOMAIN_NOT_ALLOWED: 'signup-domain-not-allowed',
} as const;

export type SignupRejectionCode =
  (typeof SIGNUP_REJECTION_CODES)[keyof typeof SIGNUP_REJECTION_CODES];

/** Upper bound on the allowed-domain list (matches the V274 CHECK and the REST validation). */
export const MAX_ALLOWED_EMAIL_DOMAINS = 200;

/** Upper bound on the extra blocked-domain list (matches the V317 CHECK and the REST validation). */
export const MAX_BLOCKED_EMAIL_DOMAINS = 1000;

/**
 * A bare DNS domain: dot-separated labels of letters/digits/hyphens, no leading/trailing hyphen,
 * at least two labels, at most 253 characters overall.
 */
const DOMAIN_SHAPE =
  /^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;

/**
 * Whether a value is one of the three sign-up modes.
 *
 * @param value Any value (e.g. a database column or a request field).
 * @returns True when it is `open`, `invite_only` or `closed`.
 */
export function isSignupMode(value: unknown): value is SignupMode {
  return typeof value === 'string' && (SIGNUP_MODES as readonly string[]).includes(value);
}

/**
 * Normalize one allowed-domain entry to a lower-case bare domain.
 *
 * Accepts the forms an operator is likely to type — `Example.com`, `@example.com`,
 * `  example.com  ` — and reduces them to `example.com`. Matching is exact, so a subdomain must be
 * listed in its own right.
 *
 * @param raw The entry as supplied.
 * @returns The normalized domain, or null when it is not a valid bare domain (an address, a URL,
 *   a wildcard, a single label, …).
 */
export function normalizeEmailDomain(raw: unknown): string | null {
  if (typeof raw !== 'string') return null;
  let domain = raw.trim().toLowerCase();
  if (domain.startsWith('@')) domain = domain.slice(1);
  return DOMAIN_SHAPE.test(domain) ? domain : null;
}

/** Result of {@link parseAllowedEmailDomains}: the usable domains and the entries refused. */
export interface ParsedEmailDomains {
  /** Normalized domains, first occurrence first, duplicates dropped. */
  domains: string[];
  /** Entries that are not valid domains, as typed. */
  invalid: string[];
}

/**
 * Parse the free-text domain list an operator types (separated by commas, spaces or new lines).
 *
 * @param text The raw field value.
 * @returns The normalized domains and the entries that could not be read as a domain.
 */
export function parseAllowedEmailDomains(text: string): ParsedEmailDomains {
  const domains: string[] = [];
  const invalid: string[] = [];
  for (const entry of text.split(/[\s,;]+/)) {
    if (!entry) continue;
    const domain = normalizeEmailDomain(entry);
    if (!domain) invalid.push(entry);
    else if (!domains.includes(domain)) domains.push(domain);
  }
  return { domains, invalid };
}

/**
 * The lower-case domain of an email address.
 *
 * @param email The address (canonical or not).
 * @returns The text after the last `@`, trimmed and lower-cased; null for a missing or malformed
 *   address.
 */
export function emailDomain(email: unknown): string | null {
  if (typeof email !== 'string') return null;
  const value = email.trim().toLowerCase();
  const at = value.lastIndexOf('@');
  if (at <= 0 || at === value.length - 1) return null;
  return value.slice(at + 1);
}

/**
 * Whether the env fallback refuses self-signup (`AUTH_SIGNUP_DISABLED=true|1`).
 *
 * @param env Environment to read (injectable for tests; defaults to `process.env`).
 * @returns True when the flag is explicitly `true` or `1` (case-insensitive, trimmed).
 */
export function isSignupDisabledByEnv(
  env: Record<string, string | undefined> = process.env,
): boolean {
  const raw = env.AUTH_SIGNUP_DISABLED;
  if (typeof raw !== 'string') return false;
  const normalized = raw.trim().toLowerCase();
  return normalized === 'true' || normalized === '1';
}

/**
 * The env-fallback policy: `closed` when `AUTH_SIGNUP_DISABLED` is set, else `open`.
 *
 * @param env Environment to read (injectable for tests; defaults to `process.env`).
 * @returns A policy with source `env` and no domain restriction — the pre-SGN-1.4 behaviour.
 */
export function signupPolicyFromEnv(
  env: Record<string, string | undefined> = process.env,
): SignupPolicy {
  return {
    mode: isSignupDisabledByEnv(env) ? 'closed' : 'open',
    allowedEmailDomains: [],
    source: 'env',
    blockedEmailDomains: [],
  };
}

/**
 * Read a stored domain array: normalized, duplicates dropped, malformed entries dropped (a
 * malformed stored domain can never match an address).
 *
 * @param stored The stored column value.
 * @returns The usable domains, first occurrence first.
 */
function storedDomains(stored: unknown): string[] {
  const domains: string[] = [];
  for (const entry of Array.isArray(stored) ? stored : []) {
    const domain = normalizeEmailDomain(entry);
    if (domain && !domains.includes(domain)) domains.push(domain);
  }
  return domains;
}

/**
 * Build a policy from a stored `apiome.signup_policy` row.
 *
 * @param row The stored row (`mode`, `allowed_email_domains`, and since V317
 *   `blocked_email_domains`), or null/undefined when none is stored.
 * @returns The stored policy with source `db`, or null when there is no usable row — the caller
 *   then falls back to env. A row whose mode is unrecognized is treated as unusable rather than
 *   guessed at; a malformed stored domain can never match an address, so it is dropped.
 */
export function signupPolicyFromRow(
  row:
    | { mode?: unknown; allowed_email_domains?: unknown; blocked_email_domains?: unknown }
    | null
    | undefined,
): SignupPolicy | null {
  if (!row || !isSignupMode(row.mode)) return null;
  return {
    mode: row.mode,
    allowedEmailDomains: storedDomains(row.allowed_email_domains),
    source: 'db',
    blockedEmailDomains: storedDomains(row.blocked_email_domains),
  };
}

/**
 * Decide whether the policy refuses creating an account for this address (pure — no I/O).
 *
 * The single gate every sign-up path shares, so email and each OAuth provider can never be
 * treated differently.
 *
 * @param policy The effective policy.
 * @param email The address the account would be created with.
 * @returns Null when the account may be created; otherwise the stable rejection code —
 *   `signup-disabled` (`closed`), `signup-invite-only` (`invite_only`), or
 *   `signup-domain-not-allowed` (`open` with a domain list the address is not on). An unrecognized
 *   mode fails closed.
 */
export function signupRejectionCode(
  policy: SignupPolicy,
  email: string | null | undefined,
): SignupRejectionCode | null {
  if (policy.mode === 'invite_only') return SIGNUP_REJECTION_CODES.SIGNUP_INVITE_ONLY;
  if (policy.mode !== 'open') return SIGNUP_REJECTION_CODES.SIGNUP_DISABLED;
  if (policy.allowedEmailDomains.length > 0) {
    const domain = emailDomain(email);
    if (!domain || !policy.allowedEmailDomains.includes(domain)) {
      return SIGNUP_REJECTION_CODES.SIGNUP_DOMAIN_NOT_ALLOWED;
    }
  }
  return null;
}
