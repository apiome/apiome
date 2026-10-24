'use client';

/**
 * Federation merge history — V2-REPO-8.2 (#2806).
 *
 * One list, two homes: the project's **Merge history** on the Versions → Sources tab, and a
 * repository's **Sync history** on its Imports tab. Each row is one repository-file import that
 * federation acted on — **Merged**, **Conflict** (nothing was written) or **Replaced** (federation
 * off). A conflict row opens to show, for each colliding class or path, both sources' definitions
 * as one line diff: the lines only the contributing file has, the lines only the imported file has,
 * and the lines they share — the per-source diff the ticket asks for.
 *
 * Reads only (`projects:view` / `imports:view`, enforced by apiome-rest).
 */

import * as React from 'react';
import { GitMerge } from 'lucide-react';

import { Badge } from '@/app/components/ui/Badge';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { ErrorState } from '@/app/components/ui/ErrorState';
import { CatalogTimelineSkeleton } from '@/app/components/ade/catalog/CatalogSkeletons';
import {
  FEDERATION_STATUS_LABEL,
  FEDERATION_STATUS_TONE,
  conflictDiff,
  mergeSentence,
  parseFederationMerges,
  sourceText,
  type FederationConflict,
  type FederationMerge,
} from '@lib/repository-federation';

export interface FederationMergeHistoryProps {
  /** The BFF route to read (`/api/projects/{id}/federation-merges` or `/api/repositories/{id}/…`). */
  url: string;
  /** `project` names the imported file on each row; `repository` names the project. */
  scope: 'project' | 'repository';
  /** Re-read when this changes (e.g. after the switch moves). */
  refreshKey?: unknown;
  /** Shown when there is no history. */
  emptyDescription: string;
  /** Test id of the list. */
  'data-testid'?: string;
}

const LOAD_ERROR = 'Could not load the merge history.';

/** Marks before each diff line, matching who has it. */
const MARK: Record<'same' | 'existing' | 'incoming', string> = { same: ' ', existing: '−', incoming: '+' };

/**
 * Both sources' definitions of one colliding class or path, as one line diff.
 *
 * @param props - The conflict.
 * @returns The diff block.
 */
export function FederationConflictDiff({ conflict }: { conflict: FederationConflict }): React.JSX.Element {
  const existing = conflict.sources.find((s) => s.role === 'existing') ?? conflict.sources[0];
  const incoming = conflict.sources.find((s) => s.role === 'incoming') ?? conflict.sources[1];
  const lines = conflictDiff(conflict);
  return (
    <div className="fed-conflict" data-testid="federation-conflict">
      <div className="fed-conflict__title">
        <Badge variant="neutral" square>
          {conflict.kind === 'class' ? 'Class' : 'Path'}
        </Badge>
        <span className="mono">{conflict.key}</span>
      </div>
      <ul className="fed-conflict__legend">
        <li className="fed-legend fed-legend--existing">
          <span aria-hidden>−</span> Only in <span className="mono">{sourceText(existing)}</span> (already contributing)
        </li>
        <li className="fed-legend fed-legend--incoming">
          <span aria-hidden>+</span> Only in <span className="mono">{sourceText(incoming)}</span> (imported)
        </li>
      </ul>
      <pre className="fed-diff" aria-label={`Definitions of ${conflict.key} in both files`} data-testid="federation-diff">
        {lines.map((line, index) => (
          <span key={index} className={`fed-diff__line fed-diff__line--${line.change}`} data-change={line.change}>
            <span className="fed-diff__mark" aria-hidden>
              {MARK[line.change]}
            </span>
            {line.text}
            {'\n'}
          </span>
        ))}
      </pre>
    </div>
  );
}

/**
 * One history row.
 *
 * @param props - The row and the list's scope.
 * @returns The list item.
 */
function MergeRow({ merge, scope }: { merge: FederationMerge; scope: 'project' | 'repository' }): React.JSX.Element {
  const when = merge.createdAt ? new Date(merge.createdAt).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' }) : '';
  return (
    <li className="fed-row" data-testid="federation-merge" data-status={merge.status}>
      <div className="fed-row__head">
        <Badge variant={FEDERATION_STATUS_TONE[merge.status]} data-testid={`federation-status-${merge.status}`}>
          {FEDERATION_STATUS_LABEL[merge.status]}
        </Badge>
        <span className="fed-row__name mono">
          {scope === 'project' ? sourceText(merge) : (merge.projectName ?? 'Deleted project')}
        </span>
        {scope === 'repository' ? <span className="fed-muted mono">{`${merge.branch}:${merge.path}`}</span> : null}
        <span className="fed-row__when">{when}</span>
      </div>
      <p className="fed-row__sentence">{mergeSentence(merge)}</p>
      {merge.conflicts.length > 0 ? (
        <details className="fed-details">
          <summary>
            Show {merge.conflicts.length === 1 ? 'the conflict' : `the ${merge.conflicts.length} conflicts`}
            {merge.conflictCount > merge.conflicts.length ? ` (of ${merge.conflictCount})` : ''}
          </summary>
          {merge.conflicts.map((conflict) => (
            <FederationConflictDiff key={`${conflict.kind}:${conflict.key}`} conflict={conflict} />
          ))}
        </details>
      ) : null}
    </li>
  );
}

/**
 * The merge history list. See {@link FederationMergeHistoryProps}.
 *
 * @returns The list, its empty state, or its error.
 */
export function FederationMergeHistory({
  url,
  scope,
  refreshKey,
  emptyDescription,
  'data-testid': testId = 'federation-history',
}: FederationMergeHistoryProps): React.JSX.Element {
  const [merges, setMerges] = React.useState<FederationMerge[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  // RC6-H3 (#6210): bumped by the error state's retry.
  const [attempt, setAttempt] = React.useState(0);

  React.useEffect(() => {
    let cancelled = false;
    setError(null);
    (async () => {
      try {
        const response = await fetch(url);
        const payload = await response.json().catch(() => null);
        const parsed = response.ok ? parseFederationMerges(payload) : null;
        if (cancelled) return;
        if (parsed) {
          setMerges(parsed);
          setError(null);
        } else {
          setError((payload as { error?: string } | null)?.error || LOAD_ERROR);
        }
      } catch {
        if (!cancelled) setError(LOAD_ERROR);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [url, refreshKey, attempt]);

  if (error) {
    return (
      <ErrorState
        variant="compact"
        title="Couldn't load the merge history"
        description={error}
        onRetry={() => setAttempt((count) => count + 1)}
        data-testid={`${testId}-error`}
      />
    );
  }
  if (!merges) {
    return <CatalogTimelineSkeleton message="Loading merge history…" testId={`${testId}-loading`} />;
  }
  if (merges.length === 0) {
    return (
      <EmptyState
        variant="inline"
        icon={<GitMerge aria-hidden />}
        title="No merges yet"
        description={emptyDescription}
        titleAs="p"
        data-testid={`${testId}-empty`}
      />
    );
  }
  return (
    <ul className="fed-list" data-testid={testId}>
      {merges.map((merge) => (
        <MergeRow key={merge.id} merge={merge} scope={scope} />
      ))}
    </ul>
  );
}
