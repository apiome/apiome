'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  validateRegistrySnapshot,
  type CapabilityRegistrySnapshot,
  type ProjectionReasonCode,
  type ReasonExplanation,
} from './capabilityRegistry';

/** What the hook exposes: the reviewed explanation per reason code + registry identity. */
export interface UseCapabilityReasonsResult {
  /** Reviewed explanation (category label, remediation, docs applicability) per reason code. */
  reasons: ReadonlyMap<ProjectionReasonCode, ReasonExplanation>;
  /** The registry contract version, when loaded. */
  registryVersion: string | null;
  /** When the registry's links/explanations were last reviewed, when loaded. */
  reviewDate: string | null;
}

const EMPTY_REASONS: ReadonlyMap<ProjectionReasonCode, ReasonExplanation> = new Map();

/**
 * The registry is static reference data (the same for every source and every drawer), so one
 * fetch per page load is shared by every consumer via this module-level cache. `null` records
 * a settled failure — consumers degrade to registry-less rendering; a page reload retries.
 */
let cachedSnapshot: CapabilityRegistrySnapshot | null = null;
let pendingFetch: Promise<CapabilityRegistrySnapshot | null> | null = null;

/** Reset the module cache — test hook only. */
export function resetCapabilityReasonsCache(): void {
  cachedSnapshot = null;
  pendingFetch = null;
}

/** Fetch + contract-validate the registry snapshot; null on any failure or contract issue. */
async function fetchRegistrySnapshot(): Promise<CapabilityRegistrySnapshot | null> {
  try {
    const res = await fetch('/api/export/capability-registry', { credentials: 'include' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data?.success === false) return null;
    const snapshot = data as CapabilityRegistrySnapshot;
    if (!Array.isArray(snapshot.reasons) || !Array.isArray(snapshot.destinations)) return null;
    // An untrustworthy registry (unknown reason codes, off-allowlist links) is refused
    // whole — the drawer then renders without registry data rather than rendering bad data.
    if (validateRegistrySnapshot(snapshot).length > 0) return null;
    return snapshot;
  } catch {
    return null;
  }
}

/**
 * Load the destination capability registry's reviewed reason explanations (EFP-2.3, #4815).
 *
 * The evidence drawer prints each loss's cause category, reviewed remediation guidance, and
 * registry provenance from `GET /api/export/capability-registry` (EFP-1.2). The registry is
 * version-static reference data, so the fetch happens once per page load and is shared by
 * every drawer via a module cache. The result is contract-validated before it is trusted
 * (`validateRegistrySnapshot`); a failed fetch or an invalid snapshot yields the empty map
 * and the drawer degrades gracefully — the registry is explanatory, never a gate.
 *
 * @param enabled Only fetch while truthy (the surface's evidence view is showing).
 */
export function useCapabilityReasons(enabled: boolean): UseCapabilityReasonsResult {
  const [snapshot, setSnapshot] = useState<CapabilityRegistrySnapshot | null>(cachedSnapshot);

  useEffect(() => {
    if (!enabled || cachedSnapshot) return;
    let cancelled = false;
    pendingFetch ??= fetchRegistrySnapshot().then((result) => {
      cachedSnapshot = result;
      return result;
    });
    void pendingFetch.then((result) => {
      if (!cancelled && result) setSnapshot(result);
    });
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  const reasons = useMemo<ReadonlyMap<ProjectionReasonCode, ReasonExplanation>>(
    () =>
      snapshot
        ? new Map(snapshot.reasons.map((explanation) => [explanation.reason, explanation]))
        : EMPTY_REASONS,
    [snapshot],
  );

  return {
    reasons,
    registryVersion: snapshot?.version ?? null,
    reviewDate: snapshot?.review_date ?? null,
  };
}
