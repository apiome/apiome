'use client';

import { useCallback, useEffect, useState } from 'react';
import type { ExportTargetsResponse } from './exportTargetCatalog';

export interface UseExportTargetsResult {
  /** The targets response once loaded (targets + resolved source coordinates), else null. */
  response: ExportTargetsResponse | null;
  loading: boolean;
  /** Load error; the dialog surfaces it with {@link UseExportTargetsResult.retry}. */
  error: string | null;
  /**
   * The HTTP status of a failed load (null while ok/loading). The Export Studio uses it to explain
   * a stale deep link — a deleted version (404) or a source outside the viewer's tenant (403) —
   * instead of repeating the generic loader message (MFX-41.4).
   */
  status: number | null;
  /**
   * The typed refusal code of a failed load (E1-6), e.g. `source-not-captured` — the source has
   * nothing to export from, so the screen offers Re-import instead of a retry. Null otherwise.
   */
  code: string | null;
  /** Read the targets again after a failed load (RC6-H3, #6210). */
  retry: () => void;
  /**
   * Set when the registry could not be reached and {@link UseExportTargetsResult.response} is the
   * last list this source loaded in this browser session (MFX-46.5) — the screen says so and offers
   * {@link UseExportTargetsResult.retry}. `savedAt` is when that list loaded (ISO 8601). Null otherwise.
   */
  stale: { savedAt: string } | null;
}

/** sessionStorage key prefix of the last good targets list per source (MFX-46.5). */
export const LAST_TARGETS_KEY = 'apiome.export.lastTargets';

/** The storage key of one source's last good targets list. */
export function lastTargetsKey(artifact: string, version?: string | null): string {
  return `${LAST_TARGETS_KEY}:${artifact}:${version ?? ''}`;
}

/** Remember a source's targets list for the session (best-effort: storage may be unavailable). */
export function saveLastTargets(artifact: string, version: string | null | undefined, response: ExportTargetsResponse): void {
  try {
    window.sessionStorage.setItem(
      lastTargetsKey(artifact, version),
      JSON.stringify({ savedAt: new Date().toISOString(), response }),
    );
  } catch {
    // Storage full or blocked: the fallback is a convenience, never required.
  }
}

/**
 * A source's last good targets list from this session, or null.
 *
 * @param artifact The artifact id.
 * @param version The version selector.
 * @returns `{ savedAt, response }`, or null when none was kept (or it cannot be read).
 */
export function readLastTargets(
  artifact: string,
  version?: string | null,
): { savedAt: string; response: ExportTargetsResponse } | null {
  try {
    const raw = window.sessionStorage.getItem(lastTargetsKey(artifact, version));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { savedAt?: unknown; response?: ExportTargetsResponse };
    if (typeof parsed?.savedAt !== 'string' || !Array.isArray(parsed.response?.targets)) return null;
    return { savedAt: parsed.savedAt, response: parsed.response as ExportTargetsResponse };
  } catch {
    return null;
  }
}

/**
 * Whether a failed load means the registry was unreachable (no answer, or a 5xx) rather than a refusal
 * about this source (4xx, or a typed code) — only then is the last good list shown instead.
 */
export function isRegistryUnreachable(status: number | null, code: string | null): boolean {
  return code === null && (status === null || status >= 500);
}

/**
 * Load the export-target list for one source revision (MFX-6.1, #3855).
 *
 * Fetches `GET /api/export/targets?artifact=…&version=…` — every registered emitter with its
 * per-source fidelity badge (MFX-2.5) — while `enabled` is truthy (i.e. while the ExportDialog
 * is open). Mirrors `../useImportSources`: there are no built-in export cards, so the first load shows
 * a loading state, but once a source's list has loaded it is kept for the browser session, and when the
 * registry is unreachable later that list is returned with {@link UseExportTargetsResult.stale} set
 * (MFX-46.5) — the screen stays usable, says the list may be out of date, and offers a retry.
 *
 * @param enabled Only fetch while truthy (e.g. while the dialog is open).
 * @param artifact The artifact (project) id to export.
 * @param version The revision to measure (UUID or label); the latest revision when omitted.
 */
export function useExportTargets(
  enabled: boolean,
  artifact: string,
  version?: string | null,
): UseExportTargetsResult {
  const [response, setResponse] = useState<ExportTargetsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<number | null>(null);
  const [code, setCode] = useState<string | null>(null);
  const [stale, setStale] = useState<{ savedAt: string } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt((count) => count + 1), []);

  useEffect(() => {
    if (!enabled || !artifact) return;

    let cancelled = false;

    // All state mutations live inside this async helper (not the effect body) so we never call
    // setState synchronously during the effect — which would trigger cascading renders.
    const load = async () => {
      setLoading(true);
      setError(null);
      setStatus(null);
      setCode(null);
      let failedStatus: number | null = null;
      let failedCode: string | null = null;
      try {
        const params = new URLSearchParams({ artifact });
        if (version) params.set('version', version);
        const res = await fetch(`/api/export/targets?${params.toString()}`, {
          credentials: 'include',
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data?.success === false) {
          failedStatus = typeof res.status === 'number' ? res.status : null;
          failedCode = typeof data?.code === 'string' ? data.code : null;
          if (!cancelled) {
            setStatus(failedStatus);
            setCode(failedCode);
          }
          throw new Error(
            typeof data?.error === 'string' ? data.error : 'Could not load export targets.',
          );
        }
        if (cancelled) return;
        setResponse(data as ExportTargetsResponse);
        setStale(null);
        saveLastTargets(artifact, version, data as ExportTargetsResponse);
      } catch (e) {
        if (cancelled) return;
        const kept = isRegistryUnreachable(failedStatus, failedCode) ? readLastTargets(artifact, version) : null;
        if (kept) {
          // MFX-46.5: the registry is down but this source loaded earlier — keep the screen usable.
          setResponse(kept.response);
          setStale({ savedAt: kept.savedAt });
          setError(null);
          setStatus(null);
        } else {
          setError(e instanceof Error ? e.message : 'Could not load export targets.');
          setResponse(null);
          setStale(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();

    return () => {
      cancelled = true;
    };
  }, [enabled, artifact, version, attempt]);

  return { response, loading, error, status, code, retry, stale };
}
