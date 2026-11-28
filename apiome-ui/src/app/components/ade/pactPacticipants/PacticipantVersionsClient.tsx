'use client';

/**
 * **A pacticipant's Versions** — `/ade/dashboard/pacts/pacticipants/{handle}/versions` (PFX-8.11,
 * #7308).
 *
 * Authority: `docs/mockups/contracts/pacticipant.html` (Versions). The versions as a managed list:
 *
 * - **Search** the loaded versions by number, branch or tag (the note says when more pages exist).
 * - **Views** (filter chips): **All**, the main branch, **Deployed** (what each environment runs
 *   now), **Unverified** (versions whose pacts have no verification result, from the matrix) and
 *   **Deleted** (restorable until purged).
 * - Inline **+ tag**, a row menu (**Pacts of this version**, **Can I deploy this?**, **Delete
 *   version**), **Restore** on a deleted row, and a sticky bulk bar (**Add a tag**, **Delete**,
 *   **Restore**, **Clear**) for the selected rows.
 *
 * A version that runs in an environment cannot be deleted ("Record its undeployment first"); the
 * tab never sends `force`. Every write says what it did in one line, naming each version it did
 * not change and why. A role without `pacts:create` sees no tagging; one without `pacts:delete`
 * no delete or restore. **The same, from anywhere** shows the commands for the selection.
 */

import * as React from 'react';
import Link from 'next/link';
import { RefreshCw, Search, Tag, Trash2, Undo2, X } from 'lucide-react';
import { Button, CommandBlock, EmptyState, Input, LoadingState } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { useMyPermissions } from '@/app/components/ade/access/useMyPermissions';
import { pactCommandSurfaces, unsupportedLines } from '@lib/pact-commands';
import { CONTRACTS_ROUTE } from '@lib/pact-overview';
import {
  PACTICIPANTS_ROUTE,
  pacticipantRoute,
  type Pacticipant,
  type PacticipantEnvironment,
  type PacticipantVersion,
} from '@lib/pact-pacticipants';
import {
  DELETE_VERSION_PERMISSION,
  MAX_VIEW_LOOKUPS,
  TAG_PERMISSION,
  UNVERIFIED_MATRIX_LIMIT,
  availableViews,
  bulkOutcome,
  deleteBlock,
  emptyVersionsStatement,
  inBatches,
  matchesSearch,
  restoreBlock,
  runningInByVersion,
  searchScopeNote,
  tagCommandAction,
  tagProblem,
  unreadEnvironments,
  unverifiedVersionNumbers,
  versionCommandAction,
  viewLabel,
  type BulkResult,
  type DeletedVersion,
  type RunningIn,
  type VersionView,
} from '@lib/pact-pacticipant-versions';
import { ContractsTabs } from '../pactOverview/ContractsTabs';
import { fetchMatrix } from '../pactMatrix/pactMatrixApi';
import { DeleteVersionsDialog } from './DeleteVersionsDialog';
import { PacticipantSubTabs } from './PacticipantSubTabs';
import { VersionsManageTable } from './VersionsManageTable';
import {
  deleteVersion,
  fetchDeletedVersions,
  fetchEnvironments,
  fetchPacticipant,
  fetchVersion,
  fetchVersions,
  restoreVersion,
  tagVersion,
} from './pacticipantsApi';
import { describeFailure } from './describeFailure';

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/** The loaded rows of a view, where the next page starts, and what the view could not cover. */
interface ViewRows {
  rows: (PacticipantVersion | DeletedVersion)[];
  nextCursor: string | null;
  /** Said under the toolbar: what the view left out, and why. */
  note: string | null;
}

/** What the last write did, said in one line. */
type Outcome = { tone: 'ok' | 'danger'; text: string } | null;

/** Props for {@link PacticipantVersionsClient}. */
export interface PacticipantVersionsClientProps {
  /** The pacticipant's handle, from the route. */
  slug: string;
}

