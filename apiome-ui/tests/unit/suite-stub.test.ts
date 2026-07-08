import { describe, it, expect } from '@jest/globals';
import { getSuiteHomeCards, getSuiteNavItems } from '../../lib/suite-stub';

describe('suite-stub (OSS build)', () => {
  it('returns no suite nav items', () => {
    expect(getSuiteNavItems()).toEqual([]);
  });

  it('returns no suite home cards', () => {
    expect(getSuiteHomeCards()).toEqual([]);
  });
});
