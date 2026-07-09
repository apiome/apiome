'use client';

/**
 * Hook fetching mock usage rollups for the dashboard sparklines (#4443, SIM-2.2).
 *
 * Loads `GET /api/mocks/usage` once per (enabled, projectSlug) change and groups the
 * daily rollups into per-version 30-day series. Usage stats are decorative — failures
 * degrade to the sparkline's empty state instead of surfacing an error to the user.
 */

import { useEffect, useState } from 'react';
import {
  buildMockUsageSeries,
  MOCK_USAGE_WINDOW_DAYS,
  type MockUsageRollup,
} from '../utils/mock-usage-series';

export interface UseMockUsageResult {
  /**
   * Per-version series keyed by `mockUsageSeriesKey(projectSlug, versionLabel)`;
   * `null` while loading or when the hook is disabled. A missing key after load
   * means the version had no usage in the window.
   */
  seriesByVersion: Map<string, number[]> | null;
}

/** State the hook keeps: which inputs a loaded series belongs to, so stale data is never served. */
interface LoadedSeries {
  key: string;
  series: Map<string, number[]>;
}

/**
 * Fetch 30-day mock usage series for the current tenant.
 *
 * @param options.enabled - skip fetching entirely when false (e.g. no tenant yet)
 * @param options.projectSlug - optional project filter forwarded to REST; omit for tenant-wide rows
 * @returns per-version usage series, `null` until loaded
 */
export function useMockUsage(options: { enabled: boolean; projectSlug?: string | null }): UseMockUsageResult {
  const { enabled, projectSlug } = options;
  const [loaded, setLoaded] = useState<LoadedSeries | null>(null);

  // Identifies the inputs a fetched series belongs to. While inputs and loaded.key
  // disagree (loading, input change, disabled), the hook reports `null` instead of
  // stale rows — no synchronous state reset in the effect needed.
  const seriesKey = enabled ? `${projectSlug ?? ''}` : null;

  useEffect(() => {
    if (seriesKey === null) return;

    let cancelled = false;

    const load = async () => {
      let series = new Map<string, number[]>();
      try {
        const params = new URLSearchParams({ days: String(MOCK_USAGE_WINDOW_DAYS) });
        if (projectSlug) params.set('projectSlug', projectSlug);
        const response = await fetch(`/api/mocks/usage?${params.toString()}`);
        const payload = await response.json().catch(() => null);
        if (response.ok && payload?.success) {
          const rollups = (payload.usage?.dailyRollups ?? []) as MockUsageRollup[];
          series = buildMockUsageSeries(rollups);
        }
      } catch (error) {
        console.error('Failed to load mock usage rollups:', error);
      }
      if (!cancelled) setLoaded({ key: seriesKey, series });
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [seriesKey, projectSlug]);

  return {
    seriesByVersion: seriesKey !== null && loaded?.key === seriesKey ? loaded.series : null,
  };
}