/**
 * Read the versions a view names one by one (the Deployed and Unverified views).
 *
 * @param slug - The pacticipant's handle.
 * @param numbers - The version numbers.
 * @param what - What the view lists, for the note.
 * @returns The rows found, and a note naming what was left out.
 */
async function lookUp(slug: string, numbers: string[], what: string): Promise<ViewRows> {
  const wanted = numbers.slice(0, MAX_VIEW_LOOKUPS);
  const answers = await inBatches(wanted, (number) => fetchVersion(slug, number));
  const rows: PacticipantVersion[] = [];
  const unread: string[] = [];
  answers.forEach((answer, index) => {
    if ('error' in answer) unread.push(`${wanted[index]} (${answer.error})`);
    else rows.push({ ...answer, branches: answer.branches ?? [], tags: answer.tags ?? [] });
  });
  const notes: string[] = [];
  if (numbers.length > wanted.length) {
    notes.push(`Showing the first ${wanted.length} of ${numbers.length} ${what}.`);
  }
  if (unread.length) notes.push(`Could not read ${unread.join(', ')}.`);
  rows.sort((a, b) => b.seq - a.seq);
  return { rows, nextCursor: null, note: notes.length ? notes.join(' ') : null };
}

/**
 * The Versions page.
 *
 * @param props - See {@link PacticipantVersionsClientProps}.
 * @returns The page.
 */
