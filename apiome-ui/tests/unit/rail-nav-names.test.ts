/**
 * The names a rail row carries once its maturity pill became a dot (HIVE-12.4, #5611).
 */

import { railNavItemName, railNavItemTitle } from '../../src/app/components/shell/RailNav';

describe('railNavItemName', () => {
  it('appends the pill, lower-cased, after a comma', () => {
    expect(railNavItemName({ label: 'Lint posture', pill: 'Preview' })).toBe('Lint posture, preview');
  });

  it('returns undefined without a pill, so the visible label stays the name', () => {
    expect(railNavItemName({ label: 'Home' })).toBeUndefined();
    expect(railNavItemName({ label: 'Home', pill: '' })).toBeUndefined();
  });
});

describe('railNavItemTitle', () => {
  it('joins the label and the pill with a middle dot', () => {
    expect(railNavItemTitle({ label: 'Lint posture', pill: 'Preview' })).toBe('Lint posture · Preview');
  });

  it('is the bare label without a pill', () => {
    expect(railNavItemTitle({ label: 'Home' })).toBe('Home');
  });
});
