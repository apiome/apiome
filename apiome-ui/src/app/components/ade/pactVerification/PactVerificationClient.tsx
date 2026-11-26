'use client';

/**
 * **Verification** — `/ade/dashboard/pacts/pacticipants/{provider}/verification` (PFX-5.5, #6949).
 *
 * Where a provider's verification stands, and what to do about it:
 *
 * * **KPI strip** — pacts, verified, failing, stale, interactions passing, last verified.
 * * **Pacts** — each consumer's newest pact with its newest result; a pact version with no result
 *   is *stale*. Each row has **Re-run**, and the section has **Verify all stale**: both open the
 *   run dialog (a verification target, the provider version and branch) and run the hosted
 *   verifier, then show what it found — including every pact it did not run, with why. PFX-6.2
 *   (#6954) adds the cadence line, an *Overdue* badge for a pact past its stale threshold, the link
 *   to its open re-publish request, and why a scheduled run of it did not happen.
 * * **History** — every result of the provider, newest first, with its trigger, duration, build
 *   and interaction counts; **Consumer** narrows it (kept in the address as `?consumer=`); **Load
 *   more** pages. Each result opens its own page (expected vs actual, the log).
 *
 * Each section reads, fails and retries on its own; a run refreshes both.
 */

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { RefreshCw, ShieldCheck } from 'lucide-react';
import { Button, EmptyState, LoadingState } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { PACTICIPANTS_ROUTE, PUBLISH_SNIPPET, pacticipantRoute } from '@lib/pact-pacticipants';
import {
  verificationRoute,
  type ResultSummary,
  type RunBody,
  type TargetOption,
  type VerificationStatus,
  type VerificationStatusEntry,
} from '@lib/pact-verification';
import { CliSnippet } from '../pactPacticipants/PacticipantPanels';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { verifySnippet } from '../pactDetail/PactDetailClient';
import { CadenceLine, HistoryTable, KpiStrip, RunDialog, StatusTable, type RunRequest } from './VerificationPanels';
import {
  fetchTargetOptions,
  fetchVerificationHistory,
  fetchVerificationStatus,
  rerunVerification,
  verifyStale,
} from './pactVerificationApi';

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/** The status read. */
type StatusRead = { data: VerificationStatus | null; error: string | null };

/** The history read: the rows so far, the next cursor, and whether a page is loading. */
type HistoryRead = {
  results: ResultSummary[];
  next: string | null;
  loaded: boolean;
  loading: boolean;
  error: string | null;
};

/** The dialog: what it runs, and for a re-run which pact. */
type OpenRun = RunRequest & { entry?: VerificationStatusEntry };

/**
 * A section's frame: heading, an optional trailing node, and its body.
 *
 * @param props - The id stem, title, an optional trailing node and the body.
 * @returns The section.
 */
