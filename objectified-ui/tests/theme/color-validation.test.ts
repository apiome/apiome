import { tryParseCssColor } from '@lib/theme/color-validation';

describe('tryParseCssColor', () => {
  it('accepts hex shorthand and long form', () => {
    expect(tryParseCssColor('#fff')).toBeTruthy();
    expect(tryParseCssColor('#6366f1')).toBeTruthy();
  });

  it('returns null for empty input', () => {
    expect(tryParseCssColor('')).toBeNull();
    expect(tryParseCssColor('   ')).toBeNull();
  });
});
