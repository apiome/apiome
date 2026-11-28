'use client';

/**
 * **Contracts** — `/ade/dashboard/pacts`, the landing of the Contracts area (PFX-8.1, #7298).
 *
 * Built to `docs/mockups/contracts/overview.html`:
 *
 * * the area's **tab row** ({@link ContractsTabs}), shared by every Contracts page;
 * * one **status strip** (DESIGN.md §5.4) for failing, stale, provider-less and pending
 *   integrations, one detail row open at a time — or, when nothing needs attention, the first-visit
 *   explainer in its place, so the page never stacks two banners;
 * * a **facts line** whose *Show stats* reveals the contract-health rollup (PFX-6.3);
 * * one **integrations table** — pair, kind, latest verdict, the environments both sides run in,
 *   last verified — with search, filter chips and the page kept in the address, a row menu, and the
 *   network graph (PFX-5.3) as its second view;
 * * **Start something**, by who is asking, and the **first-run checklist** until one integration is
 *   verified.
 *
 * States: an empty workspace has no strip and no facts line, an empty table with the first-run
 * checklist open; loading draws skeleton rows; a failed read is one banner with **Try again**. A
 * role without `pacts:create` sees no header actions and no "Start something"; the table and strip
 * stay. Anything in the address that cannot be used is said under the toolbar, never dropped.
 */

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { FileCheck2, FileUp, Import, Rocket, Search, ShieldCheck, Table2, Waypoints, WandSparkles } from 'lucide-react';
import {
  Button,
  DismissibleCallout,
  EmptyState,
  ErrorBanner,
  FactsLine,
  Segmented,
  SegmentedItem,
  StatusStrip,
  type StatusStripItem,
} from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { useMyPermissions } from '@/app/components/ade/access/useMyPermissions';
import { CAN_I_DEPLOY_ROUTE } from '@lib/pact-matrix';
import { MIGRATE_ROUTE } from '@lib/pact-migration';
import { PUBLISH_ROUTE } from '@lib/pact-publish-page';
import type { HealthOverview } from '@lib/pact-health';
import {
  CONTRACTS_CRUMBS,
  FILTER_LABEL,
  INTEGRATION_FILTERS,
  INTEGRATIONS_PAGE_SIZE,
  MAX_SEARCH_LENGTH,
  WAYS_IN,
  firstRunSteps,
  integrationsNetwork,
  overviewRoute,
  overviewStatuses,
  type OverviewQuery,
  type PactIntegrationsPage,
} from '@lib/pact-overview';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { fetchHealth } from '../pactHealth/healthApi';
import { HealthKpis } from '../pactHealth/HealthPanels';
import { NetworkGraphSvg } from '../pactNetwork/NetworkGraphSvg';
import { networkLayout } from '../pactNetwork/networkLayoutModel';
import { ContractsTabs } from './ContractsTabs';
import {
  CommandDialog,
  FirstRunChecklist,
  IntegrationsTable,
  WaysIn,
  type CommandRequest,
} from './OverviewPanels';
import { fetchIntegrations } from './overviewApi';

/** The permission every write on this page needs (publishing is `pacts:create`). */
const WRITE_PERMISSION = 'pacts:create';

/** The integrations read. */
type IntegrationsRead = { data: PactIntegrationsPage | null; error: string | null };

/** Every command the header and the ⋯ menu open, by id. */
const WAY_COMMANDS = new Map(
  WAYS_IN.flatMap((group) => group.ways)
    .filter((way) => way.command)
    .map((way) => [way.id, { title: way.title, description: way.description, command: way.command ?? '' }]),
);

/**
 * A command request by its "Start something" id.
 *
 * @param id - The entry point's id.
 * @returns The request.
 */
function commandFor(id: string): CommandRequest {
  return WAY_COMMANDS.get(id) ?? { title: id, description: '', command: '' };
}

/**
 * The Contracts landing.
 *
 * @param props - The address it was opened with.
 * @returns The page.
 */
