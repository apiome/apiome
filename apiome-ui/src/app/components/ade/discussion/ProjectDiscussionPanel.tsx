'use client';

/**
 * The Discussion tab of the Versions dashboard — COL-1.3 (#4515).
 *
 * Every comment thread of the project, whatever version or element it hangs on, newest activity
 * first. Three facets narrow the list — **status** (open / resolved / orphaned / all), **mentions
 * me**, and **element type** — and each is forwarded to apiome-rest rather than applied to a page
 * already in hand, so a filter never hides a thread that simply was not loaded yet.
 *
 * Each row names its element and links into the Studio with the COL-1.2 deep link, which selects
 * the element, puts it on the canvas and opens its thread popover. An orphaned thread's element is
 * gone, so its link opens the version instead, where the Studio lists orphaned threads for
 * relinking.
 *
 * The numbers — the chips' totals, each row's "N unresolved on this element", and the tab count
 * pushed up through `onUnresolvedTotalChange` — come from the summary route, which counts with the
 * Studio badges' own rule (`unresolvedCommentCounts` in `@lib/comment-discussion`).
 */

import * as React from 'react';
import { ArrowUpRight, AtSign, MessagesSquare } from 'lucide-react';
import { Alert } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { DataTableFilterChip, DataTableToolbar } from '@/app/components/ui/DataTable';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { formatRelativeWhen } from '@/app/components/ade/repositories/repositoryDetailModel';
import { formatVersionWithPrefix } from '@/app/utils/version-display';
import { cn } from '@lib/utils';
import {
  ANCHOR_TYPE_LABELS,
  DEFAULT_DISCUSSION_FILTERS,
  DISCUSSION_ELEMENT_FILTERS,
  DISCUSSION_ELEMENT_LABELS,
  DISCUSSION_PAGE_SIZE,
  DISCUSSION_STATUS_FILTERS,
  DISCUSSION_STATUS_LABELS,
  UNRESOLVED_COUNT_THREAD_CAP,
  commentAnchorKey,
  commentExcerpt,
  discussionListParams,
  discussionSummaryParams,
  discussionThreadHref,
  replyCountText,
  statusFilterCount,
  threadElementLabel,
  unresolvedOnElementText,
  type CommentThreadStatus,
  type DiscussionFilters,
  type DiscussionSummary,
  type DiscussionThread,
} from '@lib/comment-discussion';

/** The part of a version row the panel reads: its id and its label. */
export interface ProjectDiscussionVersion {
  /** The revision id threads carry as `version_id`. */
  id: string;
  /** The version label, e.g. `2.3.1`. */
  version_id: string;
}

export interface ProjectDiscussionPanelProps {
  /** The project whose threads are listed. */
  projectId: string;
  /** The project's versions, to print each thread's version label. */
  versions: readonly ProjectDiscussionVersion[];
  /** The Studio workspace route links are built on; null draws the rows without links. */
  workspaceRoute: string | null;
  /** Called with the project's unresolved total whenever the summary loads. */
  onUnresolvedTotalChange?: (total: number) => void;
  /**
   * Narrow the list and every count to one version's threads, by revision id — the review page's
   * Discussion tab (COL-2.2, #4518). Every version of the project when omitted.
   */
  versionId?: string;
  /** Reference time for relative dates, in epoch ms; tests pin it. Defaults to mount time. */
  now?: number;
}

/** The badge tone for each status. */
const STATUS_BADGE_VARIANT: Record<CommentThreadStatus, 'default' | 'success' | 'warning'> = {
  open: 'default',
  resolved: 'success',
  orphaned: 'warning',
};

/** A loaded page of threads, remembered with the query that produced it. */
interface LoadedPage {
  /** The list query string it answers. */
  key: string;
  /** The threads loaded so far. */
  threads: DiscussionThread[];
  /** How many threads match in all. */
  total: number;
}

/** What the BFF routes answer with. */
type Envelope<T> = Partial<T> & { success?: boolean; error?: string };

