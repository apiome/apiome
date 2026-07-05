/**
 * Tests for export fidelity preview helpers — MFX-7.2 (#3861).
 */

import { describe, expect, it } from 'vitest';
import {
  fidelityChips,
  kindBadgeClass,
  kindLabel,
  ringGeometry,
  ringStrokeClass,
  sortReportItemsWorstFirst,
  type LossItem,
} from '../exportFidelityPreview';
import type { TargetFidelitySummary } from '../publicExport';

const SUMMARY: TargetFidelitySummary = {
  tier: 'lossy',
  preserved_percent: 64,
  total: 58,
  preserved: 51,
  dropped: 3,
  approximated: 2,
  synthesized: 2,
};

describe('sortReportItemsWorstFirst', () => {
  const items: LossItem[] = [
    { construct: 'User.name', kind: 'ok', severity: 'info', message: 'OK' },
    { construct: 'User.email', kind: 'drop', severity: 'warn', message: 'Dropped' },
    { construct: 'GET /pets', kind: 'approx', severity: 'warn', message: 'Approx' },
    { construct: 'field.num', kind: 'synth', severity: 'info', message: 'Synth' },
  ];

  it('orders drop before approx before synth before ok', () => {
    const sorted = sortReportItemsWorstFirst(items);
    expect(sorted.map((i) => i.kind)).toEqual(['drop', 'approx', 'synth', 'ok']);
  });

  it('does not mutate the input', () => {
    const copy = [...items];
    sortReportItemsWorstFirst(items);
    expect(items).toEqual(copy);
  });
});

describe('kindLabel and kindBadgeClass', () => {
  it('uppercases kind labels', () => {
    expect(kindLabel('drop')).toBe('DROP');
    expect(kindLabel('ok')).toBe('OK');
  });

  it('maps kinds to distinct palette classes', () => {
    expect(kindBadgeClass('drop')).toContain('rose');
    expect(kindBadgeClass('approx')).toContain('amber');
    expect(kindBadgeClass('synth')).toContain('violet');
    expect(kindBadgeClass('ok')).toContain('emerald');
  });
});

describe('ringGeometry', () => {
  it('computes full circumference at 100%', () => {
    const ring = ringGeometry(100, 40);
    expect(ring.dashOffset).toBeCloseTo(0, 5);
    expect(ring.circumference).toBeCloseTo(2 * Math.PI * 40, 5);
  });

  it('hides the full ring at 0%', () => {
    const ring = ringGeometry(0, 40);
    expect(ring.dashOffset).toBeCloseTo(ring.circumference, 5);
  });

  it('clamps out-of-range percentages', () => {
    expect(ringGeometry(-10, 40).dashOffset).toBeCloseTo(ringGeometry(0, 40).dashOffset, 5);
    expect(ringGeometry(150, 40).dashOffset).toBeCloseTo(ringGeometry(100, 40).dashOffset, 5);
  });
});

describe('ringStrokeClass', () => {
  it('maps tiers to emerald/amber/rose strokes', () => {
    expect(ringStrokeClass('lossless')).toContain('emerald');
    expect(ringStrokeClass('lossy')).toContain('amber');
    expect(ringStrokeClass('types-only')).toContain('rose');
  });
});

describe('fidelityChips', () => {
  it('emits non-zero loss chips then always includes clean', () => {
    const chips = fidelityChips(SUMMARY);
    expect(chips.map((c) => c.key)).toEqual(['dropped', 'approximated', 'synthesized', 'preserved']);
    expect(chips.map((c) => c.count)).toEqual([3, 2, 2, 51]);
  });

  it('shows only clean for a lossless summary', () => {
    const chips = fidelityChips({
      tier: 'lossless',
      preserved_percent: 100,
      total: 10,
      preserved: 10,
      dropped: 0,
      approximated: 0,
      synthesized: 0,
    });
    expect(chips).toHaveLength(1);
    expect(chips[0].label).toBe('clean');
  });
});
