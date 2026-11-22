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
  /**
   * True while the targets are listed but their fidelity badges are still being scored in the
   * background (a large source); every entry's `fidelity` is null until it turns false.
   */
  scoring: boolean;
  /** Why the badges could not be scored (the targets stay usable without them), else null. */
  scoringError: string | null;
}

/** How often a pending targets list is polled for its scores (ms). */
export const FIDELITY_POLL_MS = 1000;

/** Polls before giving up on the scores (about five minutes). */
const FIDELITY_POLL_LIMIT = 300;

/** The outcome of polling a deferred targets list (see {@link pollTargetFidelity}). */
export type FidelityPollOutcome =
  | { kind: 'ready'; targets: ExportTargetsResponse['targets'] }
  | { kind: 'failed'; error: string }
  /** The server no longer knows the job (expired, or another REST worker ran it): load inline. */
  | { kind: 'unknown' }
  | { kind: 'cancelled' };

/**
 * Poll `GET /api/export/targets/fidelity/{token}` until the scores are ready, scoring failed, the
 * job is unknown, or `isCancelled()` turns true.
 *
 * @param token The `fidelity_token` of a pending targets response.
 * @param isCancelled Stops polling (the screen closed or the source changed).
 * @param wait Sleeps between polls; injectable for tests.
 * @returns What polling ended with.
 */
export async function pollTargetFidelity(
  token: string,
  isCancelled: () => boolean,
  wait: (ms: number) => Promise<void> = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
): Promise<FidelityPollOutcome> {
  let networkFailures = 0;
  for (let attempt = 0; attempt < FIDELITY_POLL_LIMIT; attempt += 1) {
    await wait(FIDELITY_POLL_MS);
    if (isCancelled()) return { kind: 'cancelled' };
    let res: Response;
    try {
      res = await fetch(`/api/export/targets/fidelity/${encodeURIComponent(token)}`, {
        credentials: 'include',
      });
    } catch {
      networkFailures += 1;
      if (networkFailures >= 5) return { kind: 'failed', error: 'Could not reach the server to score the targets.' };
      continue;
    }
    const data = await res.json().catch(() => ({}));
    if (isCancelled()) return { kind: 'cancelled' };
    if (res.status === 404 && data?.code === 'fidelity-job-unknown') return { kind: 'unknown' };
    if (!res.ok || data?.success === false) {
      return {
        kind: 'failed',
        error: typeof data?.error === 'string' ? data.error : 'Could not score the export targets.',
      };
    }
    if (data?.status === 'ready' && Array.isArray(data.targets)) return { kind: 'ready', targets: data.targets };
    if (data?.status === 'failed') {
      return { kind: 'failed', error: typeof data.error === 'string' ? data.error : 'Could not score the export targets.' };
    }
  }
  return { kind: 'failed', error: 'Scoring the export targets is taking too long.' };
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
 * Fetches `GET /api/export/targets?artifact=…&version=…&fidelity=deferred` — every registered
 * emitter with its per-source fidelity badge (MFX-2.5) — while `enabled` is truthy. A large source
 * comes back unscored at once ({@link UseExportTargetsResult.scoring}); the hook polls for the badges
 * and swaps them in, so the cards appear in about a second and their badges follow (i.e. while the ExportDialog
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
  const [scoring, setScoring] = useState(false);
  const [scoringError, setScoringError] = useState<string | null>(null);
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
      setScoring(false);
      setScoringError(null);
      let failedStatus: number | null = null;
      let failedCode: string | null = null;
      let pending: { data: ExportTargetsResponse; token: string } | null = null;
      try {
        const params = new URLSearchParams({ artifact });
        if (version) params.set('version', version);
        // Deferred: a large source lists its targets at once and scores them in the background.
        params.set('fidelity', 'deferred');
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
        const listed = data as ExportTargetsResponse;
        setResponse(listed);
        setStale(null);
        if (listed.fidelity_status === 'pending' && listed.fidelity_token) {
          pending = { data: listed, token: listed.fidelity_token };
          setScoring(true);
        } else {
          saveLastTargets(artifact, version, listed);
        }
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
      if (pending) await finishScoring(pending.data, pending.token);
    };

    /** Poll for the scores of a pending list and swap them in (or fall back to an inline load). */
    const finishScoring = async (listed: ExportTargetsResponse, token: string) => {
      const outcome = await pollTargetFidelity(token, () => cancelled);
      if (cancelled || outcome.kind === 'cancelled') return;
      if (outcome.kind === 'ready') {
        const scored: ExportTargetsResponse = {
          ...listed,
          targets: outcome.targets,
          fidelity_status: 'ready',
          fidelity_token: null,
        };
        setResponse(scored);
        saveLastTargets(artifact, version, scored);
      } else if (outcome.kind === 'unknown') {
        // The job is gone (expired, or another REST worker ran it): ask for the scored list outright.
        try {
          const params = new URLSearchParams({ artifact });
          if (version) params.set('version', version);
          const res = await fetch(`/api/export/targets?${params.toString()}`, { credentials: 'include' });
          const data = await res.json().catch(() => ({}));
          if (cancelled) return;
          if (res.ok && data?.success !== false && Array.isArray(data?.targets)) {
            setResponse(data as ExportTargetsResponse);
            saveLastTargets(artifact, version, data as ExportTargetsResponse);
          } else {
            setScoringError(typeof data?.error === 'string' ? data.error : 'Could not score the export targets.');
          }
        } catch {
          if (!cancelled) setScoringError('Could not score the export targets.');
        }
      } else {
        setScoringError(outcome.error);
      }
      if (!cancelled) setScoring(false);
    };

    void load();

    return () => {
      cancelled = true;
    };
  }, [enabled, artifact, version, attempt]);

  return { response, loading, error, status, code, retry, stale, scoring, scoringError };
}
