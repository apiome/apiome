'use client';

/**
 * **A pact** — `/ade/dashboard/pacts/pacticipants/{consumer}/pacts/{provider}` (PFX-5.2, #6946).
 *
 * One integration's pact, as one consumer version published it (`?version=`, or the latest):
 *
 * * **Overview** — the consumer and provider, the consumer version, the pact version (content
 *   SHA), the specification, when it was published and how many interactions it has.
 * * **Verification status** — the newest result's verdict and every provider version that
 *   verified this pact, with how (a Pact verifier or Apiome's bi-directional comparison) and
 *   whether it was pending or work in progress.
 * * **Changes since the previous pact** — the previous *different* pact of the integration and
 *   the interactions added, changed (with the values) and removed since.
 * * **Interactions** — each interaction with its provider states and its request and response
 *   (or its message); new and changed ones are marked.
 * * **History** — the integration's consumer versions, newest first, with their verdicts; each
 *   opens its own pact here.
 *
 * ### What this page owns
 *
 * The three reads (the pact, the previous pact, the history) and the open version. Each section
 * loads and fails on its own, with its own **Try again**. How each section is drawn is
 * `PactPanels`; parsing, diffing and wording are `@lib/pact-detail`.
 */

import * as React from 'react';
import Link from 'next/link';
import { RefreshCw } from 'lucide-react';
import { Button, EmptyState, LoadingState } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import {
  PACTICIPANTS_ROUTE,
  PUBLISH_SNIPPET,
  formatWhen,
  pacticipantRoute,
  shortVersion,
} from '@lib/pact-pacticipants';
import {
  PREVIOUS_OUTCOME_TEXT,
  diffPacts,
  diffSummary,
  interactionStatuses,
  latestVerification,
  pactRoute,
  parsePact,
  type PactHistory,
  type PreviousPactResponse,
} from '@lib/pact-detail';
import { CliSnippet } from '../pactPacticipants/PacticipantPanels';
import { describeFailure } from '../pactPacticipants/describeFailure';
import {
  ChangesList,
  HistoryTable,
  InteractionList,
  PactFacts,
  VerdictBadge,
  VerificationTable,
} from './PactPanels';
import { fetchPact, fetchPactHistory, fetchPreviousPact, type LoadedPact } from './pactDetailApi';

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/**
 * The CLI command an unverified pact shows: hosted verification against a registered target.
 *
 * @param provider - The provider's display name.
 * @returns The command.
 */
export function verifySnippet(provider: string): string {
  return `apiome pact verify --provider "${provider}" --provider-app-version "$GIT_COMMIT" --target staging`;
}

/** A section's read: loading (`data` null, no error), failed (`error`), or loaded. */
type Section<T> = { data: T | null; error: string | null; loaded: boolean };

/** A section that is loading. */
function loading<T>(): Section<T> {
  return { data: null, error: null, loaded: false };
}

/**
 * A section's frame: heading, an optional trailing node, and its body.
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
function SectionError({
  title,
  error,
  onRetry,
}: {
  title: string;
  error: string;
  onRetry: () => void;
}) {
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
 * The pact page.
 *
 * @param props - The consumer's and provider's handles from the route, and the `?version=` asked for.
 * @returns The page.
 */
