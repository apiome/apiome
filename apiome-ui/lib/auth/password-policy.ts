/**
 * The password rules every credential write enforces (SGN-1.1, #5650).
 *
 * One rule set, shared by the profile's **Change password** (`updateUserPassword` in
 * `lib/db/helper.ts`) and email sign-up (`email-signup-actions.ts`), so a password one accepts the
 * other accepts too. The strength meter (`components/ade/account/passwordStrength.ts`) measures
 * against these same expressions; `tests/password-policy.test.ts` keeps the two in step.
 */

/** Shortest password accepted. */
export const PASSWORD_POLICY_MIN_LENGTH = 8;

/** Longest password accepted: bcrypt reads only the first 72 bytes, so more would be ignored. */
export const PASSWORD_POLICY_MAX_LENGTH = 72;

/** Characters that satisfy the "number or special character" rule. */
export const PASSWORD_SYMBOL_PATTERN = /[0-9!@#$%^&*()_+\-=[\]{};':"\\|,.<>/?]/;

/**
 * Check a candidate password against the credential policy.
 *
 * @param password The candidate (not trimmed: spaces are characters like any other).
 * @returns The first rule it breaks, as a sentence for the form, or `null` when it is acceptable.
 */
export function validatePassword(password: unknown): string | null {
  if (typeof password !== 'string' || password.length < PASSWORD_POLICY_MIN_LENGTH) {
    return 'Password must be at least 8 characters long';
  }
  if (Buffer.byteLength(password, 'utf8') > PASSWORD_POLICY_MAX_LENGTH) {
    return 'Password must be at most 72 bytes long';
  }
  if (!/[A-Z]/.test(password)) return 'Password must contain at least one uppercase letter';
  if (!/[a-z]/.test(password)) return 'Password must contain at least one lowercase letter';
  if (!PASSWORD_SYMBOL_PATTERN.test(password)) {
    return 'Password must contain at least one number or special character';
  }
  return null;
}
