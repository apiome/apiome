/**
 * The two-factor sign-in policy, in one place (OLO-9.14, #5006).
 *
 * Three numbers decide how the second step behaves, and both the server configuration
 * (`auth.ts` → Better Auth's `twoFactor` plugin) and the sentences on `/login/2fa` and the
 * Profile page quote them. Declaring them once means a screen can never promise "30 days" or
 * "15 minutes" while the server enforces something else.
 *
 * - **Trusted device** — after a successful second factor with "Trust this device" ticked, this
 *   browser skips the second step for {@link TRUST_DEVICE_DAYS} days. The plugin keeps the trust
 *   as a signed cookie plus a server-side record, so it can be revoked from the Profile page.
 * - **Lockout** — {@link LOCKOUT_MAX_FAILED_ATTEMPTS} consecutive wrong codes, across challenges
 *   and across methods (authenticator, email, backup code), lock the account's second factor for
 *   {@link LOCKOUT_MINUTES} minutes. A correct code resets the count.
 *
 * It also owns the shape of a backup code and the wording for the plugin's refusals, so the
 * screen has no policy of its own. Free of server imports: safe in a client component.
 */

/** How long a trusted browser skips the second step, in days. */
export const TRUST_DEVICE_DAYS = 30;

/** {@link TRUST_DEVICE_DAYS} in seconds — the unit the plugin's `trustDeviceMaxAge` takes. */
export const TRUST_DEVICE_MAX_AGE_SECONDS = TRUST_DEVICE_DAYS * 24 * 60 * 60;

/** Consecutive failed second-factor verifications before the factor is locked. */
export const LOCKOUT_MAX_FAILED_ATTEMPTS = 10;

/** How long the second factor stays locked, in minutes. */
export const LOCKOUT_MINUTES = 15;

/** {@link LOCKOUT_MINUTES} in seconds — the unit the plugin's `accountLockout` takes. */
export const LOCKOUT_DURATION_SECONDS = LOCKOUT_MINUTES * 60;

/** Characters in each half of a backup code; the plugin issues `XXXXX-XXXXX`. */
const BACKUP_CODE_HALF = 5;

/** A complete backup code: two halves of five letters or digits, joined by a hyphen. */
const COMPLETE_BACKUP_CODE = /^[A-Za-z0-9]{5}-[A-Za-z0-9]{5}$/;

/**
 * Tidy whatever was typed or pasted into the backup-code box into the form the server compares.
 *
 * Backup codes are case-sensitive, so the case is never touched. Spaces and stray punctuation
 * from a copied list are dropped, and the hyphen is put back after the fifth character, so
 * `ab12c de34f`, `ab12cde34f` and `ab12c-de34f` all become `ab12c-de34f`.
 *
 * @param raw What the control now holds.
 * @returns At most ten letters or digits, with a hyphen after the fifth.
 */
export function normalizeBackupCode(raw: string): string {
  const characters = raw.replace(/[^A-Za-z0-9]/g, '').slice(0, BACKUP_CODE_HALF * 2);
  return characters.length > BACKUP_CODE_HALF
    ? `${characters.slice(0, BACKUP_CODE_HALF)}-${characters.slice(BACKUP_CODE_HALF)}`
    : characters;
}

/**
 * Whether a normalized value is a whole backup code, ready to send.
 *
 * @param code A value from {@link normalizeBackupCode}.
 * @returns `true` for `XXXXX-XXXXX`.
 */
export function isCompleteBackupCode(code: string): boolean {
  return COMPLETE_BACKUP_CODE.test(code);
}

/** What a refusal means for the screen, beyond the sentence to show. */
export interface TwoFactorRefusal {
  /** The sentence for the banner. */
  text: string;
  /**
   * `true` when no further code can succeed on this screen: the factor is locked, or the
   * sign-in challenge is spent or expired. The form is disabled and the reader is pointed back
   * to sign in.
   */
  terminal: boolean;
}

/**
 * The plugin's refusal codes that this screen words itself, rather than echoing the server.
 *
 * `ACCOUNT_TEMPORARILY_LOCKED` is the account-level lockout; `TOO_MANY_ATTEMPTS_REQUEST_NEW_CODE`
 * means this challenge's own attempts are spent; `INVALID_TWO_FACTOR_COOKIE` means the challenge
 * expired or was already used.
 */
const REFUSALS: Readonly<Record<string, TwoFactorRefusal>> = {
  ACCOUNT_TEMPORARILY_LOCKED: {
    text:
      `Too many incorrect codes. Two-factor sign-in is locked for ${LOCKOUT_MINUTES} minutes. ` +
      'Try again later, or ask an admin for help.',
    terminal: true,
  },
  TOO_MANY_ATTEMPTS_REQUEST_NEW_CODE: {
    text: 'Too many incorrect codes for this sign-in. Go back and sign in again to start over.',
    terminal: true,
  },
  INVALID_TWO_FACTOR_COOKIE: {
    text: 'This sign-in step has expired. Go back and sign in again.',
    terminal: true,
  },
  INVALID_BACKUP_CODE: {
    text: 'That backup code was not accepted. Each code works once — check it and try another.',
    terminal: false,
  },
};

/**
 * Word a refused verification for the banner.
 *
 * @param error The `error` a `authClient.twoFactor.verify*` call answered with.
 * @param fallback The sentence for a refusal the server did not explain (a plain wrong code).
 * @returns The sentence to show and whether the screen can still accept a code.
 */
export function describeTwoFactorRefusal(
  error: { code?: string | null; message?: string | null } | null | undefined,
  fallback: string
): TwoFactorRefusal {
  const known = error?.code ? REFUSALS[error.code] : undefined;
  return known ?? { text: error?.message || fallback, terminal: false };
}
