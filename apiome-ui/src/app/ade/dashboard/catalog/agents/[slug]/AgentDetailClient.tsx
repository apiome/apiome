'use client';

/**
 * Bring in → Catalog → one agent — `/ade/dashboard/catalog/agents/[slug]` (CDG-5.2, #5980).
 *
 * **Overview**: what the agent runs in and on — runtime, status and its model, with the model's
 * deprecation date called out — its owner team, the agent keys it uses (name, prefix and status:
 * never a secret) with **Link key** / **Unlink**, the consumer it is in each project its keys
 * reach, and a link to its usage. **Graph**: the dependency graph around that consumer (one per
 * project). **Retire** stops the agent consuming anything; **Delete** removes it.
 */

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Activity, RefreshCw } from 'lucide-react';

import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { Alert, Badge, Button, EmptyState, GatedState, Label, LoadingState } from '@/app/components/ui';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/app/components/ui/Tabs';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import { DependenciesPanel } from '@/app/components/ade/graph/DependenciesPanel';
import { CatalogFactsPanel } from '@/app/components/ade/catalogFacts/CatalogFactsPanel';
import { EntityOwnerSection } from '@/app/components/ade/catalogAgents/EntityOwnerSection';
import {
  deleteAgent,
  fetchAgent,
  fetchAgentKeys,
  linkAgentKey,
  unlinkAgentKey,
  updateAgent,
  type LinkableKey,
} from '@/app/components/ade/catalogAgents/catalogAgentsApi';
import { useAuthSession } from '@lib/auth/session-client';
import { graphPageHref } from '@lib/graph';
import { KEY_STATUS_LABELS, deprecationLabel, modelHref, type CatalogAgent } from '@lib/catalog-agents';

const HOME_ROUTE = '/ade/dashboard';
const CATALOG_ROUTE = '/ade/dashboard/catalog';
const AGENTS_ROUTE = '/ade/dashboard/catalog?kind=agent';

/** Props for {@link AgentDetailClient}. */
export interface AgentDetailClientProps {
  /** The agent's slug (or id), from the route. */
  slug: string;
}

/**
 * The agent page.
 *
 * @param props - See {@link AgentDetailClientProps}.
 * @returns The page.
 */
