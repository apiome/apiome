/**
 * Unit tests for the chart-kit token mapping (V2-MCP-28.3 / MCAT-14.3).
 *
 * Proves the "consumers pass domain values, primitives pick color" contract: every tone resolves to
 * Tailwind `fill-*`/`stroke-*`/`text-*` utilities (never a hex literal), unknown tones fall back to
 * neutral, and categorical assignment is stable and cyclic.
 */
import {
  chartSeriesStyle,
  chartCategoricalTone,
  chartCategoricalStyle,
  CHART_CATEGORICAL_ORDER,
  CHART_SURFACE,
  type ChartSeriesTone,
} from '../src/app/components/ui/mcp/charts/chartTokens';

const ALL_TONES: ChartSeriesTone[] = [
  'indigo',
  'emerald',
  'amber',
  'red',
  'blue',
  'violet',
  'green',
  'orange',
  'cyan',
  'pink',
  'neutral',
];

describe('chartSeriesStyle', () => {
  it('maps every tone to fill/stroke/text utility classes', () => {
    for (const tone of ALL_TONES) {
      const s = chartSeriesStyle(tone);
      expect(s.tone).toBe(tone);
      expect(s.fillClass).toMatch(/^fill-/);
      expect(s.strokeClass).toMatch(/^stroke-/);
      expect(s.textClass).toMatch(/^text-/);
    }
  });

  it('never emits a hex or rgb color literal', () => {
    for (const tone of ALL_TONES) {
      const s = chartSeriesStyle(tone);
      const joined = `${s.fillClass} ${s.strokeClass} ${s.textClass}`;
      expect(joined).not.toMatch(/#[0-9a-f]{3,6}|rgb|hsl/i);
    }
  });

  it('falls back to neutral for an unknown/nullish tone', () => {
    expect(chartSeriesStyle(null).tone).toBe('neutral');
    expect(chartSeriesStyle(undefined).tone).toBe('neutral');
    expect(chartSeriesStyle('chartreuse' as ChartSeriesTone).tone).toBe('neutral');
  });

  it('pairs each tone with dark-mode variants', () => {
    expect(chartSeriesStyle('indigo').fillClass).toContain('dark:');
  });
});

describe('chartCategoricalTone', () => {
  it('cycles through the categorical order', () => {
    expect(chartCategoricalTone(0)).toBe(CHART_CATEGORICAL_ORDER[0]);
    const n = CHART_CATEGORICAL_ORDER.length;
    expect(chartCategoricalTone(n)).toBe(CHART_CATEGORICAL_ORDER[0]);
    expect(chartCategoricalTone(n + 2)).toBe(CHART_CATEGORICAL_ORDER[2]);
  });

  it('handles negative and non-finite indices without escaping the palette', () => {
    expect(CHART_CATEGORICAL_ORDER).toContain(chartCategoricalTone(-1));
    expect(chartCategoricalTone(Number.NaN)).toBe(CHART_CATEGORICAL_ORDER[0]);
  });

  it('never auto-assigns the reserved neutral tone', () => {
    expect(CHART_CATEGORICAL_ORDER).not.toContain('neutral');
  });

  it('chartCategoricalStyle resolves the tone at an index', () => {
    expect(chartCategoricalStyle(1).tone).toBe(CHART_CATEGORICAL_ORDER[1]);
  });
});

describe('CHART_SURFACE', () => {
  it('exposes token classes for furniture, not literals', () => {
    const joined = Object.values(CHART_SURFACE).join(' ');
    expect(joined).not.toMatch(/#[0-9a-f]{3,6}|rgb|hsl/i);
    expect(CHART_SURFACE.trackStrokeClass).toMatch(/^stroke-/);
    expect(CHART_SURFACE.labelClass).toMatch(/^fill-/);
  });
});
