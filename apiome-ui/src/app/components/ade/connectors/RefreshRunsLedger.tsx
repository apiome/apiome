'use client';

import * as React from 'react';
import Link from 'next/link';
import { RefreshCw } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { connectorKindLabel } from '@lib/connector-kinds';
import { listRefreshRuns, runOutcome, type RefreshRun } from '@lib/connectors-api';

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
  const [runs, setRuns] = React.useState<RefreshRun[] | null>(null);
  const [total, setTotal] = React.useState(0);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const page = await listRefreshRuns({ connector: connectorId, limit });
      setRuns(page.runs);
      setTotal(page.total);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The runs could not be read. Try again.');
    } finally {
      setLoading(false);
    }
  }, [connectorId, limit]);

  React.useEffect(() => {
    void load();
  }, [load, refreshKey]);

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
                        <span className="cnx-meta">
                          {connectorKindLabel(run.connectorKind)}
                          {run.trigger ? ` · ${run.trigger}` : ''}
                        </span>
                      </>
                    ) : (
                      <>
                        <span className="cnx-name">{run.repositoryName ?? run.repositoryId}</span>
                        <span className="cnx-meta cnx-mono">
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
                    {run.errorMessage ? <span className="cnx-meta">{run.errorMessage}</span> : null}
                  </td>
                  <td className="cnx-mono">{run.startedAt ? new Date(run.startedAt).toLocaleString() : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {total > runs.length ? (
            <p className="cnx-note">
              Showing the newest {runs.length} of {total} runs.
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
