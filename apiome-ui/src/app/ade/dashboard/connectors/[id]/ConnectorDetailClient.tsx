'use client';

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { RefreshCw } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { FormField } from '@/app/components/ui/FormField';
import { Input } from '@/app/components/ui/Input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/app/components/ui/Select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/app/components/ui/Tabs';
import { ConnectorEnvironments } from '@/app/components/ade/gatewayConfigs/ConnectorEnvironments';
import { toast } from '@/app/components/ui/toast';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { useDialog } from '@/app/components/providers/DialogProvider';
import { ConnectorFields } from '@/app/components/ade/connectors/ConnectorFields';
import { RefreshRunsLedger } from '@/app/components/ade/connectors/RefreshRunsLedger';
import { ConflictPolicyOption } from '@/app/components/ade/dashboard/repositories/RepositoryConflictPolicy';
import {
  CONFLICT_POLICIES,
  asConflictPolicy,
  type ConflictPolicy,
} from '@/app/components/ade/dashboard/repositories/repositoryConflictPolicy';
import {
  CADENCE_OPTIONS,
  buildCredentials,
  buildScope,
  cadenceSeconds,
  cadenceValue,
  connectorKind,
  connectorKindLabel,
  landsInMcpCatalog,
  scopeToValues,
  type FieldValues,
} from '@lib/connector-kinds';
import { isFeatureReleased } from '@lib/feature-release';
import {
  deleteConnector,
  getConnector,
  listConnectorItems,
  putCredentials,
  runOutcome,
  syncConnector,
  updateConnector,
  type Connector,
  type ConnectorItem,
} from '@lib/connectors-api';

/**
 * One connector — `/ade/dashboard/connectors/[id]` (CDG-1.7, #5958).
 *
 * **Items** is the inventory: every API the connector has seen, its environment and revision, and a
 * link to its catalog item — or, for an MCP registry (CDG-4.4), to the MCP server it added and the reason
 * an entry is still discovered. **Runs** is the shared refresh ledger, filtered to this connector.
 * **Settings** changes the name, scope, schedule and conflict policy, pauses or resumes scheduled
 * syncs, replaces the credential, and deletes the connector (its catalog items stay).
 */

const CONNECTORS_ROUTE = '/ade/dashboard/connectors';

/**
 * The connector page.
 *
 * @param props.connectorId - The connector id from the route.
 * @returns The page.
 */