export default function AgentDetailClient({ slug }: AgentDetailClientProps) {
  const router = useRouter();
  const { data: session } = useAuthSession();
  const tenantId = (session?.user as { current_tenant_id?: string } | undefined)?.current_tenant_id;
  const [agent, setAgent] = React.useState<CatalogAgent | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [tab, setTab] = React.useState('overview');
  const [linkOpen, setLinkOpen] = React.useState(false);

  const load = React.useCallback(async () => {
    setError(null);
    try {
      setAgent(await fetchAgent(slug));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load the agent');
    }
  }, [slug]);

  React.useEffect(() => {
    if (tenantId) void load();
  }, [tenantId, load]);

  /** Run one change and show the agent it returns. */
  const act = async (work: () => Promise<CatalogAgent | void>) => {
    setBusy(true);
    setActionError(null);
    try {
      const next = await work();
      if (next) setAgent(next);
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : 'Could not save the agent');
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!agent) return;
    await act(async () => {
      await deleteAgent(agent.slug);
      router.push(AGENTS_ROUTE);
    });
  };

  const title = agent?.name ?? slug;
  const retired = agent?.status === 'retired';

  return (
    <Page>
      <PageHeader
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Bring in' },
          { label: 'Catalog', href: CATALOG_ROUTE },
          { label: 'Agents', href: AGENTS_ROUTE },
          { label: title },
        ]}
        title={title}
        description={agent?.description || 'An agent: what it runs on, the keys it uses and what it consumes.'}
        actions={
          agent ? (
            <>
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => void act(() => updateAgent(agent.slug, { status: retired ? 'active' : 'retired' }))}
                data-testid="agent-retire"
              >
                {retired ? 'Reactivate' : 'Retire'}
              </Button>
              <Button variant="danger-soft" disabled={busy} onClick={() => void remove()} data-testid="agent-delete">
                Delete
              </Button>
            </>
          ) : null
        }
      />
      <PageBody>
        {!tenantId ? (
          <GatedState description="Agents belong to one workspace." />
        ) : error && !agent ? (
          <EmptyState
            variant="compact"
            surface={false}
            tone="danger"
            title="The agent could not be read"
            description={error}
            action={
              <Button variant="soft" onClick={() => void load()}>
                <RefreshCw aria-hidden />
                Try again
              </Button>
            }
          />
        ) : !agent ? (
          <LoadingState message="Reading the agent…" minHeightClassName="min-h-[8rem]" />
        ) : (
          <div className="agt-page" data-testid="agent-detail">
            {actionError ? <Alert variant="error">{actionError}</Alert> : null}
            <dl className="agt-facts">
              <div>
                <dt>Status</dt>
                <dd>
                  <Badge status={retired ? 'retired' : 'active'} dot>
                    {retired ? 'Retired' : 'Active'}
                  </Badge>
                </dd>
              </div>
              <div>
                <dt>Runtime</dt>
                <dd>{agent.runtime ?? '—'}</dd>
              </div>
              <div>
                <dt>Model</dt>
                <dd data-testid="agent-model">
                  {agent.model ? (
                    <>
                      <Link className="agt-link" href={modelHref(agent.model.slug)}>
                        {agent.model.name}
                      </Link>{' '}
                      <span className="agt-muted">
                        {agent.model.provider}
                        {agent.model.modelVersion ? ` · ${agent.model.modelVersion}` : ''}
                      </span>
                    </>
                  ) : (
                    '—'
                  )}
                </dd>
              </div>
            </dl>
            {agent.model?.deprecatedAt ? (
              <Alert variant={agent.model.deprecated ? 'error' : 'warning'} data-testid="agent-model-deprecation">
                {deprecationLabel(agent.model)}: {agent.model.name} — move this agent to a supported model.
              </Alert>
            ) : null}

            <Tabs value={tab} onValueChange={setTab}>
              <TabsList aria-label="Agent">
                <TabsTrigger value="overview" data-testid="agent-tab-overview">
                  Overview
                </TabsTrigger>
                <TabsTrigger value="graph" data-testid="agent-tab-graph">
                  Graph
                </TabsTrigger>
              </TabsList>
              <TabsContent value="overview" className="agt-page">
                <EntityOwnerSection kind="agent" entityId={agent.id} owner={agent.owner} onChanged={() => void load()} />
                <KeysSection agent={agent} busy={busy} onLink={() => setLinkOpen(true)} onUnlink={(keyId) => void act(() => unlinkAgentKey(agent.slug, keyId))} />
                <ConsumersSection agent={agent} />
                <CatalogFactsPanel kind="agent" id={agent.id} active={tab === 'overview'} />
              </TabsContent>
              <TabsContent value="graph">
                <AgentGraph agent={agent} active={tab === 'graph'} />
              </TabsContent>
            </Tabs>
          </div>
        )}
      </PageBody>
      {agent ? (
        <LinkKeyDialog
          open={linkOpen}
          onOpenChange={setLinkOpen}
          linked={agent.keys.map((key) => key.id)}
          onLink={(keyId) => act(() => linkAgentKey(agent.slug, keyId))}
        />
      ) : null}
    </Page>
  );
}

