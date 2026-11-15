'use client';

/**
 * The merge request page — COL-4.3 (#4527).
 *
 * One page for a proposal to merge a draft branch into a version line, composed of the pieces that
 * already exist:
 *
 * - **Header** — breadcrumb to the project, the title, the state, `source → target`, who opened it.
 * - **Changes** — the CTG-1.x classified diff from the merge base to the branch tip, in the review
 *   page's own Changes panel (`ReviewChangesPanel` pointed at this page's routes).
 * - **Conflicts** — the merge session's conflicts in the existing conflict list
 *   (`MergeRequestConflictsPanel`).
 * - **Review** — the COL-2.1 review of the branch tip, linking to the review page where reviewers
 *   decide (`MergeRequestReviewPanel`).
 * - **Status** (aside) — readiness, blockers, and Merge / Check for conflicts / Request review /
 *   Close (`MergeRequestActionsCard`).
 *
 * The tab strip is the review page's: hand-built on the shared tab classes, each pane mounted the
 * first time it is shown and kept mounted after. A merge that finds conflicts reloads the merge
 * request and opens the Conflicts tab.
 */

import * as React from 'react';
import { toast } from '../../ui/toast';
import { GitBranch, GitCompareArrows, GitMerge, MessageSquareCheck, type LucideIcon } from 'lucide-react';

import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { Badge } from '@/app/components/ui/Badge';
import { ErrorState } from '@/app/components/ui/ErrorState';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { TAB_COUNT_CLASS, TAB_LIST_CLASS, tabTriggerClass } from '@/app/components/ui/tabStyles';
import { formatVersionWithPrefix } from '@/app/utils/version-display';
import {
  MERGE_REQUEST_STATE_BADGE,
  MERGE_REQUEST_TABS,
  MERGE_REQUEST_TAB_LABELS,
  mergeRequestErrorMessage,
  type MergeRequestDetail,
  type MergeRequestPagePayload,
  type MergeRequestTabId,
} from '@lib/merge-requests';

import { ReviewChangesPanel } from '../reviews/ReviewChangesPanel';
import { MergeRequestActionsCard, type MergeOverride, type MergeRequestAction } from './MergeRequestActionsCard';
import { MergeRequestConflictsPanel } from './MergeRequestConflictsPanel';
import { MergeRequestReviewPanel } from './MergeRequestReviewPanel';
import { callMergeRequestApi } from './mergeRequestFetch';

/** Each tab's glyph. */
const TAB_GLYPH: Readonly<Record<MergeRequestTabId, LucideIcon>> = {
  changes: GitCompareArrows,
  conflicts: GitMerge,
  review: MessageSquareCheck,
};

/** The breadcrumb's first step. */
const PROJECTS_CRUMB = { label: 'Projects', href: '/ade/dashboard/projects' } as const;

/** What each action's success toast says. */
const SUCCESS_TOAST: Readonly<Record<MergeRequestAction, (detail: MergeRequestDetail) => string>> = {
  check: (detail) =>
    detail.conflicts.length
      ? `${detail.conflicts.length} conflicting path(s) found.`
      : 'No conflicts with the version line.',
  merge: (detail) => `Merged into ${detail.merge_request.target_branch_name}.`,
  close: () => 'Merge request closed.',
  review: () => 'Review requested for the current tip.',
};

/** Refusals after which the merge request is read again, because it moved on. */
const RELOAD_ON_CODES: ReadonlySet<string> = new Set(['mr-conflicts', 'mr-not-ready', 'mr-not-open', 'STALE_HEAD']);

/** What the page is showing. */
type LoadState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; payload: MergeRequestPagePayload };

/** A tab's element id. */
function tabId(id: MergeRequestTabId): string {
  return `mr-tab-${id}`;
}

/** A pane's element id. */
function panelId(id: MergeRequestTabId): string {
  return `mr-pane-${id}`;
}

export interface MergeRequestPageClientProps {
  /** The merge request id from the URL. */
  mergeRequestId: string;
  /** The tab `?tab=` asked for. */
  initialTab?: MergeRequestTabId;
}

