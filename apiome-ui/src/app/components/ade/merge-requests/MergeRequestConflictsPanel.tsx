'use client';

/**
 * The merge request page's Conflicts tab — COL-4.3 (#4527).
 *
 * Conflicts are the **merge session's** conflict rows, shown in the existing merge-session conflict
 * list (`VersionMergeConflictList`, the same one the Merge branches dialog uses) — there is no second
 * conflict UX. A merge only ever applies the three-way result, so resolving means changing the
 * draft branch until the paths no longer overlap; the list's mine / theirs marks are a checklist for
 * that work, and **Check for conflicts** runs a fresh session against the current tips.
 */

import * as React from 'react';
import { GitMerge } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { normalizeMergeConflictRows, type MergeConflictResolutionChoice } from '@lib/version-merge';
import type { MergeRequestDetail } from '@lib/merge-requests';

import { VersionMergeConflictList } from '../dashboard/VersionMergeConflictList';

export interface MergeRequestConflictsPanelProps {
  detail: MergeRequestDetail;
}

/**
 * The Conflicts tab.
 *
 * @param props - See {@link MergeRequestConflictsPanelProps}.
 * @returns The panel.
 */
export function MergeRequestConflictsPanel({ detail }: MergeRequestConflictsPanelProps) {
  const { merge_request: record, merge_session: session, conflicts } = detail;
  const [resolutions, setResolutions] = React.useState<Record<string, MergeConflictResolutionChoice | null>>({});
  const rows = React.useMemo(() => normalizeMergeConflictRows(conflicts, []), [conflicts]);

  if (!session) {
    return (
      <EmptyState
        icon={<GitMerge />}
        title="Not checked yet"
        description="Check for conflicts runs a merge session against the current tips."
        data-testid="mr-conflicts-unchecked"
      />
    );
  }

  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<GitMerge />}
        title="No conflicts"
        description={`The last merge session found nothing overlapping with ${record.target_branch_name}.`}
        data-testid="mr-conflicts-none"
      />
    );
  }

  return (
    <section className="mrq-conflicts" aria-label="Conflicts" data-testid="mr-conflicts">
      <Alert variant="warn" data-testid="mr-conflicts-help">
        {rows.length} path(s) changed on both {record.source_branch_name} and {record.target_branch_name}. Update the
        draft branch so each path keeps the version you want, then choose <strong>Check for conflicts</strong>.
      </Alert>
      <VersionMergeConflictList
        conflicts={rows}
        targetBranchName={record.target_branch_name}
        sourceBranchName={record.source_branch_name}
        resolutions={resolutions}
        onResolve={(path, choice) => setResolutions((previous) => ({ ...previous, [path]: choice }))}
        onBulkResolve={(paths, choice) =>
          setResolutions((previous) => {
            const next = { ...previous };
            for (const path of paths) next[path] = choice;
            return next;
          })
        }
      />
    </section>
  );
}