export function Panel({
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
export function SectionError({ title, error, onRetry }: { title: string; error: string; onRetry: () => void }) {
  return (
    <EmptyState
      variant="compact"
      titleAs="h3"
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
 * The provider's Verification page.
 *
 * @param props - The provider's handle and the `?consumer=` the history is narrowed to.
 * @returns The page.
 */
export default function PactVerificationClient({ slug, consumer }: { slug: string; consumer: string | null }) {
  const router = useRouter();
  const [status, setStatus] = React.useState<StatusRead>({ data: null, error: null });
  const [history, setHistory] = React.useState<HistoryRead>({
    results: [],
    next: null,
    loaded: false,
    loading: true,
    error: null,
  });
  const [open, setOpen] = React.useState<OpenRun | null>(null);
  const [targets, setTargets] = React.useState<TargetOption[] | null>(null);
  const [targetsError, setTargetsError] = React.useState<string | null>(null);
  /** Whether the open dialog ran something (the page is refreshed when it closes). */
  const ranRef = React.useRef(false);

  const loadStatus = React.useCallback(async () => {
    setStatus({ data: null, error: null });
    try {
      setStatus({ data: await fetchVerificationStatus(slug), error: null });
    } catch (caught) {
      setStatus({ data: null, error: describeFailure(caught, 'Could not load the verification status') });
    }
  }, [slug]);

  const loadHistory = React.useCallback(
    async (cursor: string | null = null) => {
      setHistory((current) => ({
        ...(cursor ? current : { results: [], next: null, loaded: false }),
        loading: true,
        error: null,
      }));
      try {
        const page = await fetchVerificationHistory(slug, { consumer, cursor });
        setHistory((current) => ({
          results: cursor ? [...current.results, ...page.results] : page.results,
          next: page.next_cursor,
          loaded: true,
          loading: false,
          error: null,
        }));
      } catch (caught) {
        setHistory((current) => ({
          ...current,
          loading: false,
          error: describeFailure(caught, 'Could not load the verification history'),
        }));
      }
    },
    [slug, consumer],
  );

  React.useEffect(() => {
    void loadStatus();
  }, [loadStatus]);
  React.useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  const refreshAll = () => {
    void loadStatus();
    void loadHistory();
  };

  const openRun = (request: OpenRun) => {
    setOpen(request);
    if (targets === null) {
      setTargetsError(null);
      fetchTargetOptions()
        .then(setTargets)
        .catch((caught) => setTargetsError(describeFailure(caught, 'Could not load the verification targets')));
    }
  };

  const closeRun = (ran: boolean) => {
    setOpen(null);
    if (ran) refreshAll();
  };

  const runOpen = async (body: RunBody) => {
    if (!open) throw new Error('Nothing to run.');
    const answer =
      open.mode === 'stale' || !open.entry
        ? await verifyStale(slug, body)
        : await rerunVerification(slug, open.entry.consumer, open.entry.pact_version_sha, body);
    ranRef.current = true;
    return answer;
  };

  const data = status.data;
  const name = data?.provider_name ?? slug;
  const stale = data?.counts.stale ?? 0;
  const consumers = data?.pacts ?? [];

  const narrow = (next: string) => {
    router.replace(verificationRoute(slug, next || null));
  };

  return (
    <Page>
      <PageHeader
        title={`${name} verification`}
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Pacticipants', href: PACTICIPANTS_ROUTE },
          { label: name, href: pacticipantRoute(slug) },
          { label: 'Verification' },
        ]}
        description="Verification results of the pacts this provider must honour: re-run one, verify the stale ones, read each result."
        actions={
          <Button variant="outline" onClick={refreshAll}>
            <RefreshCw aria-hidden />
            Refresh
          </Button>
        }
      />
      <PageBody>
        <div className="ppx pvx" data-testid="pact-verification">
          <Panel
            id="pvx-pacts"
            title="Pacts"
            aside={
              data && data.pacts.length > 0 ? (
                <Button
                  variant={stale > 0 ? 'default' : 'outline'}
                  size="sm"
                  disabled={stale === 0}
                  onClick={() => {
                    ranRef.current = false;
                    openRun({
                      mode: 'stale',
                      title: 'Verify all stale pacts',
                      description: `Replay the ${stale} stale ${stale === 1 ? 'pact' : 'pacts'} of ${name} against a verification target and publish a result for each.`,
                    });
                  }}
                  data-testid="pvx-verify-stale"
                >
                  <ShieldCheck aria-hidden />
                  Verify all stale ({stale})
                </Button>
              ) : null
            }
          >
            {status.error ? (
              <SectionError
                title="The verification status could not be read"
                error={status.error}
                onRetry={() => void loadStatus()}
              />
            ) : data === null ? (
              <LoadingState message="Reading the verification status…" minHeightClassName="min-h-[4rem]" />
            ) : data.pacts.length === 0 ? (
              <div className="ppx__empty-note" data-testid="pvx-empty">
                <EmptyState
                  variant="compact"
                  titleAs="h3"
                  title="No pacts to verify"
                  description={`No consumer has published a pact with ${name} yet. A consumer's build publishes its pacts:`}
                />
                <CliSnippet label="Publish a pact" command={PUBLISH_SNIPPET} />
              </div>
            ) : (
              <>
                <KpiStrip counts={data.counts} />
                <CadenceLine settings={data.settings} />
                {data.truncated ? (
                  <p className="ppx__muted">Only the first 500 consumers are listed.</p>
                ) : null}
                <StatusTable
                  entries={data.pacts}
                  provider={slug}
                  onRerun={(entry) => {
                    ranRef.current = false;
                    openRun({
                      mode: 'rerun',
                      entry,
                      title: `Re-run ${entry.consumer_name}'s pact`,
                      description: `Replay the pact of ${entry.consumer_name} version ${entry.consumer_version} against a verification target and publish the result.`,
                      providerVersion: entry.latest_result?.provider_version ?? null,
                      providerBranch: entry.latest_result?.provider_branch ?? null,
                    });
                  }}
                />
              </>
            )}
          </Panel>

          <Panel
            id="pvx-history"
            title="History"
            aside={
              consumers.length > 0 ? (
                <label className="pmx-field pvx-filter" htmlFor="pvx-consumer">
                  <span className="sr-only">Consumer</span>
                  <select
                    id="pvx-consumer"
                    className="pmx-input pmx-select--narrow"
                    value={consumer ?? ''}
                    onChange={(event) => narrow(event.target.value)}
                    data-testid="pvx-consumer-filter"
                  >
                    <option value="">Every consumer</option>
                    {consumers.map((entry) => (
                      <option key={entry.consumer} value={entry.consumer}>
                        {entry.consumer_name}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null
            }
          >
            {history.error && !history.loaded ? (
              <SectionError
                title="The verification history could not be read"
                error={history.error}
                onRetry={() => void loadHistory()}
              />
            ) : !history.loaded ? (
              <LoadingState message="Reading the verification history…" minHeightClassName="min-h-[4rem]" />
            ) : history.results.length === 0 ? (
              <div className="ppx__empty-note" data-testid="pvx-history-empty">
                <p className="ppx__statement">
                  No verification result yet{consumer ? ' for this consumer' : ''}. Run your Pact verifier in the
                  provider&apos;s build with result publishing on, or replay the pacts against a registered
                  verification target:
                </p>
                <CliSnippet label="Verify the pacts of a provider" command={verifySnippet(name)} />
              </div>
            ) : (
              <>
                <HistoryTable results={history.results} provider={slug} />
                {history.error ? <p className="ppx__error">{history.error}</p> : null}
                {history.next ? (
                  <div className="ppx__more">
                    <Button
                      variant="outline"
                      onClick={() => void loadHistory(history.next)}
                      disabled={history.loading}
                      data-testid="pvx-history-more"
                    >
                      {history.loading ? 'Loading…' : 'Load more'}
                    </Button>
                  </div>
                ) : null}
              </>
            )}
            {consumer ? (
              <p className="ppx__muted">
                Narrowed to one consumer.{' '}
                <Link className="ppx__link" href={verificationRoute(slug)}>
                  Show every consumer
                </Link>
              </p>
            ) : null}
          </Panel>
        </div>
        {open ? (
          <RunDialog
            request={open}
            targets={targets}
            targetsError={targetsError}
            onRun={runOpen}
            onClose={() => closeRun(ranRef.current)}
          />
        ) : null}
      </PageBody>
    </Page>
  );
}
