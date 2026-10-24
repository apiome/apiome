/**
 * Audit events for sign-up attempts an abuse guard refused (SGN-1.5, #5654).
 *
 * Every refusal by a rate limit, the disposable-email blocklist or the CAPTCHA is appended to
 * `auth_events` as a failed `sign_up` row whose `detail.guard` names the guard. Super-admins read
 * them back on the System settings **Sign-up** card (**Recent blocked sign-ups**, through
 * `GET /v1/admin/signup-policy/blocked-attempts`). Sign-up happens before any workspace exists,
 * so these rows are an installation view, not part of a workspace's access audit.
 *
 * The raw IP and User-Agent go to apiome-rest only to be hashed; neither is stored. A rate-limit
 * refusal is recorded once per budget window (`RequestBudgetStatus.firstRefusal`), so a flood of
 * refused requests cannot become a flood of ledger rows.
 *
 * Server-only.
 */
import { postAuthEvent, type AuthEventInput } from './auth-event-writer';
import { resolveClientIp, type HeaderLookup } from './client-ip';

/** Which guard refused the attempt (`detail.guard`). */
export type SignupGuard = 'rate_limit' | 'disposable_domain' | 'captcha';

/** Every guard, in the order the admin card's legend lists them. */
export const SIGNUP_GUARDS: readonly SignupGuard[] = ['rate_limit', 'disposable_domain', 'captcha'];

/** For a rate limit, what was over budget (`detail.scope`). */
export type SignupRateLimitScope = 'ip' | 'address';

/** The `provider` recorded for the email form (an OAuth sign-up records its provider id). */
export const EMAIL_SIGNUP_PROVIDER = 'email';

/** What {@link recordSignupGuardEvent} records. */
export interface SignupGuardEvent {
  /** Which guard refused the attempt. */
  guard: SignupGuard;
  /** The stable code the person was shown. */
  code: string;
  /** {@link EMAIL_SIGNUP_PROVIDER} or the OAuth provider id; null when not yet known. */
  provider: string | null;
  /** For `rate_limit`: what was over budget. */
  scope?: SignupRateLimitScope;
  /** The canonical address the attempt carried, when one was read. */
  email?: string | null;
  /** The request headers (client IP and User-Agent are read from them and hashed upstream). */
  headers: HeaderLookup | null | undefined;
}

/** Read the User-Agent from either header container shape. */
function userAgent(headers: HeaderLookup | null | undefined): string | null {
  if (!headers) return null;
  if (typeof (headers as { get?: unknown }).get === 'function') {
    return (headers as { get(name: string): string | null }).get('user-agent');
  }
  const value = (headers as Record<string, string | string[] | undefined>)['user-agent'];
  return (Array.isArray(value) ? value[0] : value) ?? null;
}

/**
 * Build the `auth_events` row for a guard refusal (pure).
 *
 * @param event What was refused, and why.
 * @returns The row `postAuthEvent` sends.
 */
export function signupGuardAuthEvent(event: SignupGuardEvent): AuthEventInput {
  const detail: Record<string, unknown> = { guard: event.guard };
  if (event.scope) detail.scope = event.scope;
  const ua = userAgent(event.headers);
  return {
    event_type: 'sign_up',
    outcome: 'failure',
    provider: event.provider,
    user_label: event.email || null,
    error_code: event.code,
    ip: resolveClientIp(event.headers).slice(0, 128),
    user_agent: ua ? ua.slice(0, 1024) : null,
    detail,
  };
}

/**
 * Record a guard refusal in `auth_events` (best-effort; never rejects).
 *
 * @param event What was refused, and why.
 * @param write The ledger writer (injectable for tests).
 */
export async function recordSignupGuardEvent(
  event: SignupGuardEvent,
  write: (row: AuthEventInput) => Promise<void> = postAuthEvent,
): Promise<void> {
  try {
    await write(signupGuardAuthEvent(event));
  } catch {
    // Best-effort, like every auth_events write.
  }
}
