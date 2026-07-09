/**
 * Unit tests for the mock usage sparkline series builder (#4443, SIM-2.2).
 *
 * The builder must turn REST `dailyRollups` rows into chronological, zero-filled,
 * fixed-length per-version series, summing duplicates and ignoring rows outside the
 * window or with malformed data.
 */

import {
  buildMockUsageSeries,
  mockUsageSeriesKey,
  MOCK_USAGE_WINDOW_DAYS,
  type MockUsageRollup,
} from '../src/app/utils/mock-usage-series';

/** Fixed "today" so tests are deterministic regardless of run date. */
const TODAY = new Date(Date.UTC(2026, 6, 9)); // 2026-07-09

const row = (overrides: Partial<MockUsageRollup>): MockUsageRollup => ({
  usageDate: '2026-07-09',
  projectSlug: 'petstore',
  versionLabel: '1.0.0',
  requestCount: 1,
  ...overrides,
});

describe('mockUsageSeriesKey', () => {
  it('joins project slug and version label', () => {
    expect(mockUsageSeriesKey('petstore', '1.0.0')).toBe('petstore/1.0.0');
  });
});

describe('buildMockUsageSeries', () => {
  it('returns an empty map for no rollups', () => {
    expect(buildMockUsageSeries([], { today: TODAY }).size).toBe(0);
  });

  it('zero-fills a full window with today last', () => {
    const series = buildMockUsageSeries(
      [row({ usageDate: '2026-07-09', requestCount: 7 }), row({ usageDate: '2026-07-08', requestCount: 3 })],
      { today: TODAY }
    );
    const values = series.get('petstore/1.0.0');
    expect(values).toHaveLength(MOCK_USAGE_WINDOW_DAYS);
    expect(values![MOCK_USAGE_WINDOW_DAYS - 1]).toBe(7); // today
    expect(values![MOCK_USAGE_WINDOW_DAYS - 2]).toBe(3); // yesterday
    expect(values!.slice(0, MOCK_USAGE_WINDOW_DAYS - 2).every((v) => v === 0)).toBe(true);
  });

  it('respects a custom window length', () => {
    const series = buildMockUsageSeries([row({ usageDate: '2026-07-03', requestCount: 5 })], {
      days: 7,
      today: TODAY,
    });
    // 2026-07-03 is 6 days before today → index 0 of a 7-day window.
    expect(series.get('petstore/1.0.0')).toEqual([5, 0, 0, 0, 0, 0, 0]);
  });

  it('groups by project slug and version label independently', () => {
    const series = buildMockUsageSeries(
      [
        row({ requestCount: 2 }),
        row({ versionLabel: '2.0.0', requestCount: 9 }),
        row({ projectSlug: 'orders', requestCount: 4 }),
      ],
      { days: 3, today: TODAY }
    );
    expect(series.get('petstore/1.0.0')).toEqual([0, 0, 2]);
    expect(series.get('petstore/2.0.0')).toEqual([0, 0, 9]);
    expect(series.get('orders/1.0.0')).toEqual([0, 0, 4]);
  });

  it('sums duplicate coordinates', () => {
    const series = buildMockUsageSeries([row({ requestCount: 2 }), row({ requestCount: 5 })], {
      days: 3,
      today: TODAY,
    });
    expect(series.get('petstore/1.0.0')).toEqual([0, 0, 7]);
  });

  it('ignores rows outside the window', () => {
    const series = buildMockUsageSeries(
      [
        row({ usageDate: '2026-06-09', requestCount: 8 }), // 30 days ago — outside a 30-day window
        row({ usageDate: '2026-07-10', requestCount: 8 }), // future
      ],
      { today: TODAY }
    );
    expect(series.size).toBe(0);
  });

  it('ignores malformed dates and non-finite or negative counts', () => {
    const series = buildMockUsageSeries(
      [
        row({ usageDate: 'not-a-date' }),
        row({ requestCount: Number.NaN }),
        row({ requestCount: -3 }),
        row({ requestCount: 6 }),
      ],
      { days: 2, today: TODAY }
    );
    expect(series.get('petstore/1.0.0')).toEqual([0, 6]);
  });

  it('accepts ISO datetime strings by reading the date part', () => {
    const series = buildMockUsageSeries([row({ usageDate: '2026-07-08T00:00:00Z', requestCount: 4 })], {
      days: 2,
      today: TODAY,
    });
    expect(series.get('petstore/1.0.0')).toEqual([4, 0]);
  });
});
