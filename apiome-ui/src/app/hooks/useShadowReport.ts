'use client';

import * as React from 'react';

import { reportQuery, type ShadowItem, type ShadowReport } from '@lib/shadow-report';
import type { ConnectorItemAction } from '@lib/connector-item-actions';

/** The report filters: one connector id and one environment, either may be empty. */
export interface ShadowReportFilters {
  connector: string | null;
  environment: string | null;
}

/** What a row action came back with. */
export interface ShadowActionResult {
  ok: boolean;
  /** REST's message on a failure. */
  error?: string;
  /** The response body (the item, or the run for an import). */
  body?: Record<string, unknown>;
}

/**
 * Read the shadow-API report and act on its rows (CDG-1.6, #5957).
 *
 * The report is read through `/api/connectors/shadow-report` whenever the filters change. A row
 * action posts to `/api/connectors/{id}/items/{itemId}/{action}` and, when it succeeds, reads the
 * report again, so the row moves to the section it now belongs in.
 *
 * @param filters - The current filters.
 * @param enabled - False until a tenant is known.
 * @returns The report, its loading and error state, `refresh`, and `act`.
 */
export function useShadowReport(filters: ShadowReportFilters, enabled = true) {
  const [report, setReport] = React.useState<ShadowReport | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const request = React.useRef(0);
  const query = reportQuery(filters);

  const refresh = React.useCallback(async () => {
    if (!enabled) return;
    const ticket = ++request.current;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`/api/connectors/shadow-report${query}`, { cache: 'no-store' });
      const body = await response.json().catch(() => ({}));
      if (ticket !== request.current) return;
      if (!response.ok) {
        setError(
          typeof body?.error === 'string'
            ? body.error
            : 'The shadow-API report could not be read. Try again.'
        );
        return;
      }
      setReport(body as ShadowReport);
    } catch {
      if (ticket === request.current) setError('The shadow-API report could not be read. Try again.');
    } finally {
      if (ticket === request.current) setLoading(false);
    }
  }, [enabled, query]);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  const act = React.useCallback(
    async (
      item: Pick<ShadowItem, 'connectorId' | 'itemId'>,
      action: ConnectorItemAction,
      payload?: Record<string, unknown>
    ): Promise<ShadowActionResult> => {
      try {
        const response = await fetch(
          `/api/connectors/${encodeURIComponent(item.connectorId)}/items/${encodeURIComponent(item.itemId)}/${action}`,
          {
            method: 'POST',
            headers: payload ? { 'Content-Type': 'application/json' } : undefined,
            body: payload ? JSON.stringify(payload) : undefined,
          }
        );
        const body = await response.json().catch(() => ({}));
        if (!response.ok) {
          return {
            ok: false,
            error: typeof body?.error === 'string' ? body.error : 'The action did not go through. Try again.',
          };
        }
        void refresh();
        return { ok: true, body };
      } catch {
        return { ok: false, error: 'The action did not go through. Check your connection and try again.' };
      }
    },
    [refresh]
  );

  return { report, loading, error, refresh, act };
}
