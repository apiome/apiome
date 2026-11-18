/**
 * Whether this server can send SMS two-factor codes (OLO-9.51 #5071).
 *
 * The Twilio env vars and the "is it configured" check, with no dependencies, so the Profile
 * actions, the phone-number guard and the OTP router can ask without loading the sender (which
 * pulls in Better Auth's ESM-only API module).
 */

/** Env var: Twilio Account SID (`AC…`). */
export const TWILIO_ACCOUNT_SID_ENV = 'TWILIO_ACCOUNT_SID';

/** Env var: Twilio Auth Token for that account. */
export const TWILIO_AUTH_TOKEN_ENV = 'TWILIO_AUTH_TOKEN';

/** Env var: the sending number (E.164). Either this or a Messaging Service SID is required. */
export const TWILIO_FROM_NUMBER_ENV = 'TWILIO_FROM_NUMBER';

/** Env var: a Twilio Messaging Service SID (`MG…`); preferred over the from-number when both are set. */
export const TWILIO_MESSAGING_SERVICE_SID_ENV = 'TWILIO_MESSAGING_SERVICE_SID';

/**
 * Read one env var, trimmed; blank counts as unset.
 *
 * @param env Environment map.
 * @param name Variable name.
 * @returns The value, or `undefined`.
 */
export function readEnv(env: NodeJS.Dict<string>, name: string): string | undefined {
  const value = env[name]?.trim();
  return value ? value : undefined;
}

/**
 * True when Twilio is configured well enough to send a text: account SID, auth token, and a
 * sender (a from-number or a Messaging Service SID).
 *
 * @param env Environment map; defaults to `process.env` (injectable for tests).
 */
export function isTwoFactorSmsOtpConfigured(env: NodeJS.Dict<string> = process.env): boolean {
  return Boolean(
    readEnv(env, TWILIO_ACCOUNT_SID_ENV) &&
    readEnv(env, TWILIO_AUTH_TOKEN_ENV) &&
    (readEnv(env, TWILIO_FROM_NUMBER_ENV) || readEnv(env, TWILIO_MESSAGING_SERVICE_SID_ENV)),
  );
}
