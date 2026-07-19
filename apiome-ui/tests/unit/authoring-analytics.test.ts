/**
 * Analytics state resolution and chart summaries (UXE-1.3).
 *
 * Two roadmap section 28.4 requirements are enforced here rather than in the
 * renderer: low-volume data is suppressed by a privacy threshold, and every
 * chart has a text equivalent. The distinction between `empty` and `threshold`
 * is the point — one says there is nothing, the other says there is something
 * we will not show, and conflating them either misleads or leaks.
 */

import {
  AUTHORING_PRIVACY_THRESHOLD,
  describeAuthoringAnalyticsState,
  formatAuthoringMetric,
  resolveAuthoringAnalyticsState,
  summarizeAuthoringSeries,
  type AuthoringAnalyticsSeries,
  type AuthoringAnalyticsState,
} from '../../lib/authoring/analytics';

/**
 * Build a series from bare values.
 *
 * @param values - One value per bucket.
 */
function series(...values: number[]): AuthoringAnalyticsSeries {
  return {
    id: 'views',
    label: 'Page views',
    unit: 'views',
    points: values.map((value, index) => ({ label: `2026-07-${10 + index}`, value })),
  };
}

describe('resolveAuthoringAnalyticsState', () => {
  it('reports an error ahead of everything else', () => {
    expect(resolveAuthoringAnalyticsState(series(100), { error: true, loading: true })).toBe('error');
  });

  it('reports loading before inspecting the data', () => {
    expect(resolveAuthoringAnalyticsState(undefined, { loading: true })).toBe('loading');
  });

  it('reports empty when there is no series at all', () => {
    expect(resolveAuthoringAnalyticsState(undefined)).toBe('empty');
  });

  it('reports empty when the series has no buckets', () => {
    expect(resolveAuthoringAnalyticsState(series())).toBe('empty');
  });

  it('suppresses a series below the privacy threshold', () => {
    expect(resolveAuthoringAnalyticsState(series(1, 2))).toBe('threshold');
  });

  it('distinguishes suppression from absence, which mean different things', () => {
    expect(resolveAuthoringAnalyticsState(series(1))).not.toBe(
      resolveAuthoringAnalyticsState(series())
    );
  });

  it('applies the threshold to the total, not to each bucket', () => {
    // Every bucket is below the threshold, but the period as a whole is not, so
    // there is nothing identifying about showing it.
    const spread = series(...Array.from({ length: 10 }, () => 2));

    expect(spread.points.every((point) => point.value < AUTHORING_PRIVACY_THRESHOLD)).toBe(true);
    expect(resolveAuthoringAnalyticsState(spread)).toBe('ready');
  });

  it('honours a caller-supplied threshold', () => {
    expect(resolveAuthoringAnalyticsState(series(5), { threshold: 3 })).toBe('ready');
    expect(resolveAuthoringAnalyticsState(series(5), { threshold: 100 })).toBe('threshold');
  });
});

describe('summarizeAuthoringSeries', () => {
  it('describes an empty series without inventing statistics', () => {
    const summary = summarizeAuthoringSeries(series());

    expect(summary).toMatchObject({ total: 0, min: 0, max: 0, average: 0, direction: 'flat' });
    expect(summary.description).toMatch(/no data/i);
  });

  it('computes total, range and mean', () => {
    expect(summarizeAuthoringSeries(series(10, 20, 30))).toMatchObject({
      total: 60,
      min: 10,
      max: 30,
      average: 20,
    });
  });

  it('reports direction as a word, so a trend is not colour-only', () => {
    expect(summarizeAuthoringSeries(series(10, 30)).direction).toBe('up');
    expect(summarizeAuthoringSeries(series(30, 10)).direction).toBe('down');
    expect(summarizeAuthoringSeries(series(10, 99, 10)).direction).toBe('flat');
  });

  it('computes the change across the period', () => {
    expect(summarizeAuthoringSeries(series(100, 150)).changePercent).toBe(50);
    expect(summarizeAuthoringSeries(series(100, 50)).changePercent).toBe(-50);
  });

  it('omits the percentage when the period starts at zero, which has no meaningful ratio', () => {
    const summary = summarizeAuthoringSeries(series(0, 40));

    expect(summary.changePercent).toBeUndefined();
    expect(summary.direction).toBe('up');
    expect(summary.description).not.toMatch(/Infinity|NaN/);
  });

  it('names the peak bucket, which is what a reader takes from the shape', () => {
    expect(summarizeAuthoringSeries(series(10, 90, 20)).description).toContain('2026-07-11');
  });

  it('produces a description usable as the chart alternative text', () => {
    const description = summarizeAuthoringSeries(series(10, 20, 30)).description;

    expect(description).toContain('Page views');
    expect(description).toContain('60 views');
    expect(description).toMatch(/up over the period/);
  });
});

describe('formatAuthoringMetric', () => {
  it('separates thousands', () => {
    expect(formatAuthoringMetric(1240, 'requests')).toBe('1,240 requests');
  });

  it.each([
    [98, '%', '98%'],
    [312, 'ms', '312ms'],
    [4, 's', '4s'],
  ])('suffixes %s directly with %s', (value, unit, expected) => {
    expect(formatAuthoringMetric(value, unit)).toBe(expected);
  });
});

describe('describeAuthoringAnalyticsState', () => {
  it.each(['loading', 'ready', 'empty', 'threshold', 'error'] as AuthoringAnalyticsState[])(
    'explains %s with a title and a sentence',
    (state) => {
      const copy = describeAuthoringAnalyticsState(state);

      expect(copy.title).toBeTruthy();
      expect(copy.description).toBeTruthy();
    }
  );

  it('tells an empty and a suppressed panel apart in words, not only in state', () => {
    expect(describeAuthoringAnalyticsState('empty').description).not.toBe(
      describeAuthoringAnalyticsState('threshold').description
    );
    expect(describeAuthoringAnalyticsState('threshold').description).toMatch(/identification|privacy/i);
  });
});
