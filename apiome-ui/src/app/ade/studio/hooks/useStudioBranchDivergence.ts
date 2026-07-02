'use client';

import { useEffect, useMemo, useSyncExternalStore } from 'react';
import { useStudio } from '../StudioContext';
import { resolveActiveBranchForRevision } from '@/app/ade/studio/lib/studio-branch-resolve';
import type { VersionBranchRow } from '@/app/components/ade/version-dialogs/types';

export type BranchDivergencePayload = {
  ahead: number;
  behind: number;
  mergeBase?: { revisionId?: string | null } | null;
  against?: { name?: string | null; tipRevisionId?: string | null } | null;
  branch?: { tipRevisionId?: string | null } | null;
  aheadSample?: Array<{ revisionId?: string; shortMessage?: string | null }>;
  behindSample?: Array<{ revisionId?: string; shortMessage?: string | null }>;
};

type DivergenceEntry = {
  data: BranchDivergencePayload | null;
  error: string | null;
  loading: boolean;
  etag: string | null;
};

const EMPTY_DIVERGENCE: DivergenceEntry = {
  data: null,
  error: null,
  loading: false,
  etag: null,
};

const divergenceByKey = new Map<string, DivergenceEntry>();
const divergenceListeners = new Set<() => void>();

function divergenceNotify() {
  divergenceListeners.forEach((l) => l());
}

function divergenceGet(key: string): DivergenceEntry {
  if (!key) return EMPTY_DIVERGENCE;
  return divergenceByKey.get(key) ?? EMPTY_DIVERGENCE;
}

function divergenceSet(key: string, patch: Partial<DivergenceEntry>) {
  const prev = divergenceGet(key);
  divergenceByKey.set(key, { ...prev, ...patch });
  divergenceNotify();
}

function subscribeDivergence(cb: () => void) {
  divergenceListeners.add(cb);
  return () => divergenceListeners.delete(cb);
}

const divergenceInflight = new Map<string, Promise<void>>();

/**
 * Fetches default-branch vs active-branch divergence for the current canvas revision (#2723 GLI-04).
 * Shared across subscribers (#2726) so toolbar + git menu do not duplicate GET …/divergence.
 */
export function useStudioBranchDivergence() {
  const {
    selectedProjectId,
    selectedVersionId,
    selectedBranchId,
    sidebarRefreshKey,
    canvasPresentationMode,
    versionBranchesByProjectId,
  } = useStudio();

  const branchesForLabel = useMemo(
    () => (selectedProjectId ? (versionBranchesByProjectId[selectedProjectId] ?? []) : []),
    [selectedProjectId, versionBranchesByProjectId]
  );

  const resolvedBranch = useMemo(() => {
    if (!selectedVersionId || !branchesForLabel.length) return null;
    return resolveActiveBranchForRevision(selectedVersionId, branchesForLabel);
  }, [selectedVersionId, branchesForLabel]);

  const displayBranch: VersionBranchRow | null = useMemo(() => {
    if (selectedBranchId && branchesForLabel.length) {
      const byId = branchesForLabel.find((b) => b.id === selectedBranchId);
      if (byId) return byId;
    }
    return resolvedBranch;
  }, [selectedBranchId, branchesForLabel, resolvedBranch]);

  const showDivergence = Boolean(
    selectedProjectId &&
      selectedVersionId &&
      displayBranch &&
      displayBranch.is_default === false &&
      !canvasPresentationMode
  );

  const branchIdForFetch = displayBranch?.id ?? '';

  const fetchKey = useMemo(() => {
    if (!showDivergence || !selectedProjectId || !branchIdForFetch) return '';
    return `${selectedProjectId}:${branchIdForFetch}`;
  }, [showDivergence, selectedProjectId, branchIdForFetch]);

  const snapshot = useSyncExternalStore(
    subscribeDivergence,
    () => divergenceGet(fetchKey),
    () => divergenceGet(fetchKey)
  );

  useEffect(() => {
    if (!fetchKey || !selectedProjectId || !branchIdForFetch) return;

    if (divergenceInflight.has(fetchKey)) {
      return;
    }

    const run = (async () => {
      const prevEntry = divergenceGet(fetchKey);
      divergenceSet(fetchKey, { loading: true, error: null });

      try {
        const url = `/api/projects/${encodeURIComponent(selectedProjectId)}/version-branches/${encodeURIComponent(branchIdForFetch)}/divergence`;
        const headers: Record<string, string> = {};
        if (prevEntry.etag) {
          headers['If-None-Match'] = prevEntry.etag;
        }
        const r = await fetch(url, { headers });
        const etag = r.headers.get('etag');
        if (r.status === 304) {
          divergenceSet(fetchKey, { loading: false });
          return;
        }
        if (!r.ok) {
          const j = (await r.json().catch(() => null)) as { detail?: unknown; error?: string } | null;
          const msg =
            typeof j?.error === 'string'
              ? j.error
              : typeof j?.detail === 'object' && j.detail !== null && 'message' in j.detail
                ? String((j.detail as { message?: string }).message ?? 'Request failed')
                : 'Could not load branch divergence';
          divergenceSet(fetchKey, { error: msg, data: null, loading: false });
          return;
        }
        const json = (await r.json()) as BranchDivergencePayload;
        divergenceSet(fetchKey, {
          data: json,
          error: null,
          loading: false,
          etag: etag ?? null,
        });
      } catch {
        divergenceSet(fetchKey, { error: 'Could not load branch divergence', data: null, loading: false });
      }
    })();

    divergenceInflight.set(fetchKey, run);
    void run.finally(() => {
      divergenceInflight.delete(fetchKey);
    });
  }, [fetchKey, selectedProjectId, branchIdForFetch, sidebarRefreshKey]);

  const defaultBranchName = useMemo(() => {
    const fromBranches = branchesForLabel.find((b) => b.is_default)?.name?.trim() ?? '';
    if (fromBranches) return fromBranches;
    return snapshot.data?.against?.name?.trim() ?? '';
  }, [branchesForLabel, snapshot.data?.against?.name]);

  const activeBranchName = displayBranch?.name?.trim() ?? '';

  return {
    selectedProjectId,
    showDivergence,
    data: snapshot.data,
    loading: snapshot.loading,
    error: snapshot.error,
    displayBranch,
    branchesForLabel,
    defaultBranchName,
    activeBranchName,
  };
}
