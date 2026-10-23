/**
 * The shared credential password policy (SGN-1.1, #5650) — used by email sign-up and Change
 * password — and its agreement with the strength meter's requirement list.
 */
import { PASSWORD_POLICY_MAX_LENGTH, validatePassword } from '../lib/auth/password-policy';
import { PASSWORD_REQUIREMENTS } from '../src/app/components/ade/account/passwordStrength';

describe('validatePassword', () => {
  it.each([
    [undefined, 'Password must be at least 8 characters long'],
    ['', 'Password must be at least 8 characters long'],
    ['Ab1defg', 'Password must be at least 8 characters long'],
    ['abcdefg1', 'Password must contain at least one uppercase letter'],
    ['ABCDEFG1', 'Password must contain at least one lowercase letter'],
    ['Abcdefgh', 'Password must contain at least one number or special character'],
  ])('refuses %p', (password, message) => {
    expect(validatePassword(password)).toBe(message);
  });

  it.each(['Abcdefg1', 'Abcdefg!', 'Correct Horse 9'])('accepts %p', (password) => {
    expect(validatePassword(password)).toBeNull();
  });

  it('refuses a password bcrypt would truncate', () => {
    expect(validatePassword(`Ab1${'x'.repeat(PASSWORD_POLICY_MAX_LENGTH)}`)).toBe(
      'Password must be at most 72 bytes long'
    );
    // Multi-byte characters count by bytes, not characters.
    expect(validatePassword(`Ab1${'é'.repeat(35)}`)).toBe('Password must be at most 72 bytes long');
  });

  it('agrees with the strength meter: every requirement met ⇔ accepted (within the length cap)', () => {
    const samples = ['Abcdefg1', 'abcdefg1', 'ABCDEFG1', 'Abcdefgh', 'Ab1', 'Zz!zzzzz', 'aaaaaaaa'];
    for (const sample of samples) {
      const meterSaysOk = PASSWORD_REQUIREMENTS.every((requirement) => requirement.test(sample));
      expect(validatePassword(sample) === null).toBe(meterSaysOk);
    }
  });
});
