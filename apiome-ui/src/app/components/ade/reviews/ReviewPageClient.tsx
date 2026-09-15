'use client';

/**
 * The review page — COL-2.2 (#4518).
 *
 * One page with everything a reviewer needs to decide on a draft version, so the decision never
 * has to happen somewhere else:
 *
 * - **Header** — breadcrumb to the project, "Review of v1.2.0", the review's state, who requested
 *   it, the round, and the round's tally.
 * - **Changes** — the classified diff against the newest published version, with a plain diff
 *   beside it (`ReviewChangesPanel`).
 * - **Spec** — the version's OpenAPI document, read-only (`ReviewSpecPanel`).
 * - **Discussion** — the version's comment threads, open ones first (`ProjectDiscussionPanel`
 *   narrowed to the version).
 * - **Reviewers** — the current round's decisions and every earlier round's (`ReviewReviewers`).
 * - **Decision bar** — sticky at the foot: Approve / Request changes, a note required with the
 *   latter (`ReviewDecisionBar`).
 *
 * The tab strip is hand-built on the shared tab classes, for the reason the catalog item detail
 * records: Radix `Tabs.Root` would have to wrap the header *and* the body. A pane mounts the first
 * time its tab is shown and then stays mounted (hidden), so the diff, the document and the threads
 * each load only when the reviewer asks for them, and a tab switch keeps what was loaded.
 */

import * as React from 'react';
import { toast } from 'sonner';
import { FileJson2, GitCompareArrows, MessagesSquare, type LucideIcon } from 'lucide-react';

import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { Alert } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import { ErrorState } from '@/app/components/ui/ErrorState';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { TAB_LIST_CLASS, tabTriggerClass } from '@/app/components/ui/tabStyles';
import { ProjectDiscussionPanel } from '@/app/components/ade/discussion/ProjectDiscussionPanel';
import { formatVersionWithPrefix } from '@/app/utils/version-display';
import { getStudioWorkspaceRoute } from '@lib/external-links';
import {
  REVIEW_TABS,
  REVIEW_TAB_LABELS,
  decisionBarModel,
  decisionPayload,
  reviewErrorMessage,
  reviewProgressText,
  reviewStatusBadge,
  type RecordableDecision,
  type ReviewDetail,
  type ReviewPagePayload,
  type ReviewTabId,
} from '@lib/review-page';

import { ReviewChangesPanel } from './ReviewChangesPanel';
import { ReviewDecisionBar } from './ReviewDecisionBar';
import { ReviewReviewers } from './ReviewReviewers';
import { ReviewSpecPanel } from './ReviewSpecPanel';

/** Each tab's glyph. */
const TAB_GLYPH: Readonly<Record<ReviewTabId, LucideIcon>> = {
  changes: GitCompareArrows,
  spec: FileJson2,
  discussion: MessagesSquare,
};

/** Refusals that mean the review moved on while the reviewer was reading, so it is read again. */
const RELOAD_ON_CODES: ReadonlySet<string> = new Set([
  'review-already-decided',
  'review-not-in-review',
  'review-closed',
  'review-spec-changed',
  'review-version-published',
  'review-conflict',
]);

/** The breadcrumb's first step. */
const PROJECTS_CRUMB = { label: 'Projects', href: '/ade/dashboard/projects' } as const;

/** What the page is showing. */
type LoadState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; payload: ReviewPagePayload };

/** A BFF envelope. */
type Envelope<T> = Partial<T> & { success?: boolean; error?: string; code?: string };

/**
 * Parse a BFF reply.
 *
 * @param response - The reply.
 * @returns Its envelope, or a failure envelope when the body is not JSON.
 */
async function readEnvelope<T>(response: Response): Promise<Envelope<T>> {
  try {
    return (await response.json()) as Envelope<T>;
  } catch {
    return { success: false, error: `The server answered ${response.status}.` } as Envelope<T>;
  }
}

/** A tab's element id. */
function tabId(id: ReviewTabId): string {
  return `review-tab-${id}`;
}