/**
 * GET a BFF route and parse its JSON envelope.
 *
 * @param url - The route.
 * @returns The parsed envelope.
 */
async function getEnvelope<T>(url: string): Promise<Envelope<T>> {
  const response = await fetch(url);
  return (await response.json()) as Envelope<T>;
}

/**
 * The empty state's sentence for the current filters.
 *
 * @param filters - The panel's filters.
 * @returns What to say when nothing matches.
 */
function emptyDescription(filters: Readonly<DiscussionFilters>): string {
  if (filters.mentionsMe) return 'No thread matching these filters mentions you.';
  if (filters.status === 'open' && filters.elementType === 'all') {
    return 'Nothing to resolve. Start a thread on an element in Studio.';
  }
  return 'No threads match these filters.';
}

/**
 * One thread row.
 *
 * @param props.thread - The thread.
 * @param props.versionLabel - Its version, as printed.
 * @param props.href - Its Studio deep link, or null.
 * @param props.unresolvedOnElement - Open threads on its element (the canvas badge number).
 * @param props.now - Reference time for the relative date.
 */
function DiscussionThreadRow({
  thread,
  versionLabel,
  href,
  unresolvedOnElement,
  now,
}: {
  thread: DiscussionThread;
  versionLabel: string;
  href: string | null;
  unresolvedOnElement: number;
  now: number;
}) {
  const label = threadElementLabel(thread);
  const author = thread.root_comment?.author_name || thread.created_by_name || 'Someone';
  const excerpt = commentExcerpt(thread.root_comment?.body);
  const unresolvedText = unresolvedOnElementText(unresolvedOnElement);
  const element = (
    <span
      className={cn(
        'disc-thread__element',
        (thread.anchor_type === 'path' || thread.anchor_type === 'operation') && 'mono'
      )}
    >
      {label}
    </span>
  );

  return (
    <li className="disc-thread" data-testid={`discussion-thread-${thread.id}`} data-status={thread.status}>
      <div className="disc-thread__head">
        {href ? (
          <a className="disc-thread__link" href={href} data-testid="discussion-thread-link">
            {element}
            <ArrowUpRight className="disc-thread__glyph" aria-hidden />
            <span className="sr-only">
              {thread.status === 'orphaned' ? ', open its version in Studio' : ', open in Studio'}
            </span>
          </a>
        ) : (
          element
        )}
        <Badge variant="secondary" square>
          {ANCHOR_TYPE_LABELS[thread.anchor_type]}
        </Badge>
        <Badge variant={STATUS_BADGE_VARIANT[thread.status]}>{DISCUSSION_STATUS_LABELS[thread.status]}</Badge>
        <span className="disc-thread__version">{versionLabel}</span>
      </div>
      {excerpt ? <p className="disc-thread__excerpt">{excerpt}</p> : null}
      <p className="disc-thread__meta">
        <span>{author}</span>
        <span aria-hidden>·</span>
        <time dateTime={thread.last_activity_at} title={thread.last_activity_at}>
          Active {formatRelativeWhen(thread.last_activity_at, now)}
        </time>
        <span aria-hidden>·</span>
        <span>{replyCountText(thread.comment_count)}</span>
        {unresolvedText ? (
          <>
            <span aria-hidden>·</span>
            <span className="disc-thread__unresolved" data-testid="discussion-thread-unresolved">
              {unresolvedText}
            </span>
          </>
        ) : null}
      </p>
    </li>
  );
}

/**
 * The project Discussion panel.
 *
 * @param props - See {@link ProjectDiscussionPanelProps}.
 */
