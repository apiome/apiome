import { formatVersionWithPrefix } from '@/app/utils/version-display';

describe('formatVersionWithPrefix', () => {
  it('does not duplicate the "v" when the version already starts with one', () => {
    // Regression: "v1" rendered as "vv1" in the published versions list.
    expect(formatVersionWithPrefix('v1')).toBe('v1');
    expect(formatVersionWithPrefix('v1.0.0')).toBe('v1.0.0');
  });

  it('adds a "v" prefix when the version has none', () => {
    expect(formatVersionWithPrefix('1')).toBe('v1');
    expect(formatVersionWithPrefix('1.0.0')).toBe('v1.0.0');
    expect(formatVersionWithPrefix('2.3.4-beta')).toBe('v2.3.4-beta');
  });

  it('strips a single leading "v" only, case-insensitively', () => {
    expect(formatVersionWithPrefix('V2')).toBe('v2');
    expect(formatVersionWithPrefix('vNext')).toBe('vNext');
  });

  it('trims surrounding whitespace before formatting', () => {
    expect(formatVersionWithPrefix('  v1  ')).toBe('v1');
    expect(formatVersionWithPrefix('  1.0.0 ')).toBe('v1.0.0');
  });

  it('returns an empty string for empty/nullish input (no lone "v")', () => {
    expect(formatVersionWithPrefix('')).toBe('');
    expect(formatVersionWithPrefix('   ')).toBe('');
    expect(formatVersionWithPrefix(null)).toBe('');
    expect(formatVersionWithPrefix(undefined)).toBe('');
  });
});
