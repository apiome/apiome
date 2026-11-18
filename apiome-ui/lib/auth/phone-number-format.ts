/**
 * Phone-number shape helpers for SMS two-factor (OLO-9.51 #5071).
 *
 * Shared by the browser (Profile → Security) and the server (the phone-number guard and the SMS
 * sender), so both accept and show a number the same way. No dependencies, no I/O.
 *
 * apiome stores numbers in E.164 — `+`, a country code, then the subscriber number, 8 to 15 digits
 * in all and no leading zero (`+14155550123`). Nothing here checks that the number is *real*; the
 * code sent to it does that.
 */

/** E.164: a plus, a non-zero first digit, then 7–14 more digits. */
const E164_PATTERN = /^\+[1-9]\d{7,14}$/;

/**
 * Reduce what a person typed to the E.164 form apiome stores.
 *
 * Spaces, dots, dashes and parentheses are dropped (`+1 (415) 555-0123` → `+14155550123`); a
 * leading `00` international prefix becomes `+`. Anything else is left for
 * {@link isE164PhoneNumber} to refuse — a number without a country code is not guessed at.
 *
 * @param raw The number as typed.
 * @returns The cleaned-up number (not necessarily valid).
 */
export function normalizePhoneNumber(raw: string): string {
  const compact = raw.trim().replace(/[\s.\-()]/g, '');
  return compact.startsWith('00') ? `+${compact.slice(2)}` : compact;
}

/**
 * Whether a number is in E.164 form.
 *
 * @param value A number, already normalized with {@link normalizePhoneNumber}.
 * @returns `true` for `+` followed by 8–15 digits with a non-zero country code.
 */
export function isE164PhoneNumber(value: unknown): value is string {
  return typeof value === 'string' && E164_PATTERN.test(value);
}

/**
 * Hide all but the last four digits of a number, for showing it back to its owner.
 *
 * @param phoneNumber An E.164 number.
 * @returns e.g. `•••• 0123`; an empty string for a missing or too-short number.
 */
export function maskPhoneNumber(phoneNumber: string | null | undefined): string {
  if (typeof phoneNumber !== 'string') return '';
  const digits = phoneNumber.replace(/\D/g, '');
  if (digits.length < 4) return '';
  return `•••• ${digits.slice(-4)}`;
}
