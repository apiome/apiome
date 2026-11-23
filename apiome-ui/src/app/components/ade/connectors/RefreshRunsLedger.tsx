'use client';

import * as React from 'react';
import Link from 'next/link';
import { RefreshCw } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { connectorKindLabel } from '@lib/connector-kinds';
import { listRefreshRuns, runOutcome, type RefreshRun } from '@lib/connectors-api';
import { formatTotal } from '@lib/cursor-pages';
import { useCursorPages } from '@/app/hooks/useCursorPages';

/**
 * The refresh ledger: Git refresh jobs and connector runs, interleaved newest first (CDG-1.7, #5958).
 *
 * One component for both places a run is read. A connector's **Runs** tab passes `connectorId` and
 * sees that connector's runs; the Repositories page passes nothing and sees every run, each with a
 * **source** badge (Git or Connector) saying where it came from.
 *
 * @param props.connectorId - Only this connector's runs.
 * @param props.limit - Rows per page.
 * @param props.refreshKey - Change it to read the ledger again (after a sync).
 * @param props.title - The section heading.
 */
export function RefreshRunsLedger({
  connectorId,
  limit = 25,
  refreshKey = 0,
  title = 'Recent runs',
}: {
  connectorId?: string;
  limit?: number;
  refreshKey?: number;
  title?: string;
}) {
  // The ledger pages by cursor (#7196): the newest page first, older ones on "Load more". Only
  // the first page asks for the count.
  const pages = useCursorPages<RefreshRun>({
    key: `${connectorId ?? ''}:${limit}`,
    getRowId: (run) => run.id,
    errorMessage: 'The runs could not be read. Try again.',
    load: async ({ cursor, offset, first }) => {
      const page = await listRefreshRuns({
        connector: connectorId,
        limit,
        cursor,
        offset,
        includeTotal: first,
      });
      return { rows: page.runs, page: page.page };
    },
  });
  const { total, loading, hasMore, loadingMore } = pages;
  const error = pages.error ?? pages.moreError;
  // Nothing is drawn until a read has answered: a failed first read is not "no runs".
  const runs = loading || (pages.error !== null && pages.rows.length === 0) ? null : pages.rows;
  const load = pages.reload;
  const shownTotal = formatTotal(total);

  // A sync elsewhere on the page bumps `refreshKey`: read the newest page again, keeping the rows
  // on screen until it answers.
  const seenRefreshKey = React.useRef(refreshKey);
  React.useEffect(() => {
    if (seenRefreshKey.current === refreshKey) return;
    seenRefreshKey.current = refreshKey;
    load();
  }, [refreshKey, load]);

  return (
    <section className="cnx-ledger" aria-labelledby="cnx-ledger-title" data-testid="refresh-runs-ledger">
      <div className="cnx-ledger__head">
        <h2 id="cnx-ledger-title" className="cnx-section-title">
          {title}
        </h2>
        <Button variant="ghost" size="sm" onClick={() => void load()} disabled={loading} data-testid="refresh-runs-reload">
          <RefreshCw aria-hidden />
          Refresh
        </Button>
      </div>
      {error ? (
        <Alert
          variant="error"
          actions={
            <Button variant="ghost" size="sm" onClick={() => void load()}>
              Try again
            </Button>
          }
        >
          {error}
        </Alert>
      ) : null}
      {runs && runs.length === 0 ? (
        <p className="cnx-note" data-testid="refresh-runs-empty">
          {connectorId ? 'This connector has not synced. Click “Sync now” to run it.' : 'Nothing has refreshed in this workspace.'}
        </p>
      ) : null}
      {runs && runs.length > 0 ? (
        <div className="cnx-table-wrap">
          <table className="cnx-table">
            <thead>
              <tr>
                <th scope="col">Source</th>
                <th scope="col">What</th>
                <th scope="col">Status</th>
                <th scope="col">Outcome</th>
                <th scope="col">Started</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id} data-testid={`refresh-run-${run.id}`}>
                  <td>
                    <Badge variant={run.source === 'connector' ? 'violet' : 'neutral'} data-testid="refresh-run-source">
                      {run.source === 'connector' ? 'Connector' : 'Git'}
                    </Badge>
                  </td>
                  <td>
                    {run.source === 'connector' ? (
                      <>
                        <Link href={`/ade/dashboard/connectors/${encodeURIComponent(run.connectorId ?? '')}`} className="cnx-link">
                          {run.connectorName ?? run.connectorId}
                        </Link>
                        <span className="hive-meta">
                          {connectorKindLabel(run.connectorKind)}
                          {run.trigger ? ` · ${run.trigger}` : ''}
                        </span>
                      </>
                    ) : (
                      <>
                        <span className="cnx-name">{run.repositoryName ?? run.repositoryId}</span>
                        <span className="hive-meta cnx-mono">
                          {run.branch}
                          {run.path ? ` · ${run.path}` : ''}
                        </span>
                      </>
                    )}
                  </td>
                  <td>
                    <Badge status={run.status} dot>
                      {run.status}
                    </Badge>
                  </td>
                  <td>
                    {runOutcome(run)}
                    {run.errorMessage ? <span className="hive-meta">{run.errorMessage}</span> : null}
                  </td>
                  <td className="cnx-mono">{run.startedAt ? new Date(run.startedAt).toLocaleString() : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {hasMore ? (
            <div className="flex flex-wrap items-center gap-2">
              <p className="cnx-note" data-testid="refresh-runs-shown">
                Showing the newest {runs.length.toLocaleString('en-US')}
                {shownTotal ? ` of ${shownTotal}` : ''} runs.
              </p>
              <Button
                variant="outline"
                size="sm"
                onClick={pages.loadMore}
                disabled={loadingMore}
                title={loadingMore ? 'Loading the next page' : undefined}
                data-testid="refresh-runs-load-more"
              >
                {loadingMore ? 'Loading…' : 'Load more'}
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
