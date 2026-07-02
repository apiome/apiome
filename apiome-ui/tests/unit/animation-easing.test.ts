import { describe, it, expect } from '@jest/globals';
import { easeOutCubic } from '../../lib/animation-easing';

describe('easeOutCubic', () => {
  it('maps endpoints to 0 and 1', () => {
    expect(easeOutCubic(0)).toBe(0);
    expect(easeOutCubic(1)).toBe(1);
  });

  it('clamps input to [0, 1]', () => {
    expect(easeOutCubic(-1)).toBe(0);
    expect(easeOutCubic(2)).toBe(1);
  });

  it('is monotonic non-decreasing on [0, 1]', () => {
    let prev = easeOutCubic(0);
    for (let i = 1; i <= 100; i += 1) {
      const x = i / 100;
      const next = easeOutCubic(x);
      expect(next).toBeGreaterThanOrEqual(prev);
      prev = next;
    }
  });
});
