'use client';

/**
 * The Versions screen's **Merge requests** tab — COL-4.3 (#4527).
 *
 * The project's branch / merge-request workflow in one place:
 *
 * - **Merge requests** — filtered by state (Open · Merged · Closed); each row opens its page.
 * - **Draft branches** — each with the version line it was drafted off and its tip, and an
 *   **Open merge request** shortcut for a draft that has none open.
 * - **New draft branch** and **Open merge request** — the two dialogs.
 *
 * The screen passes its branch list in and is told when a draft is created, so its own branch
 * menus stay current.
 */

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { GitBranch, GitBranchPlus, GitPullRequestArrow } from 'lucide-react';

import { Alert } from '../../ui/Alert';
import { Badge } from '../../ui/Badge';
import { Button } from '../../ui/Button';
import { EmptyState } from '../../ui/EmptyState';
import { LoadingState } from '../../ui/LoadingState';
import { Segmented, SegmentedItem } from '../../ui/Segmented';
import { formatVersionWithPrefix } from '@/app/utils/version-display';
import {
  MERGE_REQUEST_FILTERS,
  MERGE_REQUEST_STATE_BADGE,
  mergeRequestHref,
  type DraftBranchRecord,
  type MergeRequestRecord,
  type MergeRequestState,
} from '@lib/merge-requests';
import type { VersionBranchRow } from '../version-dialogs/types';
import { callMergeRequestApi } from './mergeRequestFetch';
import { NewDraftBranchDialog } from './NewDraftBranchDialog';
import { OpenMergeRequestDialog } from './OpenMergeRequestDialog';

export interface MergeRequestsPanelProps {
  projectId: string;
  /** The project's branches. */
  branches: ReadonlyArray<VersionBranchRow>;
  /** Called after a draft branch is created, so the screen can reload its branches. */
  onBranchesChanged?: () => void;
}

/** A load in progress, failed, or done. */
type Loaded<T> = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; data: T };

/**
 * The tab.
 *
 * @param props - See {@link MergeRequestsPanelProps}.
 * @returns The panel.
 */