/**
 * The merge request page.
 *
 * @param props - See {@link MergeRequestPageClientProps}.
 * @returns The page.
 */
export default function MergeRequestPageClient({ mergeRequestId, initialTab = 'changes' }: MergeRequestPageClientProps) {
  const [load, setLoad] = React.useState<LoadState>({ status: 'loading' });
  const [reloadToken, setReloadToken] = React.useState(0);
  const [activeTab, setActiveTab] = React.useState<MergeRequestTabId>(initialTab);
  const [visited, setVisited] = React.useState<ReadonlySet<MergeRequestTabId>>(() => new Set([initialTab]));
  const [busy, setBusy] = React.useState<MergeRequestAction | null>(null);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const tabRefs = React.useRef<Array<HTMLButtonElement | null>>([]);
  const routeBase = `/api/merge-requests/${encodeURIComponent(mergeRequestId)}`;

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      const json = await callMergeRequestApi<MergeRequestPagePayload>(routeBase);
      if (cancelled) return;
      if (!json.success || !json.mergeRequest || !json.project) {
        setLoad({
          status: 'error',
          message: mergeRequestErrorMessage(json.code, json.error || 'Could not load this merge request.'),
        });
        return;
      }
      setLoad({
        status: 'ready',
        payload: { mergeRequest: json.mergeRequest, project: json.project, viewerId: json.viewerId ?? null },
      });
    })();
    return () => {
      cancelled = true;
    };
  }, [routeBase, reloadToken]);

  /**
   * Show a tab, mounting its pane the first time, and keep `?tab=` in the address.
   *
   * @param id - The tab.
   */
  const selectTab = React.useCallback((id: MergeRequestTabId) => {
    setActiveTab(id);
    setVisited((previous) => (previous.has(id) ? previous : new Set([...previous, id])));
    try {
      const url = new URL(window.location.href);
      url.searchParams.set('tab', id);
      window.history.replaceState(window.history.state, '', url.toString());
    } catch {
      // The address is a convenience; the tab switch has already happened.
    }
  }, []);

  /**
   * Move focus to a tab and show it — the roving tabindex's arrow keys.
   *
   * @param index - The tab's index; wraps around both ends.
   */
  const focusTab = (index: number) => {
    const next = (index + MERGE_REQUEST_TABS.length) % MERGE_REQUEST_TABS.length;
    tabRefs.current[next]?.focus();
    selectTab(MERGE_REQUEST_TABS[next]);
  };

  /**
   * Run one of the Status card's actions and show its outcome.
   *
   * @param action - The action.
   * @param override - The immutability override, for Merge.
   */
  const runAction = async (action: MergeRequestAction, override?: MergeOverride) => {
    setBusy(action);
    setActionError(null);
    const json = await callMergeRequestApi<{ mergeRequest: MergeRequestDetail }>(
      `${routeBase}/${action}`,
      override ?? {}
    );
    setBusy(null);
    if (!json.success || !json.mergeRequest) {
      setActionError(mergeRequestErrorMessage(json.code, json.error || 'That did not work.'));
      if (json.code === 'mr-conflicts') selectTab('conflicts');
      if (json.code && RELOAD_ON_CODES.has(json.code)) setReloadToken((token) => token + 1);
      return;
    }
    const mergeRequest = json.mergeRequest;
    setLoad((previous) =>
      previous.status === 'ready' ? { status: 'ready', payload: { ...previous.payload, mergeRequest } } : previous
    );
    if (action === 'check' && mergeRequest.conflicts.length) selectTab('conflicts');
    toast.success(SUCCESS_TOAST[action](mergeRequest));
  };

  if (load.status === 'loading') {
    return (
      <Page>
        <PageBody>
          <LoadingState message="Loading merge request…" data-testid="mr-loading" />
        </PageBody>
      </Page>
    );
  }

  if (load.status === 'error') {
    return (
      <Page>
        <PageHeader title="Merge request" breadcrumb={[PROJECTS_CRUMB]} />
        <PageBody>
          <ErrorState
            description={load.message}
            onRetry={() => {
              setLoad({ status: 'loading' });
              setReloadToken((token) => token + 1);
            }}
            data-testid="mr-error"
          />
        </PageBody>
      </Page>
    );
  }

  const { mergeRequest: detail, project, viewerId } = load.payload;
  const record = detail.merge_request;
  const badge = MERGE_REQUEST_STATE_BADGE[record.state];
  const tipName = formatVersionWithPrefix(detail.source_tip_version_label);

  const panes: Record<MergeRequestTabId, React.ReactNode> = {
    // Keyed by the tips so a merge or a moved branch recomputes the diff.
    changes: (
      <ReviewChangesPanel
        key={`${detail.merge_base_revision_id}:${detail.source_tip_revision_id}`}
        routeBase={routeBase}
        baselineRole="the merge base"
      />
    ),
    conflicts: <MergeRequestConflictsPanel key={detail.merge_session?.id ?? 'none'} detail={detail} />,
    review: <MergeRequestReviewPanel detail={detail} viewerId={viewerId} />,
  };

  return (
    <Page>
      <PageHeader
        breadcrumb={[
          PROJECTS_CRUMB,
          {
            label: project.name || project.slug,
            href: `/ade/dashboard/versions?projectId=${encodeURIComponent(project.id)}`,
          },
          { label: 'Merge request' },
        ]}
        title={record.title}
        badge={
          <Badge variant={badge.variant} data-testid="mr-state">
            {badge.label}
          </Badge>
        }
        description={
          <span className="mrq-head" data-testid="mr-branches">
            <GitBranch aria-hidden className="mrq-head__glyph" />
            <span className="mono">{record.source_branch_name}</span>
            {tipName ? <span className="mrq-head__tip">({tipName})</span> : null}
            <span aria-hidden>→</span>
            <span className="mono">{record.target_branch_name}</span>
            <span className="mrq-head__by">· opened by {record.created_by_name || 'a former member'}</span>
          </span>
        }
        tabs={
          <div role="tablist" aria-label="Merge request sections" data-testid="mr-tabs" className={TAB_LIST_CLASS}>
            {MERGE_REQUEST_TABS.map((id, index) => {
              const Glyph = TAB_GLYPH[id];
              const isActive = id === activeTab;
              return (
                <button
                  key={id}
                  ref={(element) => {
                    tabRefs.current[index] = element;
                  }}
                  type="button"
                  role="tab"
                  id={tabId(id)}
                  aria-selected={isActive}
                  aria-controls={panelId(id)}
                  tabIndex={isActive ? 0 : -1}
                  data-testid={`mr-tab-${id}`}
                  className={tabTriggerClass({ active: isActive })}
                  onClick={() => selectTab(id)}
                  onKeyDown={(event) => {
                    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
                      event.preventDefault();
                      focusTab(index + 1);
                    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
                      event.preventDefault();
                      focusTab(index - 1);
                    }
                  }}
                >
                  <Glyph aria-hidden className="rvw-tab__glyph" />
                  {MERGE_REQUEST_TAB_LABELS[id]}
                  {id === 'conflicts' && detail.conflicts.length ? (
                    <span className={TAB_COUNT_CLASS} data-testid="mr-tab-conflicts-count">
                      {detail.conflicts.length}
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>
        }
      />

      <PageBody>
        <div className="rvw">
          <div className="rvw-main">
            {record.description ? (
              <p className="mrq-description" data-testid="mr-description">
                {record.description}
              </p>
            ) : null}
            {MERGE_REQUEST_TABS.map((id) => (
              <div
                key={id}
                role="tabpanel"
                id={panelId(id)}
                aria-labelledby={tabId(id)}
                tabIndex={0}
                hidden={activeTab !== id}
                className="rvw-pane"
                data-testid={`mr-pane-${id}`}
              >
                {visited.has(id) ? panes[id] : null}
              </div>
            ))}
          </div>
          <aside className="rvw-aside" aria-label="Merge status">
            <MergeRequestActionsCard detail={detail} busy={busy} error={actionError} onAction={runAction} />
          </aside>
        </div>
      </PageBody>
    </Page>
  );
}
