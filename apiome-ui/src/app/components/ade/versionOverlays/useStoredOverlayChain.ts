'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';

import type { ExportStudioOverlay } from '../dashboard/export/exportOverlays';
import {
  CODE_VERSION_PUBLISHED,
  VersionOverlaysError,
  addVersionOverlay,
  fetchVersionOverlays,
  isRevisionId,
  type VersionOverlayChain,
} from './versionOverlaysApi';

/** What {@link useStoredOverlayChain} exposes to Export Studio. */
export interface StoredOverlayChainState {
  /** The chain, or null while it loads, when it failed, or when no revision id is known. */
  chain: VersionOverlayChain | null;
  /** Why the chain could not be read. */
  error: string | null;
  /** Whether the export applies the chain (the REST default is true). */
  apply: boolean;
  /** Switch applying it. */
  setApply: (apply: boolean) => void;
  /**
   * Save an uploaded overlay into the chain (`source: export-studio`) and reload it.
   *
   * @returns null on success, or the message to show.
   */
  saveToChain: (overlay: ExportStudioOverlay) => Promise<string | null>;
  /** True when a specific revision is exported, so a stored chain can exist. */
  available: boolean;
}

/**
 * Load a revision's stored overlay chain (GVM-4.3) for Export Studio's Overlays step.
 *
 * The chain is addressed by revision id. When the Studio exports "the latest revision" or a
 * version label, no chain is listed (the server still applies the resolved revision's chain).
 *
 * @param projectId The exported project (the Studio's `artifact`).
 * @param version The revision the Studio exports (UUID or label), or null for the latest.
 * @returns The chain state.
 */
export function useStoredOverlayChain(projectId: string, version: string | null | undefined): StoredOverlayChainState {
  const available = !!projectId && isRevisionId(version);
  const key = available ? `${projectId}/${version}` : null;
  /** The last settled read, and the revision it describes — shown only while it still matches. */
  const [settled, setSettled] = useState<{
    key: string;
    chain: VersionOverlayChain | null;
    error: string | null;
  } | null>(null);
  const [apply, setApply] = useState(true);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!key || !version) return;
    let cancelled = false;
    fetchVersionOverlays(projectId, version)
      .then((next) => {
        if (!cancelled) setSettled({ key, chain: next, error: null });
      })
      .catch((e: unknown) => {
        if (!cancelled) setSettled({ key, chain: null, error: e instanceof Error ? e.message : 'Request failed' });
      });
    return () => {
      cancelled = true;
    };
  }, [key, projectId, version, attempt]);

  const current = settled && settled.key === key ? settled : null;
  const chain = current?.chain ?? null;
  const error = current?.error ?? null;

  const saveToChain = useCallback(
    async (overlay: ExportStudioOverlay): Promise<string | null> => {
      if (!available || !version) return 'Choose a specific revision to save overlays to it.';
      try {
        await addVersionOverlay(projectId, version, {
          name: overlay.name,
          source: 'export-studio',
          document: overlay.document,
        });
        setAttempt((n) => n + 1);
        return null;
      } catch (e) {
        if (e instanceof VersionOverlaysError && e.code === CODE_VERSION_PUBLISHED) {
          return 'This revision is published, so its overlays are read-only.';
        }
        return e instanceof Error ? e.message : 'The overlay could not be saved.';
      }
    },
    [available, projectId, version]
  );

  return useMemo(
    () => ({ chain, error, apply, setApply, saveToChain, available }),
    [chain, error, apply, saveToChain, available]
  );
}
