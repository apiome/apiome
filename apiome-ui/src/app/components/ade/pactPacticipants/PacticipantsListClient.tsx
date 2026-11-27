'use client';

/**
 * **Pacticipants** — `/ade/dashboard/pacts/pacticipants` (PFX-5.1, #6945).
 *
 * The applications registered in the workspace's Pact Broker, by handle: main branch, labels,
 * repository and when each was last changed. The **Label** filter narrows the list to the
 * pacticipants carrying one label; **Load more** reads the next page. Each name opens the
 * pacticipant's page (versions, branches, tags, environments). The Contracts tab row (PFX-8.1,
 * #7298) leads to the Matrix, Can I deploy, Environments, Webhooks, Health and Settings pages.
 *
 * A workspace with no pacticipant shows the CLI command that registers them: publishing a pact
 * registers its consumer and its provider.
 *
 * PFX-8.10 (#7307): **New pacticipant** (the header's primary action, `pacts:create`) registers one
 * first, and **Show → Deleted** lists the deleted pacticipants that can still be restored, each with
 * when it is purged and — for `pacts:delete` — **Restore**.
 */

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { Plus, RefreshCw, Undo2 } from 'lucide-react';
import { Button, EmptyState, LoadingState } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { ContractsTabs } from '../pactOverview/ContractsTabs';
import { CONTRACTS_ROUTE } from '@lib/pact-overview';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { PUBLISH_SNIPPET, formatWhen, pacticipantRoute, type Pacticipant } from '@lib/pact-pacticipants';
import { CREATE_PERMISSION, DELETE_PERMISSION } from '@lib/pact-pacticipant-settings';
import { useMyPermissions } from '@/app/components/ade/access/useMyPermissions';
import { CliSnippet, PacticipantsTable } from './PacticipantPanels';
import { fetchLabels, fetchPacticipants, restorePacticipant } from './pacticipantsApi';
import { NewPacticipantDialog } from './NewPacticipantDialog';
import { describeFailure } from './describeFailure';

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/** The loaded rows and where the next page starts. */
interface ListState {
  rows: Pacticipant[];
  nextCursor: string | null;
}

/** Which pacticipants the list shows. */
type Show = 'live' | 'deleted';

/**
 * The deleted pacticipants, with when each is purged and **Restore**.
 *
 * @param props - The rows, whether the viewer may restore, what Restore does, and the row restoring.
 * @returns The table.
 */
