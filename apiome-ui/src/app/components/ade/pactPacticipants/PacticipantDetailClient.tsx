'use client';

/**
 * **A pacticipant** — `/ade/dashboard/pacts/pacticipants/{handle}` (PFX-5.1, #6945).
 *
 * One application of the workspace's Pact Broker: its handle, main branch, repository, labels and
 * bindings; its **Branches** with their head versions; what each **Environment** runs of it now
 * (deployed versions and supported releases); its **Pacts** — every integration it is the consumer
 * or provider of, each linking to its newest pact (PFX-5.2, #6946), and a link to its **Network**
 * diagram (PFX-5.3, #6947); and its **Versions**, latest
 * recorded first, with their branches and tags. Its **Owner** team (PFX-6.4, #6956) receives the
 * Pact findings about it. Choosing a branch or a tag anywhere on the page narrows the versions to
 * it; **Clear** widens them again. Its **Settings** tab (PFX-8.10, #7307) edits, renames and deletes it.
 *
 * ### What this page owns
 *
 * The five reads and the version filter. Each section loads and fails on its own, with its own
 * **Try again**, so a broker that cannot list environments still shows the versions. How each
 * section is drawn is `PacticipantPanels`; labels, paths and formatting are `@lib/pact-pacticipants`.
 */

import * as React from 'react';
import Link from 'next/link';
import { RefreshCw, X } from 'lucide-react';
import { Button, EmptyState, LoadingState } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { ContractsTabs } from '../pactOverview/ContractsTabs';
import { CONTRACTS_ROUTE } from '@lib/pact-overview';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import {
  PACTICIPANTS_ROUTE,
  PUBLISH_SNIPPET,
  versionsSummary,
  type Pacticipant,
  type PacticipantBranch,
  type PacticipantEnvironment,
  type PacticipantVersion,
} from '@lib/pact-pacticipants';
import { BranchesTable, CliSnippet, EnvironmentsTable, PacticipantFacts, VersionsTable } from './PacticipantPanels';
import { fetchBranches, fetchEnvironments, fetchPacticipant, fetchVersions } from './pacticipantsApi';
import PacticipantOwnerPanel from './PacticipantOwnerPanel';
import { PacticipantSubTabs } from './PacticipantSubTabs';
import { describeFailure } from './describeFailure';
import { PacticipantPactsTable } from '../pactDetail/PactPanels';
import { fetchPacticipantPacts } from '../pactDetail/pactDetailApi';
import type { PacticipantPacts } from '@lib/pact-detail';
import { networkRoute } from '@lib/pact-network';
import { verificationRoute } from '@lib/pact-verification';

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/** A section's read: loading (`null`), failed (`error`), or loaded. */
type Section<T> = { data: T | null; error: string | null };

/** The version filter in force. */
interface VersionFilter {
  branch: string | null;
  tag: string | null;
}

/** The loaded versions and where the next page starts. */
interface VersionList {
  rows: PacticipantVersion[];
  nextCursor: string | null;
}

/**
 * A section's frame: heading, an optional count, and its body.
 *
 * @param props - The id stem, title, an optional trailing node and the body.
 * @returns The section.
 */
