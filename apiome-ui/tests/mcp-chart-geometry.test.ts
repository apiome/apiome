/**
 * Unit tests for the chart-kit geometry helpers (V2-MCP-28.3 / MCAT-14.3).
 *
 * These are the pure, React-free math functions the SVG chart primitives lay themselves out with.
 * Exercising them directly keeps the components declarative and proves the edge cases the charts
 * rely on (empty series, single value, full-ring arcs, non-finite guards).
 */
import {
  clamp,
  maxValue,
  sumValues,
  sparklinePoints,
  pointsToPath,
  polarToCartesian,
  describeAnnularArc,
  describeArc,
  radarPoints,
  polygonPoints,
  intensity,
} from '../src/app/components/ui/mcp/charts/chartGeometry';

describe('clamp', () => {
  it('bounds a value into [min, max]', () => {
    expect(clamp(5, 0, 10)).toBe(5);
    expect(clamp(-3, 0, 10)).toBe(0);
    expect(clamp(42, 0, 10)).toBe(10);
  });

  it('returns min for a non-finite value (safety net)', () => {
    expect(clamp(Number.NaN, 2, 10)).toBe(2);
    expect(clamp(Number.POSITIVE_INFINITY, 2, 10)).toBe(2);
  });
});

describe('maxValue', () => {
  it('returns the largest finite value', () => {
    expect(maxValue([3, 9, 4])).toBe(9);
  });

  it('ignores non-finite entries and defaults empty to 0', () => {
    expect(maxValue([Number.NaN, 5, Number.POSITIVE_INFINITY])).toBe(5);
    expect(maxValue([])).toBe(0);
  });
});

describe('sumValues', () => {
  it('sums only finite, positive values', () => {
    expect(sumValues([1, 2, 3])).toBe(6);
    expect(sumValues([1, -2, 3, Number.NaN])).toBe(4);
    expect(sumValues([])).toBe(0);
  });
});

describe('sparklinePoints', () => {
  it('returns no points for an empty series', () => {
    expect(sparklinePoints([], 120, 40, 3)).toEqual([]);
  });

  it('places a single value on a centered mid-line at the top of its own domain', () => {
    const pts = sparklinePoints([5], 120, 40, 3);
    expect(pts).toHaveLength(1);
    // innerW = 114 → centered x = 3 + 57 = 60; v == domainMax → y at top padding
    expect(pts[0].x).toBeCloseTo(60);
    expect(pts[0].y).toBeCloseTo(3);
  });

  it('maps the low value to the bottom and the high value to the top', () => {
    const pts = sparklinePoints([0, 10], 120, 40, 3);
    expect(pts[0].y).toBeGreaterThan(pts[1].y); // 0 sits lower (larger y) than 10
    expect(pts[0].x).toBeCloseTo(3);
    expect(pts[1].x).toBeCloseTo(117);
  });

  it('honors a pinned domainMax', () => {
    const [p] = sparklinePoints([50], 120, 40, 3, 100);
    // 50 of 100 → halfway: y = 3 + 34 * 0.5 = 20
    expect(p.y).toBeCloseTo(20);
  });
});

describe('pointsToPath', () => {
  it('emits an M then L commands', () => {
    expect(pointsToPath([{ x: 0, y: 0 }, { x: 10, y: 5 }])).toBe('M 0.00 0.00 L 10.00 5.00');
  });
});

describe('polarToCartesian', () => {
  it('places 0° at 12 o’clock (straight up)', () => {
    const p = polarToCartesian(50, 50, 10, 0);
    expect(p.x).toBeCloseTo(50);
    expect(p.y).toBeCloseTo(40);
  });

  it('places 90° at 3 o’clock (right)', () => {
    const p = polarToCartesian(50, 50, 10, 90);
    expect(p.x).toBeCloseTo(60);
    expect(p.y).toBeCloseTo(50);
  });
});

describe('describeAnnularArc', () => {
  it('returns empty for a non-positive sweep', () => {
    expect(describeAnnularArc(60, 60, 30, 50, 90, 90)).toBe('');
    expect(describeAnnularArc(60, 60, 30, 50, 90, 30)).toBe('');
  });

  it('emits a closed wedge path for a partial sweep', () => {
    const d = describeAnnularArc(60, 60, 30, 50, 0, 90);
    expect(d.startsWith('M')).toBe(true);
    expect(d.trimEnd().endsWith('Z')).toBe(true);
    expect(d).toContain('A 50 50'); // outer arc
    expect(d).toContain('A 30 30'); // inner arc
  });

  it('splits a full ring into two arcs', () => {
    const d = describeAnnularArc(60, 60, 30, 50, 0, 360);
    expect((d.match(/M /g) ?? []).length).toBe(2);
  });
});

describe('describeArc', () => {
  it('returns empty for a non-positive sweep', () => {
    expect(describeArc(60, 60, 46, 0, 0)).toBe('');
  });

  it('emits an open arc for a positive sweep', () => {
    const d = describeArc(60, 60, 46, -135, 135);
    expect(d.startsWith('M')).toBe(true);
    expect(d).toContain('A 46 46');
    expect(d).not.toContain('Z');
  });
});

describe('radarPoints', () => {
  it('returns no points for an empty series', () => {
    expect(radarPoints([], 100, 70, 70, 52)).toEqual([]);
  });

  it('scales each vertex by value/max along its spoke', () => {
    // First axis points straight up; a full-value vertex sits at cy - r.
    const [first] = radarPoints([100, 0, 0], 100, 70, 70, 52);
    expect(first.x).toBeCloseTo(70);
    expect(first.y).toBeCloseTo(18);
  });
});

describe('polygonPoints', () => {
  it('joins points into an SVG points string', () => {
    expect(polygonPoints([{ x: 1, y: 2 }, { x: 3, y: 4 }])).toBe('1.00,2.00 3.00,4.00');
  });
});

describe('intensity', () => {
  it('normalizes a value into [0, 1] against max', () => {
    expect(intensity(5, 10)).toBeCloseTo(0.5);
    expect(intensity(20, 10)).toBe(1);
    expect(intensity(-4, 10)).toBe(0);
    expect(intensity(Number.NaN, 10)).toBe(0);
  });
});
