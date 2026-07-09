/**
 * Mock usage sparkline series builder (#4443, SIM-2.2).
 *
 * Turns the REST `dailyRollups` payload from `GET /v1/mocks/{tenant}/usage` (#4420, SIM-1.5)
 * into per-version, chronological, zero-filled daily request-count series suitable for the
 * dashboard `<Sparkline>`.
 */

/** One daily rollup row as returned by the REST usage endpoint (camelCase serialization). */
export interface MockUsageRollup {
  /** UTC calendar day the requests were served, as `YYYY-MM-DD`. */
  usageDate: string;
  /** Slug of the project the mocked version belongs to. */
  projectSlug: string;
  /** Version label (e.g. `1.2.0`) of the mocked version. */
  versionLabel: string;
  /** Mock data-plane requests recorded on `usageDate`. */
  requestCount: number;
}

/** Default sparkline window: the ticket's "30-day usage" requirement. */
export const MOCK_USAGE_WINDOW_DAYS = 30;

const MS_PER_DAY = 24 * 60 * 60 * 1000;

/**
 * Map key for one version's series.
 *
 * @param projectSlug - project slug of the rollup rows
 * @param versionLabel - version label of the rollup rows
 * @returns stable `"{projectSlug}/{versionLabel}"` key
 */
export function mockUsageSeriesKey(projectSlug: string, versionLabel: string): string {
  return `${projectSlug}/${versionLabel}`;
}

/** Milliseconds at UTC midnight for a date, so day arithmetic ignores local timezones. */
function utcMidnight(date: Date): number {
  return Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate());
}

/** Parse a `YYYY-MM-DD` rollup date to UTC-midnight ms, or `null` when malformed. */
function parseUsageDate(value: string): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value ?? '');
  if (!match) return null;
  const ms = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return Number.isFinite(ms) ? ms : null;
}

/**
 * Build per-version daily usage series from raw rollup rows.
 *
 * Each series is chronological (oldest → today), exactly `days` entries long, with missing
 * days filled with 0. Rows outside the window, with malformed dates, or with non-finite
 * counts are skipped; duplicate coordinates are summed. Versions with no rows in the window
 * get no entry — callers should treat a missing key as "no usage" (empty sparkline state).
 *
 * @param rollups - `dailyRollups` rows from the usage endpoint
 * @param options.days - window length in days (default {@link MOCK_USAGE_WINDOW_DAYS})
 * @param options.today - "today" reference date, injectable for tests (default: now)
 * @returns map of {@link mockUsageSeriesKey} → zero-filled series of length `days`
 */
export function buildMockUsageSeries(
  rollups: readonly MockUsageRollup[],
  options?: { days?: number; today?: Date }
): Map<string, number[]> {
  const days = Math.max(1, options?.days ?? MOCK_USAGE_WINDOW_DAYS);
  const todayMs = utcMidnight(options?.today ?? new Date());
  const series = new Map<string, number[]>();

  for (const row of rollups) {
    if (!row || typeof row.projectSlug !== 'string' || typeof row.versionLabel !== 'string') continue;
    const count = Number(row.requestCount);
    if (!Number.isFinite(count) || count < 0) continue;
    const dateMs = parseUsageDate(row.usageDate);
    if (dateMs === null) continue;

    const daysAgo = Math.round((todayMs - dateMs) / MS_PER_DAY);
    if (daysAgo < 0 || daysAgo >= days) continue;

    const key = mockUsageSeriesKey(row.projectSlug, row.versionLabel);
    let values = series.get(key);
    if (!values) {
      values = new Array<number>(days).fill(0);
      series.set(key, values);
    }
    values[days - 1 - daysAgo] += count;
  }

  return series;
}