function DeletedTable({
  rows,
  canRestore,
  onRestore,
  restoring,
}: {
  rows: Pacticipant[];
  canRestore: boolean;
  onRestore: (row: Pacticipant) => void;
  restoring: string | null;
}) {
  return (
    <div className="ppx__table-wrap">
      <table className="ppx__table" data-testid="ppx-deleted-table">
        <caption className="sr-only">Deleted pacticipants</caption>
        <thead>
          <tr>
            <th scope="col">Name</th>
            <th scope="col">Deleted</th>
            <th scope="col">Purged after</th>
            {canRestore ? (
              <th scope="col">
                <span className="sr-only">Actions</span>
              </th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} data-testid={`ppx-deleted-${row.slug}`}>
              <th scope="row">
                <span className="ppx__name-cell">
                  <span className="ppx__name">{row.name}</span>
                  <span className="ppx__mono">{row.slug}</span>
                </span>
              </th>
              <td>
                <span className="ppx__when">{formatWhen(row.deleted_at)}</span>
                {row.deleted_by_label ? <span className="ppx__meta"> by {row.deleted_by_label}</span> : null}
                {row.delete_reason ? <span className="ppx__meta ppx-settings__block">{row.delete_reason}</span> : null}
              </td>
              <td className="ppx__when">{formatWhen(row.purge_after)}</td>
              {canRestore ? (
                <td>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => onRestore(row)}
                    disabled={restoring !== null}
                    aria-label={`Restore ${row.name}`}
                    data-testid={`ppx-restore-${row.slug}`}
                  >
                    <Undo2 aria-hidden />
                    {restoring === row.id ? 'Restoring…' : 'Restore'}
                  </Button>
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The Pacticipants page.
 *
 * @returns The page.
 */
export default function PacticipantsListClient() {
  const router = useRouter();
  const permissions = useMyPermissions();
  const canCreate = permissions.status === 'ready' && permissions.can(CREATE_PERMISSION);
  const canRestore = permissions.status === 'ready' && permissions.can(DELETE_PERMISSION);
  const [show, setShow] = React.useState<Show>('live');
  const [creating, setCreating] = React.useState(false);
  const [restoring, setRestoring] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<{ tone: 'ok' | 'danger'; text: string } | null>(null);
  const [label, setLabel] = React.useState<string>('');
  const [labels, setLabels] = React.useState<string[]>([]);
  const [list, setList] = React.useState<ListState | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [moreError, setMoreError] = React.useState<string | null>(null);

  const load = React.useCallback(async (filter: string, which: Show = 'live') => {
    setList(null);
    setError(null);
    setMoreError(null);
    try {
      const page = await fetchPacticipants({ label: filter || null, state: which === 'deleted' ? 'deleted' : null });
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
      const page = await fetchPacticipants({
        label: label || null,
        cursor: list.nextCursor,
        state: show === 'deleted' ? 'deleted' : null,
      });
      setList({
        rows: [...list.rows, ...page.pacticipants],
        nextCursor: page.has_more ? (page.next_cursor ?? null) : null,
      });
    } catch (caught) {
      setMoreError(describeFailure(caught, 'Could not load more pacticipants'));
    } finally {
      setLoadingMore(false);
    }
  }, [label, list, show]);

  React.useEffect(() => {
    void load(label, show);
  }, [label, load, show]);

  const restore = async (row: Pacticipant) => {
    setRestoring(row.id);
    setNotice(null);
    // The id chooses this one when several deleted pacticipants had the same handle.
    const answer = await restorePacticipant(row.id);
    setRestoring(null);
    if ('error' in answer) {
      setNotice({ tone: 'danger', text: `${row.name} could not be restored: ${answer.error}` });
      return;
    }
    setNotice({ tone: 'ok', text: `${answer.name} is restored, with the versions deleted with it.` });
    void load(label, show);
  };

  React.useEffect(() => {
    // The filter is a convenience: without labels the list still reads, so a failure only hides it.
    fetchLabels()
      .then(setLabels)
      .catch(() => setLabels([]));
  }, []);

  return (
    <Page>
      <PageHeader
        tabs={<ContractsTabs active="pacticipants" />}
        title="Pacticipants"
        breadcrumb={[{ label: 'Home', href: HOME_ROUTE }, { label: 'Contracts', href: CONTRACTS_ROUTE }, { label: 'Pacticipants' }]}
        description="The applications that take part in this workspace's pacts."
        actions={
          <>
            {canCreate ? (
              <Button onClick={() => setCreating(true)} data-testid="ppx-new-open">
                <Plus aria-hidden />
                New pacticipant
              </Button>
            ) : null}
            <Button variant="outline" onClick={() => void load(label, show)}>
              <RefreshCw aria-hidden />
              Refresh
            </Button>
          </>
        }
      />
      <PageBody>
        <div className="ppx" data-testid="pact-pacticipants">
          {notice ? (
            <p
              className={notice.tone === 'ok' ? 'ppx-settings__saved' : 'ppx__error'}
              role={notice.tone === 'ok' ? 'status' : 'alert'}
              data-testid="ppx-list-notice"
            >
              {notice.text}
            </p>
          ) : null}
          <div className="ppx__toolbar">
            <label className="ppx__field">
              <span className="ppx__field-label">Show</span>
              <select
                className="ppx__select"
                value={show}
                onChange={(event) => setShow(event.target.value as Show)}
                data-testid="ppx-show-filter"
              >
                <option value="live">Pacticipants</option>
                <option value="deleted">Deleted (can be restored)</option>
              </select>
            </label>
            {labels.length > 0 || label ? (
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
            ) : null}
          </div>
          {error ? (
            <EmptyState
              variant="compact"
              tone="danger"
              title="The pacticipants could not be read"
              description={error}
              action={
                <Button variant="soft" onClick={() => void load(label, show)}>
                  <RefreshCw aria-hidden />
                  Try again
                </Button>
              }
            />
          ) : list === null ? (
            <LoadingState message="Reading the pacticipants…" minHeightClassName="min-h-[6rem]" />
          ) : list.rows.length === 0 ? (
            show === 'deleted' ? (
              <EmptyState
                variant="compact"
                title="Nothing deleted to restore"
                description="A deleted pacticipant is listed here until it is purged."
              />
            ) : label ? (
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
                {list.nextCursor ? '+' : ''} {show === 'deleted' ? 'deleted ' : ''}
                {list.rows.length === 1 && !list.nextCursor ? 'pacticipant' : 'pacticipants'}
                {label ? ` with the label ${label}` : ''}
              </p>
              {show === 'deleted' ? (
                <DeletedTable
                  rows={list.rows}
                  canRestore={canRestore}
                  onRestore={(row) => void restore(row)}
                  restoring={restoring}
                />
              ) : (
                <PacticipantsTable pacticipants={list.rows} />
              )}
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
      {canCreate ? (
        <NewPacticipantDialog
          open={creating}
          onClose={() => setCreating(false)}
          onCreated={(created, ownerProblem) => {
            setCreating(false);
            if (ownerProblem) {
              // Stay, so the reason is read; the new pacticipant is in the list.
              setNotice({ tone: 'danger', text: ownerProblem });
              void load(label, show);
            } else {
              router.push(pacticipantRoute(created.slug));
            }
          }}
        />
      ) : null}
    </Page>
  );
}
