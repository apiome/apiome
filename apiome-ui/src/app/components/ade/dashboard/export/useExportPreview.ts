'use client';

import { useEffect, useState } from 'react';
import type { ExportPreviewResponse } from './exportFidelityPreview';

export interface UseExportPreviewResult {
  /** The dry-run preview once loaded (full report + advisory), else null. */
  preview: ExportPreviewResponse | null;
  loading: boolean;
  /**
   * Load error. The warning panel surfaces it and falls back to the coarse summary — the
   * "Export anyway" gate never depends on this fetch succeeding.
   */
  error: string | null;
}

/**
 * Load the dry-run fidelity preview for one (source, target) export (MFX-6.2, #3856).
 *
 * Fetches `POST /api/export/preview` — the full fidelity envelope (per-construct report +
 * user-facing advisory, MFX-2.5) computed without emitting an artifact — while `enabled` is
 * truthy (i.e. while the ExportDialog's Fidelity step is showing). Re-fetches when the
 * source or target changes. Mirrors `./useExportTargets`.
 *
 * @param enabled Only fetch while truthy (e.g. while the Fidelity step is showing).
 * @param artifact The artifact (project) id to export.
 * @param version The revision to measure (UUID or label); the latest revision when null.
 * @param target The chosen target emitter key (e.g. `proto`); no fetch while null.
 */
export function useExportPreview(
  enabled: boolean,
  artifact: string,
  version: string | null | undefined,
  target: string | null,
): UseExportPreviewResult {
  const [preview, setPreview] = useState<ExportPreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled || !artifact || !target) return;

    let cancelled = false;

    // All state mutations live inside this async helper (not the effect body) so we never
    // call setState synchronously during the effect — which would trigger cascading renders.
    const load = async () => {
      setLoading(true);
      setError(null);
      setPreview(null);
      try {
        const res = await fetch('/api/export/preview', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ artifact, version: version || null, target }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data?.success === false) {
          throw new Error(
            typeof data?.error === 'string' ? data.error : 'Could not load the fidelity report.',
          );
        }
        if (cancelled) return;
        setPreview(data as ExportPreviewResponse);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : 'Could not load the fidelity report.');
        setPreview(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();

    return () => {
      cancelled = true;
    };
  }, [enabled, artifact, version, target]);

  return { preview, loading, error };
}
