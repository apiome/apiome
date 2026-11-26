'use client';

/**
 * **Pacticipants** — `/ade/dashboard/pacts/pacticipants` (PFX-5.1, #6945).
 *
 * The applications registered in the workspace's Pact Broker, by handle: main branch, labels,
 * repository and when each was last changed. The **Label** filter narrows the list to the
 * pacticipants carrying one label; **Load more** reads the next page. Each name opens the
 * pacticipant's page (versions, branches, tags, environments).
 *
 * A workspace with no pacticipant shows the CLI command that registers them: publishing a pact
 * registers its consumer and its provider.
 */

import * as React from 'react';
import { RefreshCw } from 'lucide-react';
import { Button, EmptyState, LoadingState } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { PUBLISH_SNIPPET, type Pacticipant } from '@lib/pact-pacticipants';
import { CliSnippet, PacticipantsTable } from './PacticipantPanels';
import { fetchLabels, fetchPacticipants } from './pacticipantsApi';
import { describeFailure } from './describeFailure';

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/** The loaded rows and where the next page starts. */
interface ListState {
  rows: Pacticipant[];
  nextCursor: string | null;
}

/**
 * The Pacticipants page.
 *
 * @returns The page.
 */
export default function PacticipantsListClient() {
  const [label, setLabel] = React.useState<string>('');
  const [labels, setLabels] = React.useState<string[]>([]);
  const [list, setList] = React.useState<ListState | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [moreError, setMoreError] = React.useState<string | null>(null);

  const load = React.useCallback(async (filter: string) => {
    setList(null);
    setError(null);
    setMoreError(null);
    try {
      const page = await fetchPacticipants({ label: filter || null });
      setList({ rows: page.pacticipants, nextCursor: page.has_more ? (page.next_cursor ?? null) : null });
    } catch (caught) {
      setError(describeFailure(caught, 'Could not load the pacticipants'));
    }
  }, []);

  const loadMore = React.useCallback(async () => {
    if (!list?.nextCursor) return;
    setLoadingMore(true);
    setMoreError(null);
    try {
      const page = await fetchPacticipants({ label: label || null, cursor: list.nextCursor });
      setList({
        rows: [...list.rows, ...page.pacticipants],
        nextCursor: page.has_more ? (page.next_cursor ?? null) : null,
      });
    } catch (caught) {
      setMoreError(describeFailure(caught, 'Could not load more pacticipants'));
    } finally {
      setLoadingMore(false);
    }
  }, [label, list]);

  React.useEffect(() => {
    void load(label);
  }, [label, load]);

  React.useEffect(() => {
    // The filter is a convenience: without labels the list still reads, so a failure only hides it.
    fetchLabels()
      .then(setLabels)
      .catch(() => setLabels([]));
  }, []);

  return (
    <Page>
      <PageHeader
        title="Pacticipants"
        breadcrumb={[{ label: 'Home', href: HOME_ROUTE }, { label: 'Pacticipants' }]}
        description="The applications that take part in this workspace's pacts."
        actions={
          <Button variant="outline" onClick={() => void load(label)}>
            <RefreshCw aria-hidden />
            Refresh
          </Button>
        }
      />
      <PageBody>
        <div className="ppx" data-testid="pact-pacticipants">
          {labels.length > 0 || label ? (
            <div className="ppx__toolbar">
              <label className="ppx__field">
                <span className="ppx__field-label">Label</span>
                <select
                  className="ppx__select"
                  value={label}
                  onChange={(event) => setLabel(event.target.value)}
                  data-testid="ppx-label-filter"
                >
                  <option value="">All labels</option>
                  {labels.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          ) : null}
          {error ? (
            <EmptyState
              variant="compact"
              tone="danger"
              title="The pacticipants could not be read"
              description={error}
              action={
                <Button variant="soft" onClick={() => void load(label)}>
                  <RefreshCw aria-hidden />
                  Try again
                </Button>
              }
            />
          ) : list === null ? (
            <LoadingState message="Reading the pacticipants…" minHeightClassName="min-h-[6rem]" />
          ) : list.rows.length === 0 ? (
            label ? (
              <EmptyState
                variant="compact"
                title={`No pacticipant carries the label ${label}`}
                description="Choose another label, or All labels."
              />
            ) : (
              <EmptyState
                variant="compact"
                title="No pacticipants yet"
                description="Publishing a pact registers its consumer and its provider. From the consumer's build, run:"
                action={<CliSnippet label="Publish pacts" command={PUBLISH_SNIPPET} />}
              />
            )
          ) : (
            <>
              <p className="ppx__meta" data-testid="ppx-count">
                {list.rows.length}
                {list.nextCursor ? '+' : ''} {list.rows.length === 1 && !list.nextCursor ? 'pacticipant' : 'pacticipants'}
                {label ? ` with the label ${label}` : ''}
              </p>
              <PacticipantsTable pacticipants={list.rows} />
              {moreError ? (
                <p className="ppx__error" role="alert">
                  {moreError}
                </p>
              ) : null}
              {list.nextCursor ? (
                <div className="ppx__more">
                  <Button variant="outline" onClick={() => void loadMore()} disabled={loadingMore}>
                    {loadingMore ? 'Loading…' : 'Load more'}
                  </Button>
                </div>
              ) : null}
            </>
          )}
        </div>
      </PageBody>
    </Page>
  );
}