/** The agent keys, with Link key and Unlink. */
function KeysSection({
  agent,
  busy,
  onLink,
  onUnlink,
}: {
  agent: CatalogAgent;
  busy: boolean;
  onLink: () => void;
  onUnlink: (keyId: string) => void;
}) {
  return (
    <section className="agt-section" aria-labelledby="agt-keys" data-testid="agent-keys">
      <div className="agt-section__head">
        <h2 id="agt-keys" className="agt-section__title">
          Agent keys
        </h2>
        <Button size="sm" variant="outline" onClick={onLink} disabled={busy} data-testid="agent-link-key">
          Link key
        </Button>
      </div>
      {agent.keys.length === 0 ? (
        <p className="agt-muted">No keys yet. Link one to make the agent a consumer of what it calls.</p>
      ) : (
        <div className="agt-table-wrap">
          <table className="agt-table">
            <caption className="sr-only">Agent keys {agent.name} uses</caption>
            <thead>
              <tr>
                <th scope="col">Key</th>
                <th scope="col">Status</th>
                <th scope="col">Toolset</th>
                <th scope="col">Tools</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {agent.keys.map((key) => (
                <tr key={key.id} data-testid={`agent-key-${key.id}`}>
                  <td>
                    <span className="agt-strong">{key.name}</span>
                    <span className="agt-muted mono">{key.keyPrefix}</span>
                  </td>
                  <td>
                    <Badge status={key.status === 'active' ? 'active' : 'retired'}>{KEY_STATUS_LABELS[key.status]}</Badge>
                  </td>
                  <td>
                    {key.projectName ?? '—'}
                    {key.versionLabel ? <span className="agt-muted"> · {key.versionLabel}</span> : null}
                  </td>
                  <td className="agt-num">{key.enabledTools}</td>
                  <td>
                    <Button size="sm" variant="ghost" onClick={() => onUnlink(key.id)} disabled={busy} data-testid={`agent-unlink-${key.id}`}>
                      Unlink
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** What the agent consumes, per project, and its usage. */
function ConsumersSection({ agent }: { agent: CatalogAgent }) {
  return (
    <section className="agt-section" aria-labelledby="agt-consumes" data-testid="agent-consumers">
      <div className="agt-section__head">
        <h2 id="agt-consumes" className="agt-section__title">
          Consumes
        </h2>
        <Link className="agt-link agt-inline-icon" href={agent.usageHref} data-testid="agent-usage-link">
          <Activity aria-hidden />
          Usage
        </Link>
      </div>
      {agent.consumers.length === 0 ? (
        <p className="agt-muted">Nothing yet: link a live key whose toolset enables operations.</p>
      ) : (
        <ul className="agt-list">
          {agent.consumers.map((consumer) => (
            <li key={consumer.consumerId}>
              <Link className="agt-link" href={graphPageHref('consumer', consumer.consumerId)}>
                {consumer.projectName ?? consumer.projectId}
              </Link>
              <span className="agt-muted">
                {' '}
                · {consumer.operationCount} operation{consumer.operationCount === 1 ? '' : 's'}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** The dependency graph around the consumer the agent is in one project. */
function AgentGraph({ agent, active }: { agent: CatalogAgent; active: boolean }) {
  const [consumerId, setConsumerId] = React.useState(agent.consumers[0]?.consumerId ?? '');
  if (agent.consumers.length === 0) {
    return <p className="agt-muted">The agent consumes nothing yet, so it has no edges.</p>;
  }
  const current = agent.consumers.find((consumer) => consumer.consumerId === consumerId) ?? agent.consumers[0];
  return (
    <div className="agt-page">
      {agent.consumers.length > 1 ? (
        <div className="agx-field">
          <Label htmlFor="agt-graph-project">Project</Label>
          <select
            id="agt-graph-project"
            className="agt-select"
            value={current.consumerId}
            onChange={(event) => setConsumerId(event.target.value)}
          >
            {agent.consumers.map((consumer) => (
              <option key={consumer.consumerId} value={consumer.consumerId}>
                {consumer.projectName ?? consumer.projectId}
              </option>
            ))}
          </select>
        </div>
      ) : null}
      <DependenciesPanel
        key={current.consumerId}
        kind="consumer"
        id={current.consumerId}
        active={active}
        label={{ name: agent.name, slug: agent.slug, owner: null }}
      />
    </div>
  );
}

/** Pick one of the workspace's live agent keys to link. */
function LinkKeyDialog({
  open,
  onOpenChange,
  linked,
  onLink,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  linked: readonly string[];
  onLink: (keyId: string) => Promise<void>;
}) {
  const [keys, setKeys] = React.useState<LinkableKey[] | null>(null);
  const [keyId, setKeyId] = React.useState('');

  // The linked ids as one string, so a re-render with the same keys does not refetch.
  const linkedKey = linked.join(',');
  React.useEffect(() => {
    if (!open) return;
    setKeyId('');
    setKeys(null);
    const taken = new Set(linkedKey.split(','));
    fetchAgentKeys()
      .then((all) => setKeys(all.filter((key) => !taken.has(key.id))))
      .catch(() => setKeys([]));
  }, [open, linkedKey]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="agent-link-dialog">
        <DialogHeader>
          <DialogTitle>Link agent key</DialogTitle>
          <DialogDescription>What the key may call becomes what this agent consumes.</DialogDescription>
        </DialogHeader>
        {keys === null ? (
          <LoadingState message="Reading agent keys…" minHeightClassName="min-h-[4rem]" />
        ) : keys.length === 0 ? (
          <p className="agt-muted">No other live agent keys. Create one under MCP servers → Agent access.</p>
        ) : (
          <div className="agx-field">
            <Label htmlFor="agt-link-key">Agent key</Label>
            <select
              id="agt-link-key"
              className="agt-select"
              value={keyId}
              onChange={(event) => setKeyId(event.target.value)}
              data-testid="agent-link-select"
            >
              <option value="">Choose a key…</option>
              {keys.map((key) => (
                <option key={key.id} value={key.id}>
                  {key.name} ({key.keyPrefix})
                </option>
              ))}
            </select>
          </div>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={!keyId}
            onClick={() => {
              void onLink(keyId).then(() => onOpenChange(false));
            }}
            data-testid="agent-link-submit"
          >
            Link key
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