/** A pane's element id. */
function panelId(id: ReviewTabId): string {
  return `review-pane-${id}`;
}

export interface ReviewPageClientProps {
  /** The review id from the URL. */
  reviewId: string;
  /** The tab `?tab=` asked for. */
  initialTab?: ReviewTabId;
}

/**
 * The review page.
 *
 * @param props - See {@link ReviewPageClientProps}.
 * @returns The page.
 */
export default function ReviewPageClient({ reviewId, initialTab = 'changes' }: ReviewPageClientProps) {
  const [load, setLoad] = React.useState<LoadState>({ status: 'loading' });
  const [reloadToken, setReloadToken] = React.useState(0);
  const [activeTab, setActiveTab] = React.useState<ReviewTabId>(initialTab);
  const [visited, setVisited] = React.useState<ReadonlySet<ReviewTabId>>(() => new Set([initialTab]));
  const [submitting, setSubmitting] = React.useState(false);
  const [decisionError, setDecisionError] = React.useState<string | null>(null);
  const tabRefs = React.useRef<Array<HTMLButtonElement | null>>([]);
  const workspaceRoute = React.useMemo(() => getStudioWorkspaceRoute(), []);
  const routeBase = `/api/reviews/${encodeURIComponent(reviewId)}`;

  // The review. A reload keeps the page on screen and swaps the answer in when it arrives.
  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const json = await readEnvelope<ReviewPagePayload>(await fetch(routeBase));
        if (cancelled) return;
        if (!json.success || !json.review || !json.project) {
          setLoad({
            status: 'error',
            message: reviewErrorMessage(json.code, json.error || 'Could not load this review.'),
          });
          return;
        }
        setLoad({
          status: 'ready',
          payload: { review: json.review, project: json.project, viewerId: json.viewerId ?? null },
        });
      } catch (error) {
        if (!cancelled) {
          setLoad({
            status: 'error',
            message: error instanceof Error ? error.message : 'Could not load this review.',
          });
        }
      }
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
  const selectTab = (id: ReviewTabId) => {
    setActiveTab(id);
    setVisited((previous) => (previous.has(id) ? previous : new Set([...previous, id])));
    try {
      const url = new URL(window.location.href);
      url.searchParams.set('tab', id);
      window.history.replaceState(window.history.state, '', url.toString());
    } catch {
      // The address is a convenience; the tab switch has already happened.
    }
  };

  /**
   * Move focus to a tab and show it — the roving tabindex's arrow keys.
   *
   * @param index - The tab's index; wraps around both ends.
   */
  const focusTab = (index: number) => {
    const next = (index + REVIEW_TABS.length) % REVIEW_TABS.length;
    tabRefs.current[next]?.focus();
    selectTab(REVIEW_TABS[next]);
  };

  /**
   * Record the viewer's decision.
   *
   * @param decision - Approve or request changes.
   * @param note - The note as typed.
   * @returns True when it was recorded.
   */
  const submitDecision = async (decision: RecordableDecision, note: string): Promise<boolean> => {
    setSubmitting(true);
    setDecisionError(null);
    try {
      const response = await fetch(`${routeBase}/decision`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(decisionPayload(decision, note)),
      });
      const json = await readEnvelope<{ review: ReviewDetail }>(response);
      if (!json.success || !json.review) {
        setDecisionError(reviewErrorMessage(json.code, json.error || 'Could not record your decision.'));
        if (json.code && RELOAD_ON_CODES.has(json.code)) setReloadToken((token) => token + 1);
        return false;
      }
      const review = json.review;
      setLoad((previous) =>
        previous.status === 'ready' ? { status: 'ready', payload: { ...previous.payload, review } } : previous
      );
      toast.success(decision === 'approve' ? 'You approved this version.' : 'You requested changes.');
      return true;
    } catch (error) {
      setDecisionError(error instanceof Error ? error.message : 'Could not record your decision.');
      return false;
    } finally {
      setSubmitting(false);
    }
  };

  if (load.status === 'loading') {
    return (
      <Page>
        <PageBody>
          <LoadingState message="Loading review…" data-testid="review-loading" />
        </PageBody>
      </Page>
    );
  }

  if (load.status === 'error') {
    return (
      <Page>
        <PageHeader title="Review" breadcrumb={[PROJECTS_CRUMB]} />
        <PageBody>
          <ErrorState
            description={load.message}
            onRetry={() => {
              setLoad({ status: 'loading' });
              setReloadToken((token) => token + 1);
            }}
            data-testid="review-error"
          />
        </PageBody>
      </Page>
    );
  }

  const { review: detail, project, viewerId } = load.payload;
  const { review } = detail;
  const badge = reviewStatusBadge(review);
  const versionName = formatVersionWithPrefix(review.version_label) || 'this version';
  const bar = decisionBarModel(detail, viewerId);

  const panes: Record<ReviewTabId, React.ReactNode> = {
    changes: <ReviewChangesPanel reviewId={reviewId} />,
    spec: <ReviewSpecPanel reviewId={reviewId} projectSlug={project.slug} versionLabel={review.version_label} />,
    discussion: (
      <ProjectDiscussionPanel
        projectId={project.id}
        versions={[{ id: review.version_id, version_id: review.version_label ?? '' }]}
        workspaceRoute={workspaceRoute}
        versionId={review.version_id}
      />
    ),
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
          { label: 'Review' },
        ]}
        title={`Review of ${versionName}`}
        badge={
          <Badge variant={badge.variant} data-testid="review-status">
            {badge.label}
          </Badge>
        }
        description={
          <span data-testid="review-summary">
            Requested by {review.requested_by_name || 'a former member'} · Round {review.round} ·{' '}
            {reviewProgressText(review)}
          </span>
        }
        tabs={
          <div
            role="tablist"
            aria-label="Review sections"
            data-testid="review-tabs"
            className={TAB_LIST_CLASS}
          >
            {REVIEW_TABS.map((id, index) => {
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
                  data-testid={`review-tab-${id}`}
                  className={tabTriggerClass({ active: isActive })}
                  onClick={() => selectTab(id)}
                  onKeyDown={(event) => {
                    switch (event.key) {
                      case 'ArrowRight':
                      case 'ArrowDown':
                        event.preventDefault();
                        focusTab(index + 1);
                        break;
                      case 'ArrowLeft':
                      case 'ArrowUp':
                        event.preventDefault();
                        focusTab(index - 1);
                        break;
                      case 'Home':
                        event.preventDefault();
                        focusTab(0);
                        break;
                      case 'End':
                        event.preventDefault();
                        focusTab(REVIEW_TABS.length - 1);
                        break;
                      default:
                        break;
                    }
                  }}
                >
                  <Glyph aria-hidden className="rvw-tab__glyph" />
                  {REVIEW_TAB_LABELS[id]}
                </button>
              );
            })}
          </div>
        }
      />

      <PageBody>
        <div className="rvw">
          <div className="rvw-main">
            {detail.spec_changed && !review.closed_at ? (
              <Alert variant="warning" data-testid="review-stale">
                This version changed after round {review.round} was requested, so the decisions below judged
                different content. The review has to be re-requested.
              </Alert>
            ) : null}
            {REVIEW_TABS.map((id) => (
              <div
                key={id}
                role="tabpanel"
                id={panelId(id)}
                aria-labelledby={tabId(id)}
                tabIndex={0}
                hidden={activeTab !== id}
                className="rvw-pane"
                data-testid={`review-pane-${id}`}
              >
                {visited.has(id) ? panes[id] : null}
              </div>
            ))}
          </div>
          <aside className="rvw-aside" aria-label="Reviewers">
            <ReviewReviewers detail={detail} viewerId={viewerId} />
          </aside>
        </div>
        <ReviewDecisionBar
          key={`${review.id}:${review.round}`}
          model={bar}
          submitting={submitting}
          error={decisionError}
          onSubmit={submitDecision}
        />
      </PageBody>
    </Page>
  );
}