export default function ConnectorDetailClient({ connectorId }: { connectorId: string }) {
  const router = useRouter();
  const { confirm } = useDialog();
  const [connector, setConnector] = React.useState<Connector | null>(null);
  const [items, setItems] = React.useState<ConnectorItem[] | null>(null);
  const [itemTotal, setItemTotal] = React.useState(0);
  const [error, setError] = React.useState<string | null>(null);
  const [syncing, setSyncing] = React.useState(false);
  const [runsKey, setRunsKey] = React.useState(0);
  const [tab, setTab] = React.useState('items');
  const mcpInventory = landsInMcpCatalog(connector?.kind);

  const load = React.useCallback(async () => {
    try {
      const [found, page] = await Promise.all([getConnector(connectorId), listConnectorItems(connectorId)]);
      setConnector(found);
      setItems(page.items);
      setItemTotal(page.total);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The connector could not be read. Try again.');
    }
  }, [connectorId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const sync = async () => {
    if (!connector) return;
    setSyncing(true);
    try {
      const run = await syncConnector(connector.id);
      if (run.status === 'succeeded') toast.success(`${runOutcome({ ...run, source: 'connector' })}.`);
      else toast.error(run.errorMessage ?? 'The sync failed. The Runs tab has the details.');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'The sync did not start. Try again.');
    } finally {
      setSyncing(false);
      setRunsKey((key) => key + 1);
      void load();
    }
  };

  const remove = async () => {
    if (!connector) return;
    const confirmed = await confirm({
      title: `Delete connector "${connector.name}"?`,
      message: 'Scheduled syncs stop and the stored credential is destroyed.',
      consequence: 'The catalog items it imported stay in the catalog.',
      variant: 'danger',
      confirmLabel: 'Delete connector',
      perform: async () => {
        await deleteConnector(connector.id);
      },
    });
    if (confirmed) router.push(CONNECTORS_ROUTE);
  };

  if (error && !connector) {
    return (
      <Page>
        <PageHeader breadcrumb={[{ label: 'Connectors', href: CONNECTORS_ROUTE }, { label: 'Connector' }]} title="Connector" />
        <PageBody>
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
        </PageBody>
      </Page>
    );
  }

  return (
    <Page>
      <Tabs value={tab} onValueChange={setTab} className="contents">
        <PageHeader
          breadcrumb={[
            { label: 'Home', href: '/ade/dashboard' },
            { label: 'Connectors', href: CONNECTORS_ROUTE },
            { label: connector?.name ?? 'Connector' },
          ]}
          title={connector?.name ?? 'Connector'}
          description={connector ? `${connectorKindLabel(connector.kind)} connector.` : undefined}
          actions={
            <Button onClick={() => void sync()} disabled={!connector?.syncable || syncing} data-testid="connector-sync">
              <RefreshCw aria-hidden />
              {syncing ? 'Syncing…' : 'Sync now'}
            </Button>
          }
          tabs={
            <TabsList>
              <TabsTrigger value="items" data-testid="connector-tab-items">
                Items
              </TabsTrigger>
              <TabsTrigger value="environments" data-testid="connector-tab-environments">
                Environments
              </TabsTrigger>
              <TabsTrigger value="runs" data-testid="connector-tab-runs">
                Runs
              </TabsTrigger>
              <TabsTrigger value="settings" data-testid="connector-tab-settings">
                Settings
              </TabsTrigger>
            </TabsList>
          }
        />
        <PageBody>
          {connector ? (
            <div className="cnx-facts" data-testid="connector-facts">
              <Badge status={connector.status} dot>
                {connector.status}
              </Badge>
              <span className="cnx-meta">
                {connector.lastRunAt ? `Last run ${new Date(connector.lastRunAt).toLocaleString()}` : 'Never synced'}
              </span>
              <span className="cnx-meta">{connector.hasCredentials ? 'Credential stored' : 'No stored credential'}</span>
            </div>
          ) : (
            <p className="cnx-note">Reading the connector…</p>
          )}

          <TabsContent value="items" data-testid="connector-items">
            {items && items.length === 0 ? (
              <p className="cnx-note">The inventory is empty. Click “Sync now” to read it.</p>
            ) : null}
            {items && items.length > 0 ? (
              <div className="cnx-table-wrap">
                <table className="cnx-table">
                  <thead>
                    <tr>
                      <th scope="col">{mcpInventory ? 'Server' : 'API'}</th>
                      <th scope="col">Environment</th>
                      <th scope="col">Revision</th>
                      <th scope="col">Status</th>
                      <th scope="col">{mcpInventory ? 'MCP server' : 'Catalog item'}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item) => (
                      <tr key={item.id} data-testid={`connector-item-${item.id}`}>
                        <td>
                          <span className="cnx-name">{item.remoteName ?? item.remoteId}</span>
                          <span className="cnx-meta cnx-mono">{item.remoteId}</span>
                        </td>
                        <td>{item.environment ?? '—'}</td>
                        <td className="cnx-mono">{item.remoteRevision ?? '—'}</td>
                        <td>
                          <Badge status={item.status} dot>
                            {item.status}
                          </Badge>
                          {item.discoveredReason ? (
                            <span className="cnx-meta" data-testid={`connector-item-reason-${item.id}`}>
                              {item.discoveredReason}
                            </span>
                          ) : null}
                        </td>
                        <td>
                          {item.catalogItemId ? (
                            <Link
                              href={`/ade/dashboard/catalog/${encodeURIComponent(item.catalogItemId)}`}
                              className="cnx-link"
                              data-testid={`connector-item-link-${item.id}`}
                            >
                              Open in the catalog
                            </Link>
                          ) : item.mcpEndpointId && !isFeatureReleased('mcp') ? (
                            // The MCP servers screen is not released yet: name the server, link nowhere.
                            <span className="cnx-meta" data-testid={`connector-item-mcp-${item.id}`}>
                              Added to the MCP servers
                            </span>
                          ) : item.mcpEndpointId ? (
                            <Link
                              href={`/ade/dashboard/mcp/${encodeURIComponent(item.mcpEndpointId)}`}
                              className="cnx-link"
                              data-testid={`connector-item-link-${item.id}`}
                            >
                              Open the MCP server
                            </Link>
                          ) : (
                            <span className="cnx-meta">Not imported</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {itemTotal > items.length ? (
                  <p className="cnx-note">
                    Showing {items.length} of {itemTotal} {mcpInventory ? 'servers' : 'APIs'}.
                  </p>
                ) : null}
              </div>
            ) : null}
          </TabsContent>

          {/* CDG-5.3: one gateway config per environment the syncs found. */}
          <TabsContent value="environments">
            <ConnectorEnvironments connectorId={connectorId} active={tab === 'environments'} />
          </TabsContent>

          <TabsContent value="runs">
            <RefreshRunsLedger connectorId={connectorId} refreshKey={runsKey} title="Runs" />
          </TabsContent>

          <TabsContent value="settings">
            {connector ? (
              <ConnectorSettings
                connector={connector}
                onSaved={(next) => setConnector(next)}
                onDelete={() => void remove()}
              />
            ) : null}
          </TabsContent>
        </PageBody>
      </Tabs>
    </Page>
  );
}

/**
 * The Settings tab: the connector's own fields, its credential, pause/resume and delete.
 */
function ConnectorSettings({
  connector,
  onSaved,
  onDelete,
}: {
  connector: Connector;
  onSaved: (connector: Connector) => void;
  onDelete: () => void;
}) {
  const kind = connectorKind(connector.kind);
  const [name, setName] = React.useState(connector.name);
  const [baseUrl, setBaseUrl] = React.useState(connector.baseUrl ?? '');
  const [scope, setScope] = React.useState<FieldValues>(kind ? scopeToValues(kind, connector.scope) : {});
  const [cadence, setCadence] = React.useState(cadenceValue(connector.refreshIntervalSeconds));
  const [policy, setPolicy] = React.useState<ConflictPolicy>(asConflictPolicy(connector.conflictPolicy));
  const [credentials, setCredentials] = React.useState<FieldValues>({});
  const [saving, setSaving] = React.useState(false);
  const [problem, setProblem] = React.useState<string | null>(null);

  const save = async (changes: Record<string, unknown>, success: string) => {
    setSaving(true);
    setProblem(null);
    try {
      onSaved(await updateConnector(connector.id, changes));
      toast.success(success);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'The change was not saved. Try again.');
    } finally {
      setSaving(false);
    }
  };

  const saveCredentials = async () => {
    if (!kind) return;
    const fields = buildCredentials(kind, credentials);
    if (!fields) return;
    setSaving(true);
    setProblem(null);
    try {
      await putCredentials(connector.id, fields);
      setCredentials({});
      onSaved({ ...connector, hasCredentials: true });
      toast.success('The credential was replaced.');
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'The credential was not saved. Try again.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="cnx-settings" data-testid="connector-settings">
      {problem ? (
        <Alert variant="error" data-testid="connector-settings-error">
          {problem}
        </Alert>
      ) : null}
      <section className="cnx-panel">
        <h2 className="cnx-section-title">Connection</h2>
        <FormField label="Name" htmlFor="connector-settings-name" required>
          <Input id="connector-settings-name" value={name} onChange={(event) => setName(event.target.value)} />
        </FormField>
        {kind && kind.baseUrl !== 'none' ? (
          <FormField label="Base URL" htmlFor="connector-settings-base-url">
            <Input id="connector-settings-base-url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} />
          </FormField>
        ) : null}
        {kind ? (
          <ConnectorFields
            fields={kind.scope}
            values={scope}
            idPrefix="connector-settings-scope"
            onChange={(key, value) => setScope((current) => ({ ...current, [key]: value }))}
          />
        ) : null}
        <FormField label="Refresh" htmlFor="connector-settings-cadence">
          <Select value={cadence} onValueChange={setCadence}>
            <SelectTrigger id="connector-settings-cadence">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CADENCE_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <fieldset className="cnx-policies">
          <legend className="cnx-legend">When a synced API was edited in Apiome</legend>
          {CONFLICT_POLICIES.map((candidate) => (
            <ConflictPolicyOption
              key={candidate}
              policy={candidate}
              name="connector-settings-conflict-policy"
              selected={policy === candidate}
              disabled={saving}
              onSelect={setPolicy}
            />
          ))}
        </fieldset>
        <div className="cnx-panel__actions">
          <Button
            onClick={() =>
              void save(
                {
                  name: name.trim(),
                  ...(kind && kind.baseUrl !== 'none' ? { baseUrl: baseUrl.trim() || null } : {}),
                  ...(kind ? { scope: buildScope(kind, scope) } : {}),
                  refreshIntervalSeconds: cadenceSeconds(cadence),
                  conflictPolicy: policy,
                },
                'The connector was saved.'
              )
            }
            disabled={saving || !name.trim()}
            data-testid="connector-settings-save"
          >
            Save changes
          </Button>
        </div>
      </section>

      {kind && kind.credentials.length > 0 ? (
        <section className="cnx-panel">
          <h2 className="cnx-section-title">Credential</h2>
          <p className="cnx-note">
            {connector.hasCredentials
              ? 'A credential is stored. Enter a new one to replace it as a whole; the stored one is never shown.'
              : 'No credential is stored yet.'}
          </p>
          <ConnectorFields
            fields={kind.credentials}
            values={credentials}
            idPrefix="connector-settings-credential"
            onChange={(key, value) => setCredentials((current) => ({ ...current, [key]: value }))}
          />
          <div className="cnx-panel__actions">
            <Button
              variant="soft"
              onClick={() => void saveCredentials()}
              disabled={saving || !buildCredentials(kind, credentials)}
              data-testid="connector-settings-credential-save"
            >
              Replace credential
            </Button>
          </div>
        </section>
      ) : null}

      <section className="cnx-panel">
        <h2 className="cnx-section-title">Scheduled syncs</h2>
        <p className="cnx-note">
          {connector.status === 'paused'
            ? 'Paused: scheduled syncs are skipped. “Sync now” still runs.'
            : 'Syncs run on the schedule above.'}
        </p>
        <div className="cnx-panel__actions">
          <Button
            variant="soft"
            disabled={saving}
            onClick={() =>
              void save(
                { status: connector.status === 'paused' ? 'active' : 'paused' },
                connector.status === 'paused' ? 'Scheduled syncs resumed.' : 'Scheduled syncs paused.'
              )
            }
            data-testid="connector-settings-pause"
          >
            {connector.status === 'paused' ? 'Resume scheduled syncs' : 'Pause scheduled syncs'}
          </Button>
        </div>
      </section>

      <section className="cnx-panel cnx-panel--danger">
        <h2 className="cnx-section-title">Delete</h2>
        <p className="cnx-note">The catalog items this connector imported stay in the catalog.</p>
        <div className="cnx-panel__actions">
          <Button variant="danger" onClick={onDelete} data-testid="connector-settings-delete">
            Delete connector
          </Button>
        </div>
      </section>
    </div>
  );
}