function Panel({
  id,
  title,
  aside,
  children,
}: {
  id: string;
  title: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="ppx__panel" aria-labelledby={`${id}-title`} data-testid={id}>
      <div className="ppx__panel-head">
        <h2 id={`${id}-title`} className="ppx__title">
          {title}
        </h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

/**
 * A section that failed to read, with its retry.
 *
 * @param props - What failed, why, and how to retry.
 * @returns The notice.
 */
function SectionError({ title, error, onRetry }: { title: string; error: string; onRetry: () => void }) {
  return (
    <EmptyState
      variant="compact"
      tone="danger"
      title={title}
      description={error}
      action={
        <Button variant="soft" onClick={onRetry}>
          <RefreshCw aria-hidden />
          Try again
        </Button>
      }
    />
  );
}

/**
 * The pacticipant page.
 *
 * @param props - The pacticipant's handle, from the route.
 * @returns The page.
 */
export default function PacticipantDetailClient({ slug }: { slug: string }) {
  const [pacticipant, setPacticipant] = React.useState<Section<Pacticipant>>({ data: null, error: null });
  const [branches, setBranches] = React.useState<Section<PacticipantBranch[]>>({ data: null, error: null });
  const [moreBranches, setMoreBranches] = React.useState(false);
  const [environments, setEnvironments] = React.useState<Section<PacticipantEnvironment[]>>({
    data: null,
    error: null,
  });
  const [pacts, setPacts] = React.useState<Section<PacticipantPacts>>({ data: null, error: null });
  const [filter, setFilter] = React.useState<VersionFilter>({ branch: null, tag: null });
  const [versions, setVersions] = React.useState<Section<VersionList>>({ data: null, error: null });
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [moreError, setMoreError] = React.useState<string | null>(null);
  const [ownerRefresh, setOwnerRefresh] = React.useState(0);

  const loadPacticipant = React.useCallback(async () => {
    setPacticipant({ data: null, error: null });
    try {
      setPacticipant({ data: await fetchPacticipant(slug), error: null });
    } catch (caught) {
      setPacticipant({ data: null, error: describeFailure(caught, 'Could not load the pacticipant') });
    }
  }, [slug]);

  const loadBranches = React.useCallback(async () => {
    setBranches({ data: null, error: null });
    try {
      // The first page (100 branches) is what the page shows; the count reads `100+` when there are more.
      const page = await fetchBranches(slug);
      setBranches({ data: page.branches, error: null });
      setMoreBranches(page.has_more);
    } catch (caught) {
      setBranches({ data: null, error: describeFailure(caught, 'Could not load the branches') });
    }
  }, [slug]);

  const loadEnvironments = React.useCallback(async () => {
    setEnvironments({ data: null, error: null });
    try {
      setEnvironments({ data: (await fetchEnvironments(slug)).environments, error: null });
    } catch (caught) {
      setEnvironments({ data: null, error: describeFailure(caught, 'Could not load the environments') });
    }
  }, [slug]);

  const loadPacts = React.useCallback(async () => {
    setPacts({ data: null, error: null });
    try {
      setPacts({ data: await fetchPacticipantPacts(slug), error: null });
    } catch (caught) {
      setPacts({ data: null, error: describeFailure(caught, 'Could not load the pacts') });
    }
  }, [slug]);

  const loadVersions = React.useCallback(
    async (next: VersionFilter) => {
      setVersions({ data: null, error: null });
      setMoreError(null);
      try {
        const page = await fetchVersions(slug, next);
        setVersions({
          data: { rows: page.versions, nextCursor: page.has_more ? (page.next_cursor ?? null) : null },
          error: null,
        });
      } catch (caught) {
        setVersions({ data: null, error: describeFailure(caught, 'Could not load the versions') });
      }
    },
    [slug],
  );

  const loadMoreVersions = React.useCallback(async () => {
    const current = versions.data;
    if (!current?.nextCursor) return;
    setLoadingMore(true);
    setMoreError(null);
    try {
      const page = await fetchVersions(slug, { ...filter, cursor: current.nextCursor });
      setVersions({
        data: {
          rows: [...current.rows, ...page.versions],
          nextCursor: page.has_more ? (page.next_cursor ?? null) : null,
        },
        error: null,
      });
    } catch (caught) {
      setMoreError(describeFailure(caught, 'Could not load more versions'));
    } finally {
      setLoadingMore(false);
    }
  }, [filter, slug, versions.data]);

  const refreshAll = React.useCallback(() => {
    void loadPacticipant();
    void loadBranches();
    void loadEnvironments();
    void loadPacts();
    void loadVersions(filter);
    setOwnerRefresh((count) => count + 1);
  }, [filter, loadBranches, loadEnvironments, loadPacticipant, loadPacts, loadVersions]);

  React.useEffect(() => {
    void loadPacticipant();
    void loadBranches();
    void loadEnvironments();
    void loadPacts();
  }, [loadPacticipant, loadBranches, loadEnvironments, loadPacts]);

  React.useEffect(() => {
    void loadVersions(filter);
  }, [filter, loadVersions]);

  const pickBranch = React.useCallback((branch: string) => setFilter((f) => ({ ...f, branch })), []);
  const pickTag = React.useCallback((tag: string) => setFilter((f) => ({ ...f, tag })), []);
  const clearFilter = React.useCallback(() => setFilter({ branch: null, tag: null }), []);

  const name = pacticipant.data?.name ?? slug;
  const filtered = Boolean(filter.branch || filter.tag);

  return (
    <Page>
      <PageHeader
        tabs={<ContractsTabs active="pacticipants" />}
        title={name}
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Contracts', href: CONTRACTS_ROUTE },
          { label: 'Pacticipants', href: PACTICIPANTS_ROUTE },
          { label: name },
        ]}
        description="Versions, branches, tags and environments of one application."
        actions={
          <Button variant="outline" onClick={refreshAll}>
            <RefreshCw aria-hidden />
            Refresh
          </Button>
        }
      />
      <PageBody>
        <div className="ppx" data-testid="pact-pacticipant">
          <PacticipantSubTabs slug={slug} active="overview" />
          {pacticipant.error ? (
            <EmptyState
              variant="compact"
              tone="danger"
              title="This pacticipant could not be read"
              description={pacticipant.error}
              action={
                <div className="ppx__actions">
                  <Button variant="soft" onClick={() => void loadPacticipant()}>
                    <RefreshCw aria-hidden />
                    Try again
                  </Button>
                  <Link className="ppx__link" href={PACTICIPANTS_ROUTE}>
                    All pacticipants
                  </Link>
                </div>
              }
            />
          ) : pacticipant.data === null ? (
            <LoadingState message="Reading the pacticipant…" minHeightClassName="min-h-[6rem]" />
          ) : (
            <>
              <Panel id="ppx-overview" title="Overview">
                <PacticipantFacts pacticipant={pacticipant.data} />
              </Panel>

              <PacticipantOwnerPanel pacticipantId={pacticipant.data.id} refreshKey={ownerRefresh} />

              <Panel
                id="ppx-branches"
                title="Branches"
                aside={
                  branches.data ? (
                    <span className="ppx__meta" data-testid="ppx-branches-count">
                      {branches.data.length}
                      {moreBranches ? '+' : ''}
                    </span>
                  ) : null
                }
              >
                {branches.error ? (
                  <SectionError
                    title="The branches could not be read"
                    error={branches.error}
                    onRetry={() => void loadBranches()}
                  />
                ) : branches.data === null ? (
                  <LoadingState message="Reading the branches…" minHeightClassName="min-h-[4rem]" />
                ) : branches.data.length === 0 ? (
                  <p className="ppx__statement">
                    No branch yet. A version recorded with a branch (<code className="ppx__mono">--branch</code>)
                    adds it.
                  </p>
                ) : (
                  <BranchesTable branches={branches.data} onPickBranch={pickBranch} />
                )}
              </Panel>

              <Panel id="ppx-environments" title="Environments">
                {environments.error ? (
                  <SectionError
                    title="The environments could not be read"
                    error={environments.error}
                    onRetry={() => void loadEnvironments()}
                  />
                ) : environments.data === null ? (
                  <LoadingState message="Reading the environments…" minHeightClassName="min-h-[4rem]" />
                ) : (
                  <EnvironmentsTable environments={environments.data} pacticipantName={pacticipant.data.name} />
                )}
              </Panel>

              <Panel
                id="ppx-pacts"
                title="Pacts"
                aside={
                  pacts.data ? (
                    <>
                      <span className="ppx__meta" data-testid="ppx-pacts-count">
                        {pacts.data.pacts.length}
                        {pacts.data.truncated ? '+' : ''}
                      </span>
                      <span className="ppx__actions ppx__panel-link">
                        {pacts.data.pacts.length > 0 ? (
                          <Link className="ppx__link" href={networkRoute(slug)} data-testid="ppx-network-link">
                            Network diagram
                          </Link>
                        ) : null}
                        {pacts.data.pacts.some((pact) => pact.provider.slug === slug) ? (
                          <Link
                            className="ppx__link"
                            href={verificationRoute(slug)}
                            data-testid="ppx-verification-link"
                          >
                            Verification
                          </Link>
                        ) : null}
                      </span>
                    </>
                  ) : null
                }
              >
                {pacts.error ? (
                  <SectionError title="The pacts could not be read" error={pacts.error} onRetry={() => void loadPacts()} />
                ) : pacts.data === null ? (
                  <LoadingState message="Reading the pacts…" minHeightClassName="min-h-[4rem]" />
                ) : pacts.data.pacts.length === 0 ? (
                  <div className="ppx__empty-note" data-testid="ppx-pacts-empty">
                    <p className="ppx__statement">
                      No pact names this pacticipant yet. A consumer&apos;s build publishes its pacts:
                    </p>
                    <CliSnippet label="Publish a pact" command={PUBLISH_SNIPPET} />
                  </div>
                ) : (
                  <PacticipantPactsTable pacts={pacts.data.pacts} slug={slug} />
                )}
              </Panel>

              <Panel
                id="ppx-versions"
                title="Versions"
                aside={
                  versions.data ? (
                    <span className="ppx__meta" data-testid="ppx-versions-summary">
                      {versionsSummary(versions.data.rows.length, Boolean(versions.data.nextCursor), filter)}
                    </span>
                  ) : null
                }
              >
                {filtered ? (
                  <div className="ppx__filters" role="group" aria-label="Version filter">
                    {filter.branch ? <span className="ppx__filter">Branch: {filter.branch}</span> : null}
                    {filter.tag ? <span className="ppx__filter">Tag: {filter.tag}</span> : null}
                    <Button variant="ghost" size="sm" onClick={clearFilter}>
                      <X aria-hidden />
                      Clear
                    </Button>
                  </div>
                ) : null}
                {versions.error ? (
                  <SectionError
                    title="The versions could not be read"
                    error={versions.error}
                    onRetry={() => void loadVersions(filter)}
                  />
                ) : versions.data === null ? (
                  <LoadingState message="Reading the versions…" minHeightClassName="min-h-[4rem]" />
                ) : versions.data.rows.length === 0 ? (
                  <p className="ppx__statement">
                    {filtered
                      ? 'No version matches this filter.'
                      : 'No version yet. Publishing a pact or recording a version adds one.'}
                  </p>
                ) : (
                  <>
                    <VersionsTable versions={versions.data.rows} onPickBranch={pickBranch} onPickTag={pickTag} />
                    {moreError ? (
                      <p className="ppx__error" role="alert">
                        {moreError}
                      </p>
                    ) : null}
                    {versions.data.nextCursor ? (
                      <div className="ppx__more">
                        <Button variant="outline" onClick={() => void loadMoreVersions()} disabled={loadingMore}>
                          {loadingMore ? 'Loading…' : 'Load more'}
                        </Button>
                      </div>
                    ) : null}
                  </>
                )}
              </Panel>
            </>
          )}
        </div>
      </PageBody>
    </Page>
  );
}
