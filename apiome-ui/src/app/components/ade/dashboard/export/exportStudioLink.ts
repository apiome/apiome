/**
 * Export Studio deep-link contract (MFX-41.1, #4348).
 *
 * The Studio route `…/ade/dashboard/export/studio` is always scoped to a source — it is never a
 * bare global screen. This module is the single place that builds and reads that scoped URL, so
 * the ExportDialog's "Open in Export Studio" escalation and the Studio page agree on the query
 * parameters:
 *  - `artifact` (required) — the artifact (project / catalog-item) id to export;
 *  - `version` — the revision selector (UUID or label); the latest revision when omitted;
 *  - `label` — a human name for the source, shown in the header (falls back to the id);
 *  - `target` — a pre-selected emitter key carried from the dialog's current selection.
 */

/** The base path of the Export Studio route (tenant-scoped by the dashboard layout). */
export const EXPORT_STUDIO_PATH = '/ade/dashboard/export/studio';

/** The scoped source the Studio opens against, carried in the deep link. */
export interface ExportStudioScope {
  /** The artifact (project / catalog-item) id to export. Required — no bare global screen. */
  artifact: string;
  /** The revision selector (UUID or label); the latest revision when null/undefined. */
  version?: string | null;
  /** A human name for the source, shown in the header. */
  label?: string | null;
  /** A pre-selected emitter key (the dialog's current target selection), when escalating. */
  target?: string | null;
}

/**
 * Build the Export Studio href for a scoped source. Empty/undefined optional fields are omitted
 * so the URL only carries what was actually selected.
 *
 * @param scope The source (and optional pre-selected target) to open the Studio against.
 * @returns A root-relative URL, e.g. `/ade/dashboard/export/studio?artifact=proj-1&target=proto`.
 */
export function exportStudioHref(scope: ExportStudioScope): string {
  const params = new URLSearchParams({ artifact: scope.artifact });
  if (scope.version) params.set('version', scope.version);
  if (scope.label) params.set('label', scope.label);
  if (scope.target) params.set('target', scope.target);
  return `${EXPORT_STUDIO_PATH}?${params.toString()}`;
}
