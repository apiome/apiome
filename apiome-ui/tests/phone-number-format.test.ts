/**
 * Phone-number shape helpers for SMS two-factor (OLO-9.51 #5071).
 */

import {
  isE164PhoneNumber,
  maskPhoneNumber,
  normalizePhoneNumber,
} from '@lib/auth/phone-number-format';

describe('normalizePhoneNumber', () => {
  it('drops spaces, dots, dashes and parentheses', () => {
    expect(normalizePhoneNumber(' +1 (415) 555-0123 ')).toBe('+14155550123');
    expect(normalizePhoneNumber('+44.20.7946.0958')).toBe('+442079460958');
  });

  it('turns a 00 international prefix into +', () => {
    expect(normalizePhoneNumber('0049 30 123456')).toBe('+4930123456');
  });

  it('does not guess a country code', () => {
    expect(normalizePhoneNumber('415 555 0123')).toBe('4155550123');
  });
});

describe('isE164PhoneNumber', () => {
  it.each(['+14155550123', '+442079460958', '+4930123456'])('accepts %s', (value) => {
    expect(isE164PhoneNumber(value)).toBe(true);
  });

  it.each([
    '4155550123',
    '+0123456789',
    '+1234567',
    '+1234567890123456',
    '+1 415 555 0123',
    '',
    null,
    42,
  ])('refuses %p', (value) => {
    expect(isE164PhoneNumber(value)).toBe(false);
  });
});

describe('maskPhoneNumber', () => {
  it('keeps only the last four digits', () => {
    expect(maskPhoneNumber('+14155550123')).toBe('•••• 0123');
  });

  it('answers empty for a missing or too-short number', () => {
    expect(maskPhoneNumber(null)).toBe('');
    expect(maskPhoneNumber(undefined)).toBe('');
    expect(maskPhoneNumber('+12')).toBe('');
  });
});