export function ProjectDiscussionPanel({
  projectId,
  versions,
  workspaceRoute,
  onUnresolvedTotalChange,
  versionId,
  now,
}: ProjectDiscussionPanelProps) {
  const [filters, setFilters] = React.useState<DiscussionFilters>(DEFAULT_DISCUSSION_FILTERS);
  const [page, setPage] = React.useState<LoadedPage | null>(null);
  const [listError, setListError] = React.useState<{ key: string; message: string } | null>(null);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [moreError, setMoreError] = React.useState<string | null>(null);
  const [summary, setSummary] = React.useState<{ key: string; data: DiscussionSummary } | null>(null);
  const [mountedAt] = React.useState(() => Date.now());

  const routeBase = `/api/projects/${encodeURIComponent(projectId)}/comment-threads`;
  const listKey = discussionListParams(filters, { limit: DISCUSSION_PAGE_SIZE, offset: 0 }, versionId);
  const summaryKey = discussionSummaryParams(filters, versionId);

  // The latest callback, without re-reading the summary each time the parent re-renders.
  const onTotalRef = React.useRef(onUnresolvedTotalChange);
  React.useEffect(() => {
    onTotalRef.current = onUnresolvedTotalChange;
  }, [onUnresolvedTotalChange]);

  // The first page for the current filters.
  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const json = await getEnvelope<DiscussionThreadPageShape>(`${routeBase}${listKey}`);
        if (cancelled) return;
        if (!json.success || !Array.isArray(json.threads)) {
          setListError({ key: listKey, message: json.error || 'Failed to load comment threads' });
          return;
        }
        setListError(null);
        setPage({
          key: listKey,
          threads: json.threads,
          total: typeof json.total === 'number' ? json.total : json.threads.length,
        });
      } catch (error) {
        if (!cancelled) {
          setListError({
            key: listKey,
            message: error instanceof Error ? error.message : 'Failed to load comment threads',
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [routeBase, listKey]);

  // The counts for the current mentions / element-type filters.
  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const json = await getEnvelope<DiscussionSummary>(`${routeBase}/summary${summaryKey}`);
        if (cancelled || !json.success || !json.statusTotals) return;
        const data: DiscussionSummary = {
          statusTotals: json.statusTotals,
          unresolvedTotal: json.unresolvedTotal ?? 0,
          unresolvedByAnchor: json.unresolvedByAnchor ?? {},
          truncated: Boolean(json.truncated),
        };
        setSummary({ key: summaryKey, data });
        onTotalRef.current?.(data.unresolvedTotal);
      } catch {
        // Counts are secondary: without them the chips draw no numbers and the list still works.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [routeBase, summaryKey]);

  const versionLabels = React.useMemo(
    () => new Map(versions.map((version) => [version.id, formatVersionWithPrefix(version.version_id)])),
    [versions]
  );

  const current = page?.key === listKey ? page : null;
  const currentError = !current && listError?.key === listKey ? listError.message : null;
  const statusTotals = summary?.key === summaryKey ? summary.data.statusTotals : null;
  const unresolvedByAnchor = summary?.data.unresolvedByAnchor ?? {};
  const referenceTime = now ?? mountedAt;

  /**
   * Change some filters and forget the last "load more" failure.
   *
   * @param patch - The filters to change.
   */
  const updateFilters = (patch: Partial<DiscussionFilters>) => {
    setFilters((previous) => ({ ...previous, ...patch }));
    setMoreError(null);
  };

  /** Append the next page to the list, if the filters have not changed meanwhile. */
  const loadMore = async () => {
    if (!current) return;
    const key = listKey;
    setLoadingMore(true);
    setMoreError(null);
    try {
      const json = await getEnvelope<DiscussionThreadPageShape>(
        `${routeBase}${discussionListParams(
          filters,
          { limit: DISCUSSION_PAGE_SIZE, offset: current.threads.length },
          versionId
        )}`
      );
      if (!json.success || !Array.isArray(json.threads)) {
        setMoreError(json.error || 'Failed to load more comment threads');
        return;
      }
      const next = json.threads;
      setPage((previous) => {
        if (!previous || previous.key !== key) return previous;
        const seen = new Set(previous.threads.map((thread) => thread.id));
        return {
          key,
          threads: [...previous.threads, ...next.filter((thread) => !seen.has(thread.id))],
          total: typeof json.total === 'number' ? json.total : previous.total,
        };
      });
    } catch (error) {
      setMoreError(error instanceof Error ? error.message : 'Failed to load more comment threads');
    } finally {
      setLoadingMore(false);
    }
  };

  let body: React.ReactNode;
  if (current && current.threads.length === 0) {
    body = (
      <EmptyState
        icon={<MessagesSquare />}
        title="No threads"
        description={emptyDescription(filters)}
        data-testid="discussion-empty"
      />
    );
  } else if (current) {
    body = (
      <>
        <ul className="disc-list" aria-label="Comment threads" data-testid="discussion-thread-list">
          {current.threads.map((thread) => (
            <DiscussionThreadRow
              key={thread.id}
              thread={thread}
              versionLabel={versionLabels.get(thread.version_id) ?? `Revision ${thread.version_id.slice(0, 8)}`}
              href={discussionThreadHref(workspaceRoute, thread)}
              unresolvedOnElement={unresolvedByAnchor[commentAnchorKey(thread.anchor_type, thread.anchor_id)] ?? 0}
              now={referenceTime}
            />
          ))}
        </ul>
        {current.threads.length < current.total || moreError ? (
          <div className="disc-more">
            {moreError ? (
              <Alert variant="error" className="disc-more__error" data-testid="discussion-more-error">
                {moreError}
              </Alert>
            ) : null}
            <span className="disc-more__count" data-testid="discussion-shown">
              Showing {current.threads.length} of {current.total}
            </span>
            {current.threads.length < current.total ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => void loadMore()}
                disabled={loadingMore}
                data-testid="discussion-load-more"
              >
                {loadingMore ? 'Loading…' : 'Load more'}
              </Button>
            ) : null}
          </div>
        ) : null}
      </>
    );
  } else if (currentError) {
    body = (
      <div className="disc-state">
        <Alert variant="error" data-testid="discussion-error">
          {currentError}
        </Alert>
      </div>
    );
  } else {
    body = <LoadingState message="Loading comment threads…" minHeightClassName="disc-min-h" />;
  }

  return (
    <section className="vdlg-panel disc" aria-label="Project discussion" data-testid="project-discussion-panel">
      <DataTableToolbar>
        <div role="group" aria-label="Thread status" className="disc-facets">
          {DISCUSSION_STATUS_FILTERS.map((status) => (
            <DataTableFilterChip
              key={status}
              active={filters.status === status}
              count={statusTotals ? statusFilterCount(statusTotals, status) : undefined}
              onClick={() => updateFilters({ status })}
              data-testid={`discussion-status-${status}`}
            >
              {DISCUSSION_STATUS_LABELS[status]}
            </DataTableFilterChip>
          ))}
        </div>
        <DataTableFilterChip
          active={filters.mentionsMe}
          onClick={() => updateFilters({ mentionsMe: !filters.mentionsMe })}
          data-testid="discussion-mentions-me"
        >
          <AtSign className="disc-chip-glyph" aria-hidden />
          Mentions me
        </DataTableFilterChip>
        <div role="group" aria-label="Element type" className="disc-facets">
          {DISCUSSION_ELEMENT_FILTERS.map((elementType) => (
            <DataTableFilterChip
              key={elementType}
              active={filters.elementType === elementType}
              onClick={() => updateFilters({ elementType })}
              data-testid={`discussion-element-${elementType}`}
            >
              {DISCUSSION_ELEMENT_LABELS[elementType]}
            </DataTableFilterChip>
          ))}
        </div>
      </DataTableToolbar>
      {summary?.data.truncated ? (
        <p className="disc-note" data-testid="discussion-truncated">
          Per-element counts cover the first {UNRESOLVED_COUNT_THREAD_CAP.toLocaleString('en-US')} unresolved
          threads.
        </p>
      ) : null}
      {body}
    </section>
  );
}

/** The list route's payload, as the panel reads it. */
interface DiscussionThreadPageShape {
  threads: DiscussionThread[];
  total: number;
}