export default function PacticipantVersionsClient({ slug }: PacticipantVersionsClientProps) {
  const permissions = useMyPermissions();
  const canTag = permissions.status === 'ready' && permissions.can(TAG_PERMISSION);
  const canDelete = permissions.status === 'ready' && permissions.can(DELETE_VERSION_PERMISSION);

  const [pacticipant, setPacticipant] = React.useState<Pacticipant | null>(null);
  const [readError, setReadError] = React.useState<string | null>(null);
  const [environments, setEnvironments] = React.useState<PacticipantEnvironment[] | { error: string } | null>(null);
  const [deletedCount, setDeletedCount] = React.useState<string | null>(null);
  const [view, setView] = React.useState<VersionView>('all');
  const [search, setSearch] = React.useState('');
  const [rows, setRows] = React.useState<{ data: ViewRows | null; error: string | null }>({ data: null, error: null });
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const [busy, setBusy] = React.useState<string | null>(null);
  const [bulkBusy, setBulkBusy] = React.useState(false);
  const [bulkTag, setBulkTag] = React.useState('');
  const [bulkTagError, setBulkTagError] = React.useState<string | null>(null);
  const [outcome, setOutcome] = React.useState<Outcome>(null);
  const [confirming, setConfirming] = React.useState<string[]>([]);

  const runningIn: Map<string, RunningIn[]> | null = Array.isArray(environments)
    ? runningInByVersion(environments)
    : null;

  const loadPacticipant = React.useCallback(async () => {
    setReadError(null);
    try {
      setPacticipant(await fetchPacticipant(slug));
    } catch (caught) {
      setReadError(describeFailure(caught, 'Could not load the pacticipant'));
    }
  }, [slug]);

  const loadEnvironments = React.useCallback(async () => {
    setEnvironments(null);
    try {
      setEnvironments((await fetchEnvironments(slug)).environments);
    } catch (caught) {
      setEnvironments({ error: describeFailure(caught, 'Could not read where the versions run') });
    }
  }, [slug]);

  const loadDeletedCount = React.useCallback(async () => {
    try {
      const page = await fetchDeletedVersions(slug);
      setDeletedCount(`${page.versions.length}${page.has_more ? '+' : ''}`);
    } catch {
      setDeletedCount(null);
    }
  }, [slug]);

  /** Read the first page of a view. */
  const loadView = React.useCallback(
    async (next: VersionView, mainBranch: string | null | undefined, envs: typeof environments) => {
      setRows({ data: null, error: null });
      setSelected(new Set());
      try {
        if (next === 'all' || next === 'main') {
          const page = await fetchVersions(slug, next === 'main' ? { branch: mainBranch ?? null } : {});
          setRows({
            data: { rows: page.versions, nextCursor: page.has_more ? (page.next_cursor ?? null) : null, note: null },
            error: null,
          });
        } else if (next === 'deleted') {
          const page = await fetchDeletedVersions(slug);
          setRows({
            data: { rows: page.versions, nextCursor: page.has_more ? (page.next_cursor ?? null) : null, note: null },
            error: null,
          });
        } else if (next === 'deployed') {
          if (envs === null) return; // Read again once the environments are in.
          if (!Array.isArray(envs)) throw new Error(envs.error);
          const found = await lookUp(slug, [...runningInByVersion(envs).keys()], 'deployed versions');
          const unread = unreadEnvironments(envs);
          const note = unread.length ? `Could not read what ${unread.join(', ')} run${unread.length === 1 ? 's' : ''}.` : null;
          setRows({ data: { ...found, note: [found.note, note].filter(Boolean).join(' ') || null }, error: null });
        } else {
          const answer = await fetchMatrix({
            selectors: [{ pacticipant: slug, scope: 'all', value: '', latest: false }],
            latestby: null,
            limit: UNVERIFIED_MATRIX_LIMIT,
          });
          const found = await lookUp(slug, unverifiedVersionNumbers(answer.rows, slug), 'unverified versions');
          const capped =
            answer.rows.length >= UNVERIFIED_MATRIX_LIMIT
              ? `Read from the first ${UNVERIFIED_MATRIX_LIMIT} matrix rows; older versions are not checked.`
              : null;
          setRows({ data: { ...found, note: [capped, found.note].filter(Boolean).join(' ') || null }, error: null });
        }
      } catch (caught) {
        setRows({ data: null, error: describeFailure(caught, 'Could not load the versions') });
      }
    },
    [slug],
  );

  React.useEffect(() => {
    void loadPacticipant();
    void loadEnvironments();
    void loadDeletedCount();
  }, [loadPacticipant, loadEnvironments, loadDeletedCount]);

  const mainBranch = pacticipant?.main_branch ?? null;
  // Only the Deployed view reads from the environments; the others are not read again when they arrive.
  const viewEnvironments = view === 'deployed' ? environments : undefined;
  React.useEffect(() => {
    if (!pacticipant) return;
    void loadView(view, mainBranch, viewEnvironments ?? null);
  }, [pacticipant, view, mainBranch, viewEnvironments, loadView]);

  const loadMore = async () => {
    const current = rows.data;
    if (!current?.nextCursor) return;
    setLoadingMore(true);
    try {
      const page =
        view === 'deleted'
          ? await fetchDeletedVersions(slug, current.nextCursor)
          : await fetchVersions(slug, {
              branch: view === 'main' ? mainBranch : null,
              cursor: current.nextCursor,
            });
      setRows({
        data: {
          rows: [...current.rows, ...page.versions],
          nextCursor: page.has_more ? (page.next_cursor ?? null) : null,
          note: current.note,
        },
        error: null,
      });
    } catch (caught) {
      setOutcome({ tone: 'danger', text: describeFailure(caught, 'Could not load more versions') });
    } finally {
      setLoadingMore(false);
    }
  };

  /** Put a returned version in place of its row. */
  const replaceRow = (version: PacticipantVersion) => {
    setRows((current) =>
      current.data
        ? {
            ...current,
            data: {
              ...current.data,
              rows: current.data.rows.map((row) =>
                row.number === version.number ? { ...row, tags: version.tags ?? row.tags } : row,
              ),
            },
          }
        : current,
    );
  };

  /** Take rows out of the view (deleted, or restored from Deleted). */
  const dropRows = (numbers: string[]) => {
    setRows((current) =>
      current.data
        ? { ...current, data: { ...current.data, rows: current.data.rows.filter((row) => !numbers.includes(row.number)) } }
        : current,
    );
    setSelected((current) => new Set([...current].filter((number) => !numbers.includes(number))));
  };

  const tagOne = async (number: string, tag: string): Promise<string | null> => {
    setBusy(number);
    setOutcome(null);
    const answer = await tagVersion(slug, number, tag);
    setBusy(null);
    if ('error' in answer) return answer.error;
    replaceRow(answer);
    setOutcome({ tone: 'ok', text: `Tagged ${number} with ${tag}.` });
    return null;
  };

  const tagSelected = async () => {
    const tag = bulkTag.trim();
    const problem = tagProblem(tag);
    if (problem) {
      setBulkTagError(problem);
      return;
    }
    const numbers = [...selected];
    setBulkBusy(true);
    setOutcome(null);
    const result: BulkResult = { done: [], failed: [], skipped: [] };
    const answers = await inBatches(numbers, (number) => tagVersion(slug, number, tag));
    answers.forEach((answer, index) => {
      if ('error' in answer) result.failed.push({ number: numbers[index], error: answer.error });
      else {
        result.done.push(numbers[index]);
        replaceRow(answer);
      }
    });
    setBulkBusy(false);
    setBulkTag('');
    setOutcome(bulkOutcome('tag', result, tag));
  };

  const deleteConfirmed = async (numbers: string[], reason: string) => {
    setBulkBusy(true);
    setOutcome(null);
    const asked = confirming;
    const result: BulkResult = {
      done: [],
      failed: [],
      skipped: asked
        .filter((number) => !numbers.includes(number))
        .map((number) => ({ number, reason: deleteBlock(number, runningIn?.get(number)) ?? 'not sent' })),
    };
    const answers = await inBatches(numbers, (number) => deleteVersion(slug, number, reason));
    answers.forEach((answer, index) => {
      if ('error' in answer) result.failed.push({ number: numbers[index], error: answer.error });
      else result.done.push(numbers[index]);
    });
    dropRows(result.done);
    setBulkBusy(false);
    setConfirming([]);
    setOutcome(bulkOutcome('delete', result));
    if (result.done.length) void loadDeletedCount();
  };

  const restore = async (numbers: string[]) => {
    setOutcome(null);
    setBulkBusy(numbers.length > 1);
    if (numbers.length === 1) setBusy(numbers[0]);
    const deletedRows = (rows.data?.rows ?? []) as DeletedVersion[];
    const result: BulkResult = { done: [], failed: [], skipped: [] };
    const sendable = numbers.filter((number) => {
      const row = deletedRows.find((entry) => entry.number === number);
      const why = row ? restoreBlock(row) : null;
      if (why) result.skipped.push({ number, reason: why });
      return !why;
    });
    const answers = await inBatches(sendable, (number) => restoreVersion(slug, number));
    answers.forEach((answer, index) => {
      if ('error' in answer) result.failed.push({ number: sendable[index], error: answer.error });
      else result.done.push(sendable[index]);
    });
    dropRows(result.done);
    setBusy(null);
    setBulkBusy(false);
    const head = result.done.length
      ? `Restored ${result.done.join(', ')} with ${result.done.length === 1 ? 'its' : 'their'} pacts, results and deployments.`
      : 'No version was restored.';
    const problems = [...result.skipped.map((s) => `${s.number}: ${s.reason}`), ...result.failed.map((f) => `${f.number}: ${f.error}`)];
    setOutcome(problems.length ? { tone: 'danger', text: `${head} Not changed — ${problems.join(' ')}` } : { tone: 'ok', text: head });
    if (result.done.length) void loadDeletedCount();
  };

  const select = (number: string | null, on: boolean) => {
    setSelected((current) => {
      const next = new Set(current);
      const targets = number === null ? shown.map((row) => row.number) : [number];
      for (const target of targets) {
        if (on) next.add(target);
        else next.delete(target);
      }
      return next;
    });
  };

  const name = pacticipant?.name ?? slug;
  const deleted = view === 'deleted';
  const shown = (rows.data?.rows ?? []).filter((row) => matchesSearch(row, search));
  const scopeNote = rows.data ? searchScopeNote(search, rows.data.rows.length, Boolean(rows.data.nextCursor)) : null;
  const first = [...selected][0] ?? shown[0]?.number ?? null;
  const who = { slug, name };
  const action = first
    ? deleted
      ? versionCommandAction('restore', who, first)
      : tagCommandAction(who, first, bulkTag)
    : null;

  return (
    <Page>
      <PageHeader
        tabs={<ContractsTabs active="pacticipants" />}
        title={name}
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Contracts', href: CONTRACTS_ROUTE },
          { label: 'Pacticipants', href: PACTICIPANTS_ROUTE },
          { label: name, href: pacticipantRoute(slug) },
          { label: 'Versions' },
        ]}
        description="Tag, delete and restore this pacticipant’s versions."
        actions={
          <Button
            variant="outline"
            onClick={() => {
              void loadEnvironments(); // The Deployed view reads again when they are in.
              void loadDeletedCount();
              if (pacticipant && view !== 'deployed') void loadView(view, mainBranch, null);
            }}
          >
            <RefreshCw aria-hidden />
            Refresh
          </Button>
        }
      />
      <PageBody>
        <div className="ppx" data-testid="pact-pacticipant-versions">
          <PacticipantSubTabs slug={slug} active="versions" />
          {readError ? (
            <EmptyState
              variant="compact"
              tone="danger"
              title="This pacticipant could not be read"
              description={readError}
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
          ) : !pacticipant ? (
            <LoadingState message="Reading the pacticipant…" minHeightClassName="min-h-[6rem]" />
          ) : (
            <section className="ppx__panel ppx-versions" aria-label="Versions" data-testid="ppx-versions-manage">
              <div className="ppx-versions__toolbar">
                <div className="ppx-versions__search">
                  <Search aria-hidden className="ppx-versions__search-icon" />
                  <Input
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Search versions, branches, tags…"
                    aria-label="Search versions"
                    className="ppx-versions__search-input"
                    data-testid="ppx-versions-search"
                  />
                </div>
                <div className="ppx-versions__chips" role="group" aria-label="Show">
                  {availableViews(mainBranch).map((id) => (
                    <button
                      key={id}
                      type="button"
                      className={id === view ? 'ppx-versions__chip is-active' : 'ppx-versions__chip'}
                      aria-pressed={id === view}
                      onClick={() => {
                        setView(id);
                        setOutcome(null);
                      }}
                      data-testid={`ppx-versions-view-${id}`}
                    >
                      {viewLabel(id, mainBranch)}
                      {id === 'deleted' && deletedCount && deletedCount !== '0' ? (
                        <span className="ppx-versions__count">{deletedCount}</span>
                      ) : null}
                    </button>
                  ))}
                </div>
                <span className="ppx-versions__hint">Deleted versions can be restored until they are purged.</span>
              </div>

              {Array.isArray(environments) || environments === null ? null : (
                <p className="ppx__meta" role="status" data-testid="ppx-versions-env-error">
                  {environments.error}. The Running in column is empty, and a deployed version is still refused by
                  Apiome when you delete it.
                </p>
              )}
              {rows.data?.note ? (
                <p className="ppx__meta" role="status" data-testid="ppx-versions-note">
                  {rows.data.note}
                </p>
              ) : null}
              {scopeNote ? (
                <p className="ppx__meta" role="status" data-testid="ppx-versions-search-note">
                  {scopeNote}
                </p>
              ) : null}
              {outcome ? (
                <p
                  className={outcome.tone === 'ok' ? 'ppx-settings__saved' : 'ppx__error'}
                  role={outcome.tone === 'ok' ? 'status' : 'alert'}
                  data-testid="ppx-versions-outcome"
                >
                  {outcome.text}
                </p>
              ) : null}

              {rows.error ? (
                <EmptyState
                  variant="compact"
                  tone="danger"
                  title="The versions could not be read"
                  description={rows.error}
                  action={
                    <Button variant="soft" onClick={() => void loadView(view, mainBranch, environments)}>
                      <RefreshCw aria-hidden />
                      Try again
                    </Button>
                  }
                />
              ) : rows.data === null ? (
                <LoadingState message="Reading the versions…" minHeightClassName="min-h-[4rem]" />
              ) : shown.length === 0 ? (
                <p className="ppx__statement" data-testid="ppx-versions-empty">
                  {emptyVersionsStatement(name, view, Boolean(search.trim()))}
                </p>
              ) : (
                <VersionsManageTable
                  slug={slug}
                  versions={shown}
                  deleted={deleted}
                  runningIn={runningIn}
                  selected={selected}
                  onSelect={select}
                  canTag={canTag}
                  canDelete={canDelete}
                  onTag={tagOne}
                  onDelete={(number) => setConfirming([number])}
                  onRestore={(number) => void restore([number])}
                  busy={busy}
                />
              )}
              {rows.data ? (
                <div className="ppx-versions__foot">
                  <span className="ppx__meta" data-testid="ppx-versions-count">
                    {shown.length} of {rows.data.rows.length}
                    {rows.data.nextCursor ? '+' : ''} versions
                  </span>
                  {rows.data.nextCursor ? (
                    <Button variant="outline" size="sm" onClick={() => void loadMore()} disabled={loadingMore}>
                      {loadingMore ? 'Loading…' : 'Load more'}
                    </Button>
                  ) : null}
                </div>
              ) : null}

              {selected.size > 0 ? (
                <div className="ppx-versions__bulk" role="region" aria-label="Selection" data-testid="ppx-versions-bulk">
                  <span className="ppx-versions__bulk-count">{selected.size} selected</span>
                  {deleted ? (
                    canDelete ? (
                      <Button size="sm" variant="outline" disabled={bulkBusy} onClick={() => void restore([...selected])}>
                        <Undo2 aria-hidden />
                        Restore
                      </Button>
                    ) : null
                  ) : (
                    <>
                      {canTag ? (
                        <form
                          className="ppx-versions__bulk-tag"
                          noValidate
                          onSubmit={(event) => {
                            event.preventDefault();
                            void tagSelected();
                          }}
                        >
                          <label htmlFor="ppx-bulk-tag" className="sr-only">
                            Tag for the selected versions
                          </label>
                          <Input
                            id="ppx-bulk-tag"
                            className="ppx-versions__tag-input"
                            placeholder="Tag"
                            value={bulkTag}
                            aria-invalid={bulkTagError ? true : undefined}
                            onChange={(event) => {
                              setBulkTag(event.target.value);
                              setBulkTagError(null);
                            }}
                            data-testid="ppx-bulk-tag-input"
                          />
                          <Button type="submit" size="sm" variant="outline" disabled={bulkBusy}>
                            <Tag aria-hidden />
                            Add a tag
                          </Button>
                          {bulkTagError ? (
                            <span className="ppx__error" role="alert">
                              {bulkTagError}
                            </span>
                          ) : null}
                        </form>
                      ) : null}
                      {canDelete ? (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={bulkBusy}
                          onClick={() => setConfirming([...selected])}
                          data-testid="ppx-bulk-delete"
                        >
                          <Trash2 aria-hidden />
                          Delete
                        </Button>
                      ) : null}
                    </>
                  )}
                  <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
                    <X aria-hidden />
                    Clear
                  </Button>
                </div>
              ) : null}

              {action && (deleted ? canDelete : canTag) ? (
                <CommandBlock
                  headingLevel={2}
                  surfaces={pactCommandSurfaces(action)}
                  unsupported={unsupportedLines(action)}
                  footnote={
                    selected.size > 1
                      ? 'Shown for the first selected version; one command per version. Replace {tenant} with your workspace’s handle in the REST path.'
                      : 'Replace {tenant} with your workspace’s handle in the REST path.'
                  }
                  data-testid="ppx-versions-command"
                />
              ) : null}
            </section>
          )}
        </div>
      </PageBody>
      {pacticipant ? (
        <DeleteVersionsDialog
          pacticipant={who}
          numbers={confirming}
          runningIn={runningIn}
          deleting={bulkBusy}
          onConfirm={(numbers, reason) => void deleteConfirmed(numbers, reason)}
          onCancel={() => setConfirming([])}
        />
      ) : null}
    </Page>
  );
}