export default function PactDetailClient({
  consumer,
  provider,
  initialVersion = null,
}: {
  consumer: string;
  provider: string;
  initialVersion?: string | null;
}) {
  const [version, setVersion] = React.useState<string | null>(initialVersion);
  const [pact, setPact] = React.useState<Section<LoadedPact>>(loading);
  const [previous, setPrevious] = React.useState<Section<PreviousPactResponse>>(loading);
  const [history, setHistory] = React.useState<Section<PactHistory>>(loading);

  const loadPact = React.useCallback(async () => {
    setPact(loading());
    try {
      setPact({ data: await fetchPact(provider, consumer, version), error: null, loaded: true });
    } catch (caught) {
      setPact({
        data: null,
        error: describeFailure(caught, 'Could not load the pact'),
        loaded: true,
      });
    }
  }, [consumer, provider, version]);

  const loadPrevious = React.useCallback(async () => {
    setPrevious(loading());
    try {
      setPrevious({
        data: await fetchPreviousPact(provider, consumer, version),
        error: null,
        loaded: true,
      });
    } catch (caught) {
      setPrevious({
        data: null,
        error: describeFailure(caught, 'Could not load the previous pact'),
        loaded: true,
      });
    }
  }, [consumer, provider, version]);

  const loadHistory = React.useCallback(async () => {
    setHistory(loading());
    try {
      setHistory({ data: await fetchPactHistory(provider, consumer), error: null, loaded: true });
    } catch (caught) {
      setHistory({
        data: null,
        error: describeFailure(caught, 'Could not load the history'),
        loaded: true,
      });
    }
  }, [consumer, provider]);

  React.useEffect(() => {
    void loadPact();
    void loadPrevious();
  }, [loadPact, loadPrevious]);

  React.useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  /** Open another consumer version's pact, and keep the address shareable. */
  const openVersion = React.useCallback(
    (next: string) => {
      setVersion(next);
      if (typeof window !== 'undefined')
        window.history.replaceState(null, '', pactRoute(consumer, provider, next));
    },
    [consumer, provider],
  );

  const refreshAll = React.useCallback(() => {
    void loadPact();
    void loadPrevious();
    void loadHistory();
  }, [loadHistory, loadPact, loadPrevious]);

  const view = pact.data?.view ?? null;
  const diff = React.useMemo(() => {
    const found = previous.data?.previous;
    return view && found ? diffPacts(view, parsePact(found.document)) : null;
  }, [previous.data, view]);
  const statuses = React.useMemo(() => interactionStatuses(diff), [diff]);
  const openVersionNumber = view?.consumerVersion ?? version;
  const entry =
    history.data?.entries.find((row) => row.consumerVersion === openVersionNumber) ?? null;

  const consumerName = view?.consumerName || consumer;
  const providerName = view?.providerName || provider;

  return (
    <Page>
      <PageHeader
        title={`${consumerName} → ${providerName}`}
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Pacticipants', href: PACTICIPANTS_ROUTE },
          { label: consumerName, href: pacticipantRoute(consumer) },
          { label: `Pact with ${providerName}` },
        ]}
        description="The interactions one consumer version expects of its provider, and how they were verified."
        actions={
          <Button variant="outline" onClick={refreshAll}>
            <RefreshCw aria-hidden />
            Refresh
          </Button>
        }
      />
      <PageBody>
        <div className="ppx" data-testid="pact-detail">
          {pact.error ? (
            <SectionError
              title="This pact could not be read"
              error={pact.error}
              onRetry={() => void loadPact()}
            />
          ) : !pact.loaded ? (
            <LoadingState message="Reading the pact…" minHeightClassName="min-h-[6rem]" />
          ) : view === null ? (
            <div className="ppx__empty-note" data-testid="ppd-empty">
              <EmptyState
                variant="compact"
                title={version ? `No pact for version ${version}` : 'No pact yet'}
                description={
                  version
                    ? `${consumer} has no pact with ${provider} at this version.`
                    : `${consumer} has not published a pact for ${provider}. Publish one from the consumer's build:`
                }
                action={
                  <Link className="ppx__link" href={pacticipantRoute(consumer)}>
                    Back to {consumer}
                  </Link>
                }
              />
              <CliSnippet label="Publish a pact" command={PUBLISH_SNIPPET} />
            </div>
          ) : (
            <>
              <Panel id="ppd-overview" title="Overview">
                <PactFacts pact={view} consumer={consumer} provider={provider} />
              </Panel>

              <Panel
                id="ppd-verification"
                title="Verification status"
                aside={
                  entry ? <VerdictBadge latest={latestVerification(entry.verifications)} /> : null
                }
              >
                {history.error ? (
                  <SectionError
                    title="The verification results could not be read"
                    error={history.error}
                    onRetry={() => void loadHistory()}
                  />
                ) : !history.loaded ? (
                  <LoadingState
                    message="Reading the verification results…"
                    minHeightClassName="min-h-[4rem]"
                  />
                ) : entry === null ? (
                  <p className="ppx__statement">
                    This version is older than the history read here, so its verification results
                    are not shown.
                  </p>
                ) : entry.verifications.length === 0 ? (
                  <div className="ppx__empty-note">
                    <p className="ppx__statement">
                      Not verified yet. Run your Pact verifier in the provider&apos;s build with
                      result publishing on, or replay the pact against a registered verification
                      target:
                    </p>
                    <CliSnippet
                      label="Verify the pacts of a provider"
                      command={verifySnippet(providerName)}
                    />
                  </div>
                ) : (
                  <VerificationTable verifications={entry.verifications} />
                )}
              </Panel>

              <Panel
                id="ppd-changes"
                title="Changes since the previous pact"
                aside={
                  diff ? (
                    <span className="ppx__meta" data-testid="ppd-diff-summary">
                      {diffSummary(diff)}
                    </span>
                  ) : null
                }
              >
                {previous.error ? (
                  <SectionError
                    title="The previous pact could not be read"
                    error={previous.error}
                    onRetry={() => void loadPrevious()}
                  />
                ) : !previous.loaded || previous.data === null ? (
                  <LoadingState
                    message="Comparing with the previous pact…"
                    minHeightClassName="min-h-[4rem]"
                  />
                ) : previous.data.outcome !== 'found' || !previous.data.previous || !diff ? (
                  <p className="ppx__statement" data-testid="ppd-previous-outcome">
                    {previous.data.outcome === 'found'
                      ? 'The previous pact could not be compared.'
                      : PREVIOUS_OUTCOME_TEXT[previous.data.outcome]}
                  </p>
                ) : (
                  <>
                    <p className="ppx__statement">
                      Compared with version{' '}
                      <button
                        type="button"
                        className="ppx__chip-button ppx__mono"
                        onClick={() => openVersion(previous.data!.previous!.consumerVersion)}
                        aria-label={`Open the pact of version ${previous.data.previous.consumerVersion}`}
                        title={previous.data.previous.consumerVersion}
                      >
                        {shortVersion(previous.data.previous.consumerVersion)}
                      </button>
                      , published {formatWhen(previous.data.previous.publishedAt)}.
                    </p>
                    <ChangesList diff={diff} />
                  </>
                )}
              </Panel>

              <Panel
                id="ppd-interactions"
                title="Interactions"
                aside={<span className="ppx__meta">{view.interactions.length}</span>}
              >
                {view.interactions.length === 0 ? (
                  <p className="ppx__statement">This pact has no interactions.</p>
                ) : (
                  <InteractionList interactions={view.interactions} statuses={statuses} />
                )}
              </Panel>

              <Panel
                id="ppd-history"
                title="History"
                aside={
                  history.data ? (
                    <span className="ppx__meta" data-testid="ppd-history-count">
                      {history.data.entries.length}
                      {history.data.truncated ? '+' : ''} versions
                    </span>
                  ) : null
                }
              >
                {history.error ? (
                  <SectionError
                    title="The history could not be read"
                    error={history.error}
                    onRetry={() => void loadHistory()}
                  />
                ) : !history.loaded || history.data === null ? (
                  <LoadingState message="Reading the history…" minHeightClassName="min-h-[4rem]" />
                ) : history.data.entries.length === 0 ? (
                  <p className="ppx__statement">
                    No consumer version of this integration is in the matrix yet.
                  </p>
                ) : (
                  <>
                    <HistoryTable
                      entries={history.data.entries}
                      openVersion={openVersionNumber}
                      onOpen={openVersion}
                    />
                    {history.data.truncated ? (
                      <p className="ppx__muted">
                        Only the newest results are read; older versions are not listed.
                      </p>
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
