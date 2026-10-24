/**
 * Optional CAPTCHA on the email sign-up form: Cloudflare Turnstile (SGN-1.5, #5654).
 *
 * Off by default. It turns on when **both** `TURNSTILE_SITE_KEY` (public, sent to the browser to
 * draw the widget) and `TURNSTILE_SECRET_KEY` (server-only, verifies the widget's token) are set;
 * with only one of them it stays off, because a widget whose token cannot be verified (or a check
 * the browser cannot complete) would only lock everyone out.
 *
 * While on, `startEmailSignup` refuses a submission whose token Cloudflare does not confirm with
 * `email-signup-captcha-failed`. The check fails closed: if Cloudflare cannot be reached, the
 * submission is refused rather than let through. OAuth sign-up and **Resend email** never show
 * the widget.
 *
 * Server-only: reads the secret. The browser gets the site key through the `/signup` page props.
 */

/** Cloudflare's server-side token check. */
export const TURNSTILE_VERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify';

/** The browser script that draws the widget (explicit rendering, so React controls the mount). */
export const TURNSTILE_SCRIPT_URL =
  'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';

/** Longest token accepted (Cloudflare documents 2048 characters). */
export const TURNSTILE_TOKEN_MAX_LENGTH = 2048;

/** How long the server waits for Cloudflare before failing closed. */
const VERIFY_TIMEOUT_MS = 5_000;

/** The two keys, when Turnstile is configured. */
export interface TurnstileConfig {
  /** Public site key the widget is drawn with. */
  siteKey: string;
  /** Secret key the server verifies tokens with. */
  secretKey: string;
}

/**
 * Read the Turnstile keys from the environment.
 *
 * @param env Environment to read (injectable for tests).
 * @returns Both keys when both are set (trimmed, non-empty); otherwise null — CAPTCHA is off.
 */
export function turnstileConfig(env: NodeJS.Dict<string> = process.env): TurnstileConfig | null {
  const siteKey = env.TURNSTILE_SITE_KEY?.trim();
  const secretKey = env.TURNSTILE_SECRET_KEY?.trim();
  return siteKey && secretKey ? { siteKey, secretKey } : null;
}

/**
 * The site key to hand the browser, or null when CAPTCHA is off.
 *
 * @param env Environment to read (injectable for tests).
 * @returns `TURNSTILE_SITE_KEY` when Turnstile is fully configured; never the secret.
 */
export function turnstileSiteKey(env: NodeJS.Dict<string> = process.env): string | null {
  return turnstileConfig(env)?.siteKey ?? null;
}

/**
 * Ask Cloudflare whether a widget token is genuine.
 *
 * @param token The token the widget produced (`cf-turnstile-response`).
 * @param secretKey `TURNSTILE_SECRET_KEY`.
 * @param remoteIp The client IP, passed on as a hint; `unknown` is left out.
 * @param fetchImpl Fetch implementation (injectable for tests).
 * @returns True only when Cloudflare answers `success: true`. A missing, over-long or rejected
 *   token, a non-2xx answer, a timeout or a network error all return false (fail closed).
 */
export async function verifyTurnstileToken(
  token: unknown,
  secretKey: string,
  remoteIp: string | null,
  fetchImpl: typeof fetch = fetch,
): Promise<boolean> {
  if (typeof token !== 'string' || !token || token.length > TURNSTILE_TOKEN_MAX_LENGTH) return false;
  const body = new URLSearchParams({ secret: secretKey, response: token });
  if (remoteIp && remoteIp !== 'unknown') body.set('remoteip', remoteIp);
  try {
    const response = await fetchImpl(TURNSTILE_VERIFY_URL, {
      method: 'POST',
      body,
      cache: 'no-store',
      signal: AbortSignal.timeout(VERIFY_TIMEOUT_MS),
    });
    if (!response.ok) return false;
    const result = (await response.json().catch(() => null)) as { success?: unknown } | null;
    return result?.success === true;
  } catch {
    return false;
  }
}
