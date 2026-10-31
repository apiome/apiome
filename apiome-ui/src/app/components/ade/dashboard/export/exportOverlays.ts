/**
 * Export Studio overlays (GVM-4.2, #5877) — the pure model behind the **Overlays** step.
 *
 * An overlay (OpenAPI Overlay 1.0 / 1.1 / 1.2) rewrites the version's OpenAPI document before the
 * export runs: partner-specific servers, descriptions or `x-` extensions without forking the
 * source. The Studio reads each uploaded file here, keeps the chain in the order the user set, and
 * sends it inline (`overlays: [{name, document}]`) on both the Verify call and the export job, so
 * the verdict, the snapshot the job is pinned to, and the artifact all describe the overlaid
 * document. What the overlays did comes back on `overlay` ({@link ExportOverlayReport}).
 */

import { parse as parseYaml } from 'yaml';

/** The most overlays one export applies (REST `MAX_EXPORT_OVERLAYS`). */
export const MAX_EXPORT_OVERLAYS = 10;

/** The largest overlay file accepted, in bytes (REST `MAX_EXPORT_OVERLAY_BYTES`, 1 MiB). */
export const MAX_EXPORT_OVERLAY_BYTES = 1024 * 1024;

/** One overlay in the Studio's chain — exactly the REST request entry. */
export interface ExportStudioOverlay {
  /** The overlay's label: the uploaded file's name. */
  name: string;
  /** The parsed Overlay document. */
  document: Record<string, unknown>;
}

/** One changed leaf (or the truncation row) of the overlay ledger. */
export interface ExportOverlayLedgerRow {
  pointer: string;
  kind: string;
  overlay: string | null;
  action_index: number | null;
  target: string | null;
  detail: string;
}

/** One overlay action that could not be applied. */
export interface ExportOverlayFinding {
  rule: string;
  severity: string;
  overlay: string;
  action_index: number;
  target: string;
  message: string;
}

/** What the overlays of one verify or export did (REST `ExportOverlayReport`). */
export interface ExportOverlayReport {
  applied: string[];
  ledger: ExportOverlayLedgerRow[];
  findings: ExportOverlayFinding[];
  changes: number;
  truncated: boolean;
}

/** The outcome of reading one overlay file. */
export type OverlayFileResult =
  | { ok: true; overlay: ExportStudioOverlay }
  | { ok: false; error: string };

/**
 * Read one uploaded overlay file (JSON or YAML) into a chain entry.
 *
 * @param name The file's name — the overlay's label.
 * @param text The file's text.
 * @param size The file's size in bytes (defaults to the text's UTF-8 length).
 * @returns The overlay, or the reason it cannot be used.
 */
export function parseOverlayFile(name: string, text: string, size?: number): OverlayFileResult {
  const bytes = size ?? new TextEncoder().encode(text).length;
  if (bytes > MAX_EXPORT_OVERLAY_BYTES) {
    return { ok: false, error: `${name} is larger than 1 MB, the most one overlay may be.` };
  }
  let document: unknown;
  try {
    document = parseYaml(text);
  } catch {
    return { ok: false, error: `${name} is not valid JSON or YAML.` };
  }
  if (!document || typeof document !== 'object' || Array.isArray(document)) {
    return { ok: false, error: `${name} is not an overlay: it has no \`overlay: 1.x\` line.` };
  }
  const marker = (document as Record<string, unknown>).overlay;
  if (typeof marker !== 'string' || !/^\d+(\.\d+)*$/.test(marker.trim())) {
    return { ok: false, error: `${name} is not an overlay: it has no \`overlay: 1.x\` line.` };
  }
  return { ok: true, overlay: { name, document: document as Record<string, unknown> } };
}

/**
 * Add overlays to the end of the chain, respecting {@link MAX_EXPORT_OVERLAYS}. A file whose name is
 * already in the chain replaces that entry in place (re-uploading an edited file keeps its order).
 *
 * @param chain The current chain.
 * @param added The overlays to add, in upload order.
 * @returns The new chain and how many were left out for the limit.
 */
export function addOverlays(
  chain: readonly ExportStudioOverlay[],
  added: readonly ExportStudioOverlay[],
): { chain: ExportStudioOverlay[]; dropped: number } {
  const next = [...chain];
  let dropped = 0;
  for (const overlay of added) {
    const existing = next.findIndex((entry) => entry.name === overlay.name);
    if (existing >= 0) next[existing] = overlay;
    else if (next.length < MAX_EXPORT_OVERLAYS) next.push(overlay);
    else dropped += 1;
  }
  return { chain: next, dropped };
}

/**
 * Move one overlay up or down the chain. Out-of-range moves return the chain unchanged.
 *
 * @param chain The current chain.
 * @param index The overlay to move.
 * @param delta -1 to apply it earlier, +1 to apply it later.
 * @returns The reordered chain.
 */
export function moveOverlay(
  chain: readonly ExportStudioOverlay[],
  index: number,
  delta: -1 | 1,
): ExportStudioOverlay[] {
  const target = index + delta;
  if (index < 0 || index >= chain.length || target < 0 || target >= chain.length) return [...chain];
  const next = [...chain];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

/**
 * The `overlays` request field for a chain: the chain itself, or null when empty (so an export
 * without overlays sends exactly what it sent before overlays existed).
 */
export function overlaysRequestField(
  chain: readonly ExportStudioOverlay[] | null | undefined,
): ExportStudioOverlay[] | null {
  return chain && chain.length > 0 ? [...chain] : null;
}

/** How many actions an overlay declares, for the chain row's caption. */
export function overlayActionCount(overlay: ExportStudioOverlay): number {
  const actions = overlay.document.actions;
  return Array.isArray(actions) ? actions.length : 0;
}

/** The overlay's own title (`info.title`), when it has one. */
export function overlayTitle(overlay: ExportStudioOverlay): string | null {
  const info = overlay.document.info;
  if (!info || typeof info !== 'object') return null;
  const title = (info as Record<string, unknown>).title;
  return typeof title === 'string' && title.trim() ? title.trim() : null;
}

/** Plain words for a ledger row's change kind. */
export const OVERLAY_CHANGE_LABEL: Record<string, string> = {
  set: 'Added',
  replaced: 'Replaced',
  appended: 'Appended',
  removed: 'Removed',
};

/**
 * One sentence summarising a report, for the panel heading.
 *
 * @param report The report from a verify or a completed job.
 * @returns e.g. `2 overlays changed 5 values · 1 action matched nothing`.
 */
export function overlayReportSummary(report: ExportOverlayReport): string {
  const overlays = `${report.applied.length} ${report.applied.length === 1 ? 'overlay' : 'overlays'}`;
  const values = `${report.changes} ${report.changes === 1 ? 'value' : 'values'}`;
  const parts = [`${overlays} changed ${values}`];
  if (report.findings.length > 0) {
    const n = report.findings.length;
    parts.push(`${n} ${n === 1 ? 'action' : 'actions'} could not be applied`);
  }
  return parts.join(' · ');
}
