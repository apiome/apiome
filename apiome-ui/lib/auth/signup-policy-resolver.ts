/**
 * Cached read of the installation sign-up policy (SGN-1.4, #5653).
 *
 * Every sign-up enforcement point in apiome-ui — the OAuth resolution engine (through
 * `resolution-store.ts`) and the email sign-up action — asks this module for the effective policy:
 * the stored `apiome.signup_policy` row when there is one, else the `AUTH_SIGNUP_DISABLED` env
 * fallback (`signup-policy.ts`).
 *
 * The result is cached in-process for a short lifetime, so a policy change takes effect **without
 * a restart**: at once on the instance that served the admin's save (the proxy calls
 * {@link invalidateSignupPolicyCache}), and within the cache lifetime on every other instance.
 *
 * Failure handling: when the database cannot be read, the last policy this process read is served
 * if there is one; otherwise sign-up **fails closed** (`closed`) rather than falling back to a
 * possibly more permissive env value. A failure is never cached, so the next call retries. A
 * database that has not had V274 applied yet is not a failure — the table not existing is the same
 * "nothing stored" state, so env behaviour is unchanged until the migration runs.
 *
 * Mirror of the cached half of `apiome-rest/src/app/signup_policy.py`.
 *
 * Server-only: reads the database. Never import from a client component.
 */
import { signupPolicyFromEnv, signupPolicyFromRow, type SignupPolicy } from './signup-policy';

/** An env-shaped map, matching the other auth resolvers' injectable `env` parameter. */
type EnvMap = Record<string, string | undefined>;

/** Reads the stored policy row; resolves null when no policy is stored. */
export type SignupPolicyRowReader = () => Promise<{
  mode?: unknown;
  allowed_email_domains?: unknown;
} | null>;

/** Default cache lifetime (ms): a change made on another instance lands within this. */
export const DEFAULT_CACHE_TTL_MS = 30_000;
/** Bounds on the configurable lifetime, so it is neither a per-request read nor unboundedly stale. */
export const MIN_CACHE_TTL_MS = 1_000;
export const MAX_CACHE_TTL_MS = 300_000;

/** Postgres SQLSTATE for "relation does not exist" — V274 not applied yet. */
const UNDEFINED_TABLE = '42P01';

interface CacheEntry {
  /** The effective policy last read. */
  policy: SignupPolicy;
  /** Clock reading (ms) when it was read. */
  readAt: number;
}

/** Module-level in-process cache (per server instance). Reset via {@link invalidateSignupPolicyCache}. */
let cache: CacheEntry | null = null;

/**
 * Resolve the cache lifetime from `SIGNUP_POLICY_CACHE_TTL_SECONDS`, clamped to the bounds.
 *
 * The variable is in seconds so one value configures apiome-ui and apiome-rest alike.
 *
 * @param env Environment to read (injectable for tests).
 * @returns The lifetime in milliseconds.
 */
export function signupPolicyCacheTtlMs(env: EnvMap = process.env): number {
  const raw = env.SIGNUP_POLICY_CACHE_TTL_SECONDS;
  const parsed = raw && raw.trim() ? Number(raw) : NaN;
  if (!Number.isFinite(parsed)) return DEFAULT_CACHE_TTL_MS;
  return Math.min(MAX_CACHE_TTL_MS, Math.max(MIN_CACHE_TTL_MS, Math.trunc(parsed * 1000)));
}

/**
 * Drop the cached policy so the next read goes to the database.
 *
 * Called after a successful admin save so the instance that served it applies the change at once
 * instead of after the cache lifetime.
 */
export function invalidateSignupPolicyCache(): void {
  cache = null;
}

/**
 * Read the stored policy row from `apiome.signup_policy`.
 *
 * @returns The row, or null when no policy is stored or the table does not exist yet.
 */
const readStoredRow: SignupPolicyRowReader = async () => {
  // Required lazily so importing this module (e.g. from a unit test of a caller) opens no pool.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const connectionPool = require('../db/db');
  try {
    const result = await connectionPool.query(
      'SELECT mode, allowed_email_domains FROM apiome.signup_policy WHERE singleton',
    );
    return result.rowCount > 0 ? result.rows[0] : null;
  } catch (error) {
    if ((error as { code?: string } | null)?.code === UNDEFINED_TABLE) return null;
    throw error;
  }
};

/** Injection points for {@link resolveSignupPolicy} (tests only; production uses the defaults). */
export interface ResolveSignupPolicyOptions {
  /** Reads the stored row (defaults to the `apiome.signup_policy` query). */
  readRow?: SignupPolicyRowReader;
  /** Environment for the fallback and the cache lifetime (defaults to `process.env`). */
  env?: EnvMap;
  /** Clock in ms (defaults to `Date.now`). */
  now?: () => number;
}

/**
 * Resolve the effective sign-up policy: the stored one, else the env fallback (cached).
 *
 * @param options Injection points for tests.
 * @returns The effective policy. Never rejects — see the module doc for failure handling.
 */
export async function resolveSignupPolicy(
  options: ResolveSignupPolicyOptions = {},
): Promise<SignupPolicy> {
  const env = options.env ?? process.env;
  const now = options.now ?? Date.now;

  if (cache && now() - cache.readAt < signupPolicyCacheTtlMs(env)) {
    return cache.policy;
  }
  const stale = cache?.policy ?? null;

  let row: Awaited<ReturnType<SignupPolicyRowReader>>;
  try {
    row = await (options.readRow ?? readStoredRow)();
  } catch (error) {
    console.error(
      'Sign-up policy: could not read the stored policy:',
      error instanceof Error ? error.message : error,
    );
    return stale ?? { mode: 'closed', allowedEmailDomains: [], source: 'db' };
  }

  const policy = signupPolicyFromRow(row) ?? signupPolicyFromEnv(env);
  cache = { policy, readAt: now() };
  return policy;
}
