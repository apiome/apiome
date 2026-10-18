'use client';

import * as React from 'react';
import Link from 'next/link';
import { LayoutGrid, List, Plus, RefreshCw } from 'lucide-react';

import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { EmptyState, GatedState } from '@/app/components/ui/EmptyState';
import { Segmented, SegmentedItem } from '@/app/components/ui/Segmented';
import { toast } from '@/app/components/ui/toast';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { useAuthSession } from '@lib/auth/session-client';
import { cadenceLabel } from '@/app/components/ade/repositories/webhookAllowlistModel';
import { connectorKindLabel } from '@lib/connector-kinds';
import { listConnectors, runOutcome, syncConnector, type Connector } from '@lib/connectors-api';

/**
 * Bring in → Connectors — `/ade/dashboard/connectors` (CDG-1.7, #5958).
 *
 * Every registered connector with its health and last run, as a list or a grid (the same two views
 * Repositories offers). "Sync now" runs one sync and reports its outcome in place; the name opens the
 * connector's Items, Runs and Settings.
 */

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/** The page's two views. */
type ConnectorsView = 'list' | 'grid';

/**
 * A connector's schedule as words.
 *
 * @param seconds - `refreshIntervalSeconds` (null = deployment default).
 */
export function scheduleLabel(seconds: number | null): string {
  return seconds ? cadenceLabel(seconds) : 'Deployment default';
}

/**
 * The connectors list page.
 *
 * @returns The page.
 */
export default function ConnectorsClient() {
  const { data: session } = useAuthSession();
  const tenantId = (session?.user as { current_tenant_id?: string } | undefined)?.current_tenant_id;
  const [connectors, setConnectors] = React.useState<Connector[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [view, setView] = React.useState<ConnectorsView>('list');
  const [syncing, setSyncing] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    try {
      const list = await listConnectors();
      setConnectors(list.connectors);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The connectors could not be read. Try again.');
    }
  }, []);

  React.useEffect(() => {
    if (tenantId) void load();
  }, [tenantId, load]);

  const sync = React.useCallback(
    async (connector: Connector) => {
      setSyncing(connector.id);
      try {
        const run = await syncConnector(connector.id);
        if (run.status === 'succeeded') toast.success(`${connector.name}: ${runOutcome({ ...run, source: 'connector' })}.`);
        else toast.error(`${connector.name}: ${run.errorMessage ?? 'the sync failed'}. Open the connector's runs for details.`);
      } catch (e) {
        toast.error(e instanceof Error ? e.message : 'The sync did not start. Try again.');
      } finally {
        setSyncing(null);
        void load();
      }
    },
    [load]
  );

  const addButton = (
    <Button asChild data-testid="connectors-add">
      <Link href="/ade/dashboard/connectors/new">
        <Plus aria-hidden />
        Add connector
      </Link>
    </Button>
  );

  return (
    <Page>
      <PageHeader
        breadcrumb={[{ label: 'Home', href: HOME_ROUTE }, { label: 'Connectors' }]}
        title="Connectors"
        description="Gateways and registries whose APIs sync into the catalog."
        actions={addButton}
      />
      <PageBody>
        {!tenantId ? (
          <GatedState description="Connectors are registered against one workspace." />
        ) : error ? (
          <EmptyState
            variant="compact"
            surface={false}
            tone="danger"
            title="The connectors could not be read"
            description={error}
            action={
              <Button variant="soft" onClick={() => void load()}>
                <RefreshCw aria-hidden />
                Try again
              </Button>
            }
          />
        ) : connectors === null ? (
          <p className="cnx-note" data-testid="connectors-loading">
            Reading your connectors…
          </p>
        ) : connectors.length === 0 ? (
          <EmptyState
            variant="compact"
            surface={false}
            title="Connect your first gateway"
            description="Kong, AWS API Gateway, Azure API Management and Apigee APIs sync into the catalog."
            action={addButton}
          />
        ) : (
          <>
            <div className="cnx-toolbar">
              <Segmented value={view} onValueChange={(next) => setView(next as ConnectorsView)} size="sm" aria-label="List view">
                <SegmentedItem value="list" data-testid="connectors-view-list">
                  <List aria-hidden />
                  List
                </SegmentedItem>
                <SegmentedItem value="grid" data-testid="connectors-view-grid">
                  <LayoutGrid aria-hidden />
                  Grid
                </SegmentedItem>
              </Segmented>
            </div>
            {view === 'list' ? (
              <div className="cnx-table-wrap">
                <table className="cnx-table" data-testid="connectors-table">
                  <thead>
                    <tr>
                      <th scope="col">Connector</th>
                      <th scope="col">Health</th>
                      <th scope="col">Last run</th>
                      <th scope="col">Schedule</th>
                      <th scope="col">
                        <span className="sr-only">Actions</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {connectors.map((connector) => (
                      <tr key={connector.id} data-testid={`connector-row-${connector.id}`}>
                        <td>
                          <Link href={`/ade/dashboard/connectors/${encodeURIComponent(connector.id)}`} className="cnx-link">
                            {connector.name}
                          </Link>
                          <span className="cnx-meta">{connectorKindLabel(connector.kind)}</span>
                        </td>
                        <td>
                          <Badge status={connector.status} dot>
                            {connector.status}
                          </Badge>
                        </td>
                        <td className="cnx-mono">
                          {connector.lastRunAt ? new Date(connector.lastRunAt).toLocaleString() : 'Never'}
                        </td>
                        <td>{scheduleLabel(connector.refreshIntervalSeconds)}</td>
                        <td className="cnx-actions">
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={!connector.syncable || syncing === connector.id}
                            onClick={() => void sync(connector)}
                            data-testid={`connector-sync-${connector.id}`}
                          >
                            {syncing === connector.id ? 'Syncing…' : 'Sync now'}
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <ul className="cnx-grid" data-testid="connectors-grid">
                {connectors.map((connector) => (
                  <li key={connector.id} className="cnx-card">
                    <Link href={`/ade/dashboard/connectors/${encodeURIComponent(connector.id)}`} className="cnx-link">
                      {connector.name}
                    </Link>
                    <span className="cnx-meta">{connectorKindLabel(connector.kind)}</span>
                    <div className="cnx-card__row">
                      <Badge status={connector.status} dot>
                        {connector.status}
                      </Badge>
                      <span className="cnx-meta">
                        {connector.lastRunAt ? `Last run ${new Date(connector.lastRunAt).toLocaleString()}` : 'Never synced'}
                      </span>
                    </div>
                    <Button
                      size="sm"
                      variant="soft"
                      disabled={!connector.syncable || syncing === connector.id}
                      onClick={() => void sync(connector)}
                    >
                      {syncing === connector.id ? 'Syncing…' : 'Sync now'}
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </PageBody>
    </Page>
  );
}