export default function PactOverviewClient({ query }: { query: OverviewQuery }) {
  const router = useRouter();
  const permissions = useMyPermissions();
  const canWrite = permissions.status === 'ready' && permissions.can(WRITE_PERMISSION);
  const [read, setRead] = React.useState<IntegrationsRead>({ data: null, error: null });
  const [health, setHealth] = React.useState<{ data: HealthOverview | null; error: string | null }>({
    data: null,
    error: null,
  });
  const [command, setCommand] = React.useState<CommandRequest | null>(null);
  const [search, setSearch] = React.useState(query.q);
  const [checklistOpen, setChecklistOpen] = React.useState<boolean | null>(null);

  const { q, filter, page, view } = query;
  const load = React.useCallback(async () => {
    setRead({ data: null, error: null });
    try {
      setRead({ data: await fetchIntegrations({ q, filter, page }), error: null });
    } catch (caught) {
      setRead({ data: null, error: describeFailure(caught, 'Could not load the integrations') });
    }
  }, [q, filter, page]);

  React.useEffect(() => {
    void load();
  }, [load]);

  React.useEffect(() => {
    setSearch(q);
  }, [q]);

  React.useEffect(() => {
    // The rollup is only the facts line's "Show stats": a failure says so there, not as a banner.
    fetchHealth()
      .then((data) => setHealth({ data, error: null }))
      .catch((caught) => setHealth({ data: null, error: describeFailure(caught, 'Could not load the contract health') }));
  }, []);

  const go = (next: Partial<Omit<OverviewQuery, 'problems'>>) =>
    router.replace(overviewRoute({ q, filter, page: 1, view, ...next }));

  const data = read.data;
  const empty = data !== null && data.counts.integrations === 0;
  const verifiedOnce = data !== null && data.counts.verified > 0;
  const showChecklist = checklistOpen ?? (data !== null && !verifiedOnce);
  const statuses = data ? overviewStatuses(data) : [];
  const network = React.useMemo(
    () => (data && view === 'network' ? integrationsNetwork(data.integrations) : null),
    [data, view],
  );
  const layout = React.useMemo(() => (network ? networkLayout(network) : null), [network]);
  const lastPage = data ? Math.max(1, Math.ceil(data.total / INTEGRATIONS_PAGE_SIZE)) : 1;

  const stripItems: StatusStripItem[] = statuses.map((status) => ({
    id: status.id,
    tone: status.tone,
    label: status.label,
    detail: status.detail,
    title: status.title,
    body: status.body,
    actions: status.action ? (
      <Button size="sm" variant="outline" onClick={() => router.replace(status.action!.href)}>
        {status.action.label}
      </Button>
    ) : status.id === 'no-provider-contract' && canWrite ? (
      <Button size="sm" variant="outline" onClick={() => setCommand(commandFor('publish-provider-contract'))}>
        Publish provider contract
      </Button>
    ) : undefined,
  }));

  return (
    <Page>
      <PageHeader
        title="Contracts"
        breadcrumb={[CONTRACTS_CRUMBS[0], { label: 'Contracts' }]}
        description="What services need from each other, and whether a version can deploy."
        tabs={<ContractsTabs active="overview" />}
        actions={
          canWrite ? (
            <Button variant="outline" onClick={() => setCommand(commandFor('publish-provider-contract'))}>
              <FileCheck2 aria-hidden />
              Publish provider contract
            </Button>
          ) : undefined
        }
        overflow={
          canWrite
            ? {
                items: [
                  { id: 'verify', label: 'Run a verification', icon: ShieldCheck, onSelect: () => setCommand(commandFor('verify')) },
                  {
                    id: 'export',
                    label: 'Derive a pact from a project',
                    icon: WandSparkles,
                    onSelect: () => setCommand(commandFor('export-consumer-contract')),
                  },
                  { id: 'can-i-deploy', label: 'Can I deploy?', icon: Rocket, href: CAN_I_DEPLOY_ROUTE, separatorBefore: true },
                  { id: 'migrate', label: 'Migrate from a broker', icon: Import, href: MIGRATE_ROUTE },
                ],
              }
            : undefined
        }
        primaryAction={
          canWrite ? (
            <Button asChild data-testid="ctx-publish">
              <Link href={PUBLISH_ROUTE}>
                <FileUp aria-hidden />
                Publish a pact
              </Link>
            </Button>
          ) : undefined
        }
      />
      <PageBody>
        <div className="ctx" data-testid="pact-overview">
          {read.error ? (
            <ErrorBanner
              title="The integrations could not be read."
              description={read.error}
              onRetry={() => void load()}
              retryLabel="Try again"
              data-testid="ctx-error"
            />
          ) : stripItems.length > 0 ? (
            <StatusStrip aria-label="Contract status" caption="Needs you" storageKey="contracts:overview" items={stripItems} />
          ) : data && !empty ? (
            <DismissibleCallout id="contracts-explainer" reopenFrom="The Contracts guide in Help">
              <strong>A contract is what one service needs from another.</strong> Consumers publish pacts,
              providers publish their spec or verify against the pacts, and Apiome tells you whether a version
              is safe to deploy.
            </DismissibleCallout>
          ) : null}

          {data && !empty ? (
            <FactsLine
              page="contracts"
              aria-label="Contracts summary"
              facts={[
                { id: 'integrations', value: data.counts.integrations, label: data.counts.integrations === 1 ? 'integration' : 'integrations' },
                { id: 'verified', value: data.counts.verified, label: 'verified' },
                { id: 'pacticipants', value: data.pacticipants, label: data.pacticipants === 1 ? 'pacticipant' : 'pacticipants' },
                { id: 'environments', value: data.environments, label: data.environments === 1 ? 'environment' : 'environments' },
              ]}
              stats={
                health.data ? (
                  <HealthKpis counts={health.data.counts} totals={health.data.totals} />
                ) : (
                  <p className="ppx__muted" data-testid="ctx-stats-note">
                    {health.error ?? 'Rolling up the contract health…'}
                  </p>
                )
              }
            />
          ) : null}

          <section className="ctx-table-wrap" aria-label="Integrations">
            <div className="ctx-toolbar">
              <form
                className="ctx-search"
                role="search"
                onSubmit={(event) => {
                  event.preventDefault();
                  go({ q: search.trim() });
                }}
              >
                <Search className="ctx-search__glyph" aria-hidden />
                <input
                  className="ctx-search__input"
                  type="search"
                  value={search}
                  maxLength={MAX_SEARCH_LENGTH}
                  placeholder="Search consumers and providers…"
                  aria-label="Search integrations"
                  onChange={(event) => setSearch(event.target.value)}
                  data-testid="ctx-search"
                />
              </form>
              <div className="ctx-chips" role="group" aria-label="Filter">
                {INTEGRATION_FILTERS.filter((chip) => chip !== 'mine' || data?.mine_available !== false).map((chip) => (
                  <button
                    key={chip}
                    type="button"
                    className="ctx-chip"
                    aria-pressed={chip === filter}
                    onClick={() => go({ filter: chip })}
                    data-testid={`ctx-chip-${chip}`}
                  >
                    {FILTER_LABEL[chip]}
                    {data && chip !== 'all' ? (
                      <span className="ctx-chip__count">
                        {chip === 'failing'
                          ? data.counts.failing
                          : chip === 'stale'
                            ? data.counts.stale
                            : chip === 'bidirectional'
                              ? data.counts.bidirectional
                              : data.counts.mine}
                      </span>
                    ) : null}
                  </button>
                ))}
              </div>
              <span className="ctx-toolbar__spacer" />
              <Segmented
                size="sm"
                value={view}
                aria-label="View"
                onValueChange={(next) => go({ view: next === 'network' ? 'network' : 'table', page })}
              >
                <SegmentedItem value="table">
                  <Table2 aria-hidden />
                  Table
                </SegmentedItem>
                <SegmentedItem value="network">
                  <Waypoints aria-hidden />
                  Network
                </SegmentedItem>
              </Segmented>
            </div>

            {query.problems.length > 0 ? (
              <ul className="ctx-problems" data-testid="ctx-problems">
                {query.problems.map((problem) => (
                  <li key={problem}>{problem}</li>
                ))}
              </ul>
            ) : null}

            {read.error ? null : empty ? (
              <EmptyState
                variant="compact"
                titleAs="h2"
                title="No contracts yet"
                description="Record a pact from a consumer’s tests and publish it; both sides appear here."
                data-testid="ctx-empty"
              />
            ) : data && data.total === 0 ? (
              <EmptyState
                variant="compact"
                titleAs="h2"
                title="No integration matches"
                description={`Nothing matches ${q ? `“${q}”` : 'this filter'}. Clear the search or choose All.`}
                action={
                  <Button variant="outline" onClick={() => router.replace(overviewRoute({ view }))}>
                    Show every integration
                  </Button>
                }
                data-testid="ctx-no-match"
              />
            ) : view === 'network' && network && layout ? (
              <div className="ctx-network" data-testid="ctx-network">
                <NetworkGraphSvg network={network} layout={layout} />
                <p className="ppx__muted">The network of the integrations on this page.</p>
              </div>
            ) : (
              <IntegrationsTable rows={data ? data.integrations : null} />
            )}

            {data && data.total > 0 ? (
              <div className="ctx-table-foot">
                <span className="ppx__meta" data-testid="ctx-count">
                  {data.integrations.length} of {data.total} {data.total === 1 ? 'integration' : 'integrations'}
                  {data.truncated
                    ? ` — ${data.omitted_integrations} more are not listed: the first ${data.counts.integrations} were read. Search to narrow the list.`
                    : ''}
                </span>
                <div className="ctx-pager">
                  <Button size="sm" variant="outline" disabled={page <= 1} title={page <= 1 ? 'This is the first page' : undefined} onClick={() => go({ page: page - 1 })}>
                    Previous
                  </Button>
                  <Button size="sm" variant="outline" disabled={page >= lastPage} title={page >= lastPage ? 'This is the last page' : undefined} onClick={() => go({ page: page + 1 })}>
                    Next
                  </Button>
                </div>
              </div>
            ) : null}
          </section>

          {canWrite ? (
            <section className="ctx-start" aria-labelledby="ctx-start-h">
              <div className="ctx-start__head">
                <h2 className="ctx-start__title" id="ctx-start-h">
                  Start something
                </h2>
                {data && verifiedOnce ? (
                  <Button variant="link" size="sm" onClick={() => setChecklistOpen(!showChecklist)} aria-expanded={showChecklist}>
                    {showChecklist ? 'Hide the first-run checklist' : 'Show the first-run checklist'}
                  </Button>
                ) : null}
              </div>
              {showChecklist ? <FirstRunChecklist steps={firstRunSteps(data)} /> : null}
              <WaysIn onCommand={setCommand} />
            </section>
          ) : null}
        </div>
        <CommandDialog request={command} onClose={() => setCommand(null)} />
      </PageBody>
    </Page>
  );
}

