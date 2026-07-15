/**
 * Privacy-safe projection metrics client (EFP-3.2, #4817).
 *
 * Posts a whitelisted `{ kind, page_total?, reason_category? }` payload to
 * `/api/export/projection-metrics`. Never send construct labels, native ids,
 * source locations, or free-text explanations — the REST handler rejects
 * unknown fields and unknown reason categories.
 */

export type ProjectionMetricKind =
  | 'preview_failure'
  | 'stale_acknowledgement'
  | 'evidence_page'
  | 'aggregation_used'
  | 'documentation_link_available'
  | 'documentation_link_missing';

export interface ProjectionMetricPayload {
  kind: ProjectionMetricKind;
  page_total?: number;
  reason_category?: string;
}

/**
 * Record one privacy-safe projection metric. Failures are swallowed — telemetry
 * must never block the export UI.
 *
 * @param payload Whitelisted kind + optional integer/reason fields only.
 */
export async function trackProjectionMetric(payload: ProjectionMetricPayload): Promise<void> {
  try {
    await fetch('/api/export/projection-metrics', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    });
  } catch {
    // Best-effort; ignore transport errors.
  }
}
