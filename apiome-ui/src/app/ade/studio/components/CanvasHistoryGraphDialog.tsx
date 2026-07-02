'use client';

/**
 * In-canvas revision history graph dialog. Re-uses the dashboard's
 * `VersionHistoryGraphPanel` so the visualization stays in sync with Phase 3 polish.
 *
 * Canvas-specific wiring:
 *   - Fetches branches + tags on open (the panel needs them for tip labels, lane
 *     filtering, and tag pills).
 *   - `onCheckoutRevision` switches the canvas selection via `StudioContext` and
 *     triggers a canvas refresh, all without leaving the editor.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import VersionHistoryGraphPanel from '@/app/ade/dashboard/versions/VersionHistoryGraphPanel';
import {
  DEFAULT_HISTORY_WINDOW,
  type VersionHistoryBranchMeta,
  type VersionHistoryTag,
  type VersionHistoryVertex,
} from '@/app/ade/dashboard/versions/version-history-dag';
import type { Version } from '../editor/components/types';

export interface CanvasHistoryGraphDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  /** The canvas's full revision list (DB rows include parent / merge fields). */
  versions: Version[];
  /** Called when the user picks a revision to open on the canvas. */
  onCheckoutRevision: (revisionId: string) => void;
  /** Open the create-branch-from-revision dialog. */
  onBranchFromRevision?: (revisionId: string) => void;
  /** Current canvas head revision (pinned row in the studio) — powers "HEAD" toolbar button. */
  headRevisionId?: string | null;
}

type RuntimeVersion = Version & {
  parent_version_id?: string | null;
  merge_parent_version_id?: string | null;
  author?: string | null;
  creator_name?: string | null;
  creator_id?: string | null;
  message?: string | null;
};

function toVertex(v: Version): VersionHistoryVertex {
  const row = v as RuntimeVersion;
  return {
    id: v.id,
    version_id: v.version_id,
    parent_version_id: row.parent_version_id ?? null,
    merge_parent_version_id: row.merge_parent_version_id ?? null,
    created_at: v.created_at,
    shortMessage: v.shortMessage ?? null,
    commitMessage: row.message ?? v.description ?? null,
    authorName: row.author ?? row.creator_name ?? null,
    creatorId: row.creator_id ?? null,
  };
}

export function CanvasHistoryGraphDialog({
  open,
  onOpenChange,
  projectId,
  versions,
  onCheckoutRevision,
  onBranchFromRevision,
  headRevisionId,
}: CanvasHistoryGraphDialogProps) {
  const router = useRouter();
  const [branches, setBranches] = useState<VersionHistoryBranchMeta[]>([]);
  const [tags, setTags] = useState<VersionHistoryTag[]>([]);
  const [windowSize, setWindowSize] = useState<number>(DEFAULT_HISTORY_WINDOW);

  useEffect(() => {
    if (!open) return;
    if (!projectId) return;
    let cancelled = false;
    (async () => {
      try {
        const [bRes, tRes] = await Promise.all([
          fetch(`/api/projects/${projectId}/version-branches`),
          fetch(`/api/projects/${projectId}/version-tags`),
        ]);
        if (cancelled) return;

        const bJson = (await bRes.json().catch(() => ({}))) as {
          success?: boolean;
          branches?: Array<{ id: string; name: string; tip_version_id: string }>;
        };
        if (bJson.success && Array.isArray(bJson.branches)) {
          setBranches(
            bJson.branches.map((b) => ({
              id: b.id,
              name: b.name,
              tip_version_id: b.tip_version_id,
            }))
          );
        }

        const tJson = (await tRes.json().catch(() => ({}))) as {
          success?: boolean;
          tags?: Array<{
            id: string;
            name: string;
            version_id: string;
            immutable?: boolean;
            protected?: boolean;
          }>;
        };
        if (tJson.success && Array.isArray(tJson.tags)) {
          setTags(
            tJson.tags.map((t) => ({
              id: t.id,
              name: t.name,
              version_id: t.version_id,
              immutable: t.immutable,
              protected: t.protected,
            }))
          );
        }
      } catch {
        /* lane filter just falls back to layered layout */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, projectId]);

  const vertices = useMemo(() => versions.map(toVertex), [versions]);

  const handleCompare = useCallback(
    (revisionId: string) => {
      if (!projectId) return;
      router.push(
        `/ade/dashboard/versions?projectId=${encodeURIComponent(projectId)}&compareHead=${encodeURIComponent(revisionId)}`
      );
    },
    [projectId, router]
  );

  const handleViewSpec = useCallback(
    (revisionId: string) => {
      onCheckoutRevision(revisionId);
      onOpenChange(false);
    },
    [onCheckoutRevision, onOpenChange]
  );

  const handleCheckout = useCallback(
    (revisionId: string) => {
      onCheckoutRevision(revisionId);
      onOpenChange(false);
    },
    [onCheckoutRevision, onOpenChange]
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-6xl w-[92vw]" aria-describedby="canvas-history-desc">
        <DialogHeader>
          <DialogTitle>Revision history</DialogTitle>
          <DialogDescription id="canvas-history-desc">
            Click a node to compare with its primary parent (opens in the Versions dashboard).
            Ctrl/Cmd-click to switch the canvas to that revision. Use the node menu to switch to a
            revision, create a branch, or view its spec.
          </DialogDescription>
        </DialogHeader>
        <div className="py-2">
          {vertices.length === 0 ? (
            <div className="text-sm text-gray-500 dark:text-gray-400 p-6 text-center">
              No revisions yet.
            </div>
          ) : (
            <VersionHistoryGraphPanel
              key={branches.map((b) => b.id).sort().join('|') || 'canvas-graph-no-branches'}
              versions={vertices}
              branches={branches}
              tags={tags}
              headRevisionId={headRevisionId}
              selectedRevisionId={headRevisionId}
              windowSize={windowSize}
              onWindowSizeIncrease={setWindowSize}
              onCompareToPrimaryParent={handleCompare}
              onViewSpec={handleViewSpec}
              onBranchFromRevision={onBranchFromRevision}
              onCheckoutRevision={handleCheckout}
            />
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

export default CanvasHistoryGraphDialog;
