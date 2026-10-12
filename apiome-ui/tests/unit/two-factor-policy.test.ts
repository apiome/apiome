/**
 * The two-factor sign-in policy (OLO-9.14, #5006).
 *
 * One module holds the numbers the server enforces and the screens quote, the shape of a backup
 * code, and the wording for the plugin's refusals. These tests pin all three.
 */
import {
  LOCKOUT_DURATION_SECONDS,
  LOCKOUT_MAX_FAILED_ATTEMPTS,
  LOCKOUT_MINUTES,
  TRUST_DEVICE_DAYS,
  TRUST_DEVICE_MAX_AGE_SECONDS,
  describeTwoFactorRefusal,
  isCompleteBackupCode,
  normalizeBackupCode,
} from '@lib/auth/two-factor-policy';

describe('policy constants', () => {
  it('trusts a device for thirty days', () => {
    expect(TRUST_DEVICE_DAYS).toBe(30);
    expect(TRUST_DEVICE_MAX_AGE_SECONDS).toBe(2_592_000);
  });

  it('locks the factor for fifteen minutes after ten consecutive failures', () => {
    expect(LOCKOUT_MAX_FAILED_ATTEMPTS).toBe(10);
    expect(LOCKOUT_MINUTES).toBe(15);
    expect(LOCKOUT_DURATION_SECONDS).toBe(900);
  });
});

describe('normalizeBackupCode', () => {
  it.each([
    ['ab12c-de34f', 'ab12c-de34f'],
    ['ab12cde34f', 'ab12c-de34f'],
    ['ab12c de34f', 'ab12c-de34f'],
    ['  ab12c-de34f\n', 'ab12c-de34f'],
    ['ab12c--de34f', 'ab12c-de34f'],
    ['1. ab12c-de34f', '1ab12-cde34'],
    ['ab12', 'ab12'],
    ['ab12c', 'ab12c'],
    ['ab12c-', 'ab12c'],
    ['ab12cd', 'ab12c-d'],
    ['', ''],
  ])('tidies %p to %p', (raw, expected) => {
    expect(normalizeBackupCode(raw)).toBe(expected);
  });

  it('never changes the case — backup codes are case-sensitive', () => {
    expect(normalizeBackupCode('Ab12C-dE34f')).toBe('Ab12C-dE34f');
  });

  it('keeps at most ten characters', () => {
    expect(normalizeBackupCode('ab12cde34fZZZZ')).toBe('ab12c-de34f');
  });
});

describe('isCompleteBackupCode', () => {
  it.each(['ab12c-de34f', 'ABCDE-12345', '00000-00000'])('accepts %s', (code) => {
    expect(isCompleteBackupCode(code)).toBe(true);
  });

  it.each(['', 'ab12c', 'ab12c-de34', 'ab12cde34f', 'ab12c-de34fg', 'ab12c_de34f', '123456'])(
    'refuses %p',
    (code) => {
      expect(isCompleteBackupCode(code)).toBe(false);
    }
  );
});

describe('describeTwoFactorRefusal', () => {
  const FALLBACK = 'That code was not accepted.';

  it('names the lockout and its length, and closes the screen', () => {
    const refusal = describeTwoFactorRefusal(
      { code: 'ACCOUNT_TEMPORARILY_LOCKED', message: 'server wording' },
      FALLBACK
    );
    expect(refusal.terminal).toBe(true);
    expect(refusal.text).toContain('locked for 15 minutes');
    expect(refusal.text).not.toContain('server wording');
  });

  it.each(['TOO_MANY_ATTEMPTS_REQUEST_NEW_CODE', 'INVALID_TWO_FACTOR_COOKIE'])(
    'closes the screen and sends the reader back to sign in for %s',
    (code) => {
      const refusal = describeTwoFactorRefusal({ code }, FALLBACK);
      expect(refusal.terminal).toBe(true);
      expect(refusal.text).toMatch(/sign in again/);
    }
  );

  it('says a backup code works once, and leaves the screen open', () => {
    const refusal = describeTwoFactorRefusal({ code: 'INVALID_BACKUP_CODE' }, FALLBACK);
    expect(refusal).toEqual({
      text: 'That backup code was not accepted. Each code works once — check it and try another.',
      terminal: false,
    });
  });

  it("passes on the server's sentence for a refusal it does not word itself", () => {
    expect(describeTwoFactorRefusal({ code: 'INVALID_CODE', message: 'Invalid code' }, FALLBACK)).toEqual({
      text: 'Invalid code',
      terminal: false,
    });
  });

  it.each([null, undefined, {}, { code: null, message: null }, { code: 'UNKNOWN', message: '' }])(
    'falls back for %p',
    (error) => {
      expect(describeTwoFactorRefusal(error, FALLBACK)).toEqual({ text: FALLBACK, terminal: false });
    }
  );
});