export function MergeRequestsPanel({ projectId, branches, onBranchesChanged }: MergeRequestsPanelProps) {
  const router = useRouter();
  const [filter, setFilter] = React.useState<MergeRequestState>('open');
  const [requests, setRequests] = React.useState<Loaded<MergeRequestRecord[]>>({ status: 'loading' });
  const [drafts, setDrafts] = React.useState<DraftBranchRecord[]>([]);
  const [openRequests, setOpenRequests] = React.useState<MergeRequestRecord[]>([]);
  const [reloadToken, setReloadToken] = React.useState(0);
  const [draftDialogOpen, setDraftDialogOpen] = React.useState(false);
  const [openDialog, setOpenDialog] = React.useState<{ source?: string } | null>(null);
  const base = `/api/projects/${encodeURIComponent(projectId)}`;

  // The requests in the chosen state.
  React.useEffect(() => {
    let cancelled = false;
    setRequests({ status: 'loading' });
    (async () => {
      const json = await callMergeRequestApi<{ merge_requests: MergeRequestRecord[] }>(
        `${base}/merge-requests?state=${filter}`
      );
      if (cancelled) return;
      if (!json.success || !Array.isArray(json.merge_requests)) {
        setRequests({ status: 'error', message: json.error || 'Could not load merge requests.' });
        return;
      }
      setRequests({ status: 'ready', data: json.merge_requests });
    })();
    return () => {
      cancelled = true;
    };
  }, [base, filter, reloadToken]);

  // The draft branches, and which of them already have an open request.
  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      const [draftJson, openJson] = await Promise.all([
        callMergeRequestApi<{ branches: DraftBranchRecord[] }>(`${base}/draft-branches`),
        callMergeRequestApi<{ merge_requests: MergeRequestRecord[] }>(`${base}/merge-requests?state=open`),
      ]);
      if (cancelled) return;
      setDrafts(draftJson.success && Array.isArray(draftJson.branches) ? draftJson.branches : []);
      setOpenRequests(openJson.success && Array.isArray(openJson.merge_requests) ? openJson.merge_requests : []);
    })();
    return () => {
      cancelled = true;
    };
  }, [base, reloadToken]);

  const openBySource = React.useMemo(
    () => new Map(openRequests.map((request) => [request.source_branch_id, request])),
    [openRequests]
  );
  // Memoized: the dialog resets its form whenever this list changes identity.
  const availableDrafts = React.useMemo(
    () => drafts.filter((draft) => !openBySource.has(draft.id)),
    [drafts, openBySource]
  );

  let list: React.ReactNode;
  if (requests.status === 'loading') {
    list = <LoadingState message="Loading merge requests…" data-testid="mr-list-loading" />;
  } else if (requests.status === 'error') {
    list = (
      <Alert variant="danger" data-testid="mr-list-error">
        {requests.message}
      </Alert>
    );
  } else if (requests.data.length === 0) {
    list = (
      <EmptyState
        icon={<GitPullRequestArrow />}
        title={`No ${MERGE_REQUEST_STATE_BADGE[filter].label.toLowerCase()} merge requests`}
        description="Draft a change on a branch, then open a merge request for review."
        data-testid="mr-list-empty"
      />
    );
  } else {
    list = (
      <ul className="mrq-list" data-testid="mr-list">
        {requests.data.map((request) => {
          const badge = MERGE_REQUEST_STATE_BADGE[request.state];
          return (
            <li key={request.id} className="mrq-row" data-testid="mr-row">
              <Link className="mrq-row__title" href={mergeRequestHref(request.id)}>
                {request.title}
              </Link>
              <Badge variant={badge.variant}>{badge.label}</Badge>
              <span className="mrq-row__meta">
                <span className="mono">{request.source_branch_name}</span> →{' '}
                <span className="mono">{request.target_branch_name}</span> · opened by{' '}
                {request.created_by_name || 'a former member'}
              </span>
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <section className="mrq-panel" aria-label="Merge requests" data-testid="mr-panel">
      <div className="mrq-panel__head">
        <Segmented
          size="sm"
          value={filter}
          onValueChange={(next) => setFilter(next as MergeRequestState)}
          aria-label="Which merge requests to show"
        >
          {MERGE_REQUEST_FILTERS.map((state) => (
            <SegmentedItem key={state} value={state} data-testid={`mr-filter-${state}`}>
              {MERGE_REQUEST_STATE_BADGE[state].label}
            </SegmentedItem>
          ))}
        </Segmented>
        <div className="mrq-panel__actions">
          <Button
            variant="outline"
            onClick={() => setDraftDialogOpen(true)}
            disabled={branches.length === 0}
            data-testid="mr-new-draft"
          >
            <GitBranchPlus aria-hidden />
            New draft branch
          </Button>
          <Button onClick={() => setOpenDialog({})} disabled={availableDrafts.length === 0} data-testid="mr-open">
            <GitPullRequestArrow aria-hidden />
            Open merge request
          </Button>
        </div>
      </div>

      {list}

      <section className="mrq-drafts" aria-label="Draft branches" data-testid="mr-drafts">
        <h3 className="mrq-drafts__title">Draft branches</h3>
        {drafts.length === 0 ? (
          <p className="mrq-drafts__empty">No draft branches yet. A draft branch keeps your edits off the line.</p>
        ) : (
          <ul className="mrq-list">
            {drafts.map((draft) => {
              const open = openBySource.get(draft.id);
              return (
                <li key={draft.id} className="mrq-row" data-testid="mr-draft-row">
                  <GitBranch aria-hidden className="mrq-row__glyph" />
                  <span className="mrq-row__title mono">{draft.name}</span>
                  <span className="mrq-row__meta">
                    off {draft.base_branch_name ?? 'a deleted branch'} · tip{' '}
                    {formatVersionWithPrefix(draft.tip_version_label) || draft.tip_revision_id}
                  </span>
                  {open ? (
                    <Link className="mrq-row__link" href={mergeRequestHref(open.id)}>
                      Open merge request
                    </Link>
                  ) : (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setOpenDialog({ source: draft.name })}
                      data-testid="mr-draft-open"
                    >
                      Open merge request
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <NewDraftBranchDialog
        open={draftDialogOpen}
        onOpenChange={setDraftDialogOpen}
        projectId={projectId}
        branches={branches}
        onCreated={() => {
          setReloadToken((token) => token + 1);
          onBranchesChanged?.();
        }}
      />
      <OpenMergeRequestDialog
        open={openDialog !== null}
        onOpenChange={(next) => (next ? undefined : setOpenDialog(null))}
        projectId={projectId}
        drafts={availableDrafts}
        branches={branches}
        initialSource={openDialog?.source}
        onOpened={(detail) => router.push(mergeRequestHref(detail.merge_request.id))}
      />
    </section>
  );
}
