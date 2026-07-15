'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ProjectionManifestSummary } from './exportFidelityPreview';
import {
  evidencePageIssues,
  type ExportProjectionEvidenceResponse,
  type ProjectionEdge,
  type ProjectionNode,
} from './projectionEvidence';

/** Evidence rows requested per page (within the server's hard cap of 500). */
export const EVIDENCE_PAGE_LIMIT = 200;

/** Pages fetched per window — one auto-load walks at most this many cursors. */
export const EVIDENCE_PAGES_PER_WINDOW = 5;

/**
 * Documented initial-render row budget: first auto-load window ceiling
 * `EVIDENCE_PAGE_LIMIT × EVIDENCE_PAGES_PER_WINDOW`). Aggregation at the documented
 * graph threshold (48) further bounds DOM work (EFP-3.2).
 */
export const EVIDENCE_INITIAL_RENDER_ROW_BUDGET =
  EVIDENCE_PAGE_LIMIT * EVIDENCE_PAGES_PER_WINDOW;

export interface UseProjectionEvidenceResult {
  /** The snapshot summary from the first page (hash, provenance, full status counts). */
  summary: ProjectionManifestSummary | null;
  /** Every node loaded so far, deduplicated by id. */
  nodes: ProjectionNode[];
  /** Every edge loaded so far, in server (canonical) order. */
  edges: ProjectionEdge[];
  /** True when the server withheld source-native evidence values. */
  redacted: boolean;
  /** Whether a page walk is in flight. */
  loading: boolean;
  /** Fetch/transport error; the panel degrades to the envelope summary. */
  error: string | null;
  /**
   * Integrity problems found in a page (`evidencePageIssues` + cross-page snapshot
   * identity). Non-empty means the evidence must be refused, not partially rendered.
   */
  integrityIssues: string[];
  /** True once every evidence page has been loaded (no cursor remains). */
  complete: boolean;
  /** Continue the cursor walk for another window; no-op while loading or when complete. */
  loadMore: () => void;
}

/**
 * Load the bounded projection evidence behind one configured export (EFP-2.2, #4814).
 *
 * Walks `POST /api/export/projection-evidence` (EFP-2.1) cursor pages for the given
 * `(artifact, version, target, options)` — the same triple the surface's preview/verify used,
 * so the evidence describes exactly the snapshot whose summary the fidelity envelope embeds.
 * Fetches up to {@link EVIDENCE_PAGES_PER_WINDOW} pages per window and exposes
 * {@link UseProjectionEvidenceResult.loadMore} to continue, so a huge manifest cannot stall
 * the Fidelity step; the full status counts always come from the summary, so nothing is
 * silently hidden while more pages remain.
 *
 * Every page is integrity-checked before it is trusted (`evidencePageIssues`), and every
 * subsequent page must carry the first page's `manifest_hash` — a mid-walk snapshot change
 * (the source was re-imported) refuses the evidence rather than mixing two snapshots.
 *
 * @param enabled Only fetch while truthy (the surface's projection section is showing).
 * @param artifact The artifact (project) id to export.
 * @param version The revision (UUID or label); the latest revision when null.
 * @param target The chosen target emitter key; no fetch while null.
 * @param options The changed (non-default) option overrides the surface previews with,
 *   or null — must match the preview/verify request for snapshot identity.
 */
export function useProjectionEvidence(
  enabled: boolean,
  artifact: string,
  version: string | null | undefined,
  target: string | null,
  options: Record<string, unknown> | null,
): UseProjectionEvidenceResult {
  const [summary, setSummary] = useState<ProjectionManifestSummary | null>(null);
  const [nodes, setNodes] = useState<ProjectionNode[]>([]);
  const [edges, setEdges] = useState<ProjectionEdge[]>([]);
  const [redacted, setRedacted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [integrityIssues, setIntegrityIssues] = useState<string[]>([]);
  const [complete, setComplete] = useState(false);

  // The walk's continuation cursor + accumulated node ids live in refs: they are fetch
  // bookkeeping, not render state, and must survive between windows without re-rendering.
  const cursorRef = useRef<string | null>(null);
  const seenNodeIdsRef = useRef<Set<string>>(new Set());
  const firstHashRef = useRef<string | null>(null);
  // Monotonic token: a config change or unmount invalidates any in-flight walk.
  const walkToken = useRef(0);

  // A stable key for the options object so the effect re-runs on content, not identity.
  const optionsKey = useMemo(() => JSON.stringify(options ?? null), [options]);

  /** Walk up to one window of pages from the current cursor, accumulating results. */
  const fetchWindow = useCallback(
    async (token: number, startCursor: string | null) => {
      setLoading(true);
      setError(null);
      try {
        let cursor = startCursor;
        for (let pageIndex = 0; pageIndex < EVIDENCE_PAGES_PER_WINDOW; pageIndex += 1) {
          const res = await fetch('/api/export/projection-evidence', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({
              artifact,
              version: version || null,
              target,
              options: options ?? null,
              cursor,
              limit: EVIDENCE_PAGE_LIMIT,
            }),
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok || data?.success === false) {
            throw new Error(
              typeof data?.error === 'string'
                ? data.error
                : 'Could not load the projection evidence.',
            );
          }
          if (token !== walkToken.current) return;

          const response = data as ExportProjectionEvidenceResponse;
          const issues = evidencePageIssues(response.page);
          if (firstHashRef.current == null) {
            firstHashRef.current = response.page.manifest_hash;
          } else if (response.page.manifest_hash !== firstHashRef.current) {
            issues.push(
              `page snapshot '${response.page.manifest_hash}' does not match the walk's ` +
                `snapshot '${firstHashRef.current}' — the source changed mid-walk`,
            );
          }
          if (issues.length > 0) {
            // An untrusted page refuses the whole evidence view — never partially render.
            setIntegrityIssues(issues);
            setComplete(false);
            return;
          }

          const freshNodes = response.page.nodes.filter(
            (node) => !seenNodeIdsRef.current.has(node.id),
          );
          for (const node of freshNodes) seenNodeIdsRef.current.add(node.id);
          setSummary((current) => current ?? response.summary);
          setRedacted((current) => current || response.redacted);
          if (freshNodes.length > 0) setNodes((current) => [...current, ...freshNodes]);
          if (response.page.edges.length > 0) {
            setEdges((current) => [...current, ...response.page.edges]);
          }

          cursor = response.page.next_cursor ?? null;
          cursorRef.current = cursor;
          if (cursor == null) {
            setComplete(true);
            return;
          }
        }
      } catch (e) {
        if (token !== walkToken.current) return;
        setError(e instanceof Error ? e.message : 'Could not load the projection evidence.');
      } finally {
        if (token === walkToken.current) setLoading(false);
      }
    },
    [artifact, version, target, options],
  );

  useEffect(() => {
    if (!enabled || !artifact || !target) return;
    const token = ++walkToken.current;
    // A new configuration is a new walk: reset the accumulation before the first window.
    cursorRef.current = null;
    seenNodeIdsRef.current = new Set();
    firstHashRef.current = null;
    setSummary(null);
    setNodes([]);
    setEdges([]);
    setRedacted(false);
    setIntegrityIssues([]);
    setComplete(false);
    void fetchWindow(token, null);
    return () => {
      // Invalidate the in-flight walk so a late page cannot settle stale state.
      walkToken.current += 1;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- optionsKey stands in for `options` content
  }, [enabled, artifact, version, target, optionsKey]);

  const loadMore = useCallback(() => {
    if (loading || complete || integrityIssues.length > 0 || cursorRef.current == null) return;
    void fetchWindow(walkToken.current, cursorRef.current);
  }, [loading, complete, integrityIssues, fetchWindow]);

  return { summary, nodes, edges, redacted, loading, error, integrityIssues, complete, loadMore };
}
