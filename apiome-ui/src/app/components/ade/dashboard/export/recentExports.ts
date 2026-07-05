/**
 * Browser-local recent exports for one project version (MFX-6.5, #3859).
 *
 * The version view shows a "Recent exports" list (target + fidelity % + relative time, per the
 * export mockup) next to the fidelity pre-summary. Exports are recorded client-side when the
 * ExportDialog emits a document, keyed per artifact + version, so the list is scoped to the
 * version being viewed. Storage conventions mirror `../../../utils/git-import-recent-specs.ts`.
 *
 * This is the interim per-version store: the tenant-wide, queryable export history lives on the
 * REST side later (MFX-46.1); when that lands this module's readers swap to the API without
 * changing the panel.
 */

import type { ExportFidelityTier } from './exportTargetCatalog';

/** One recorded export of a specific artifact version. */
export type RecentExport = {
  /** Registry key of the target emitter, e.g. `"proto"`. */
  targetKey: string;
  /** Human label of the target, shown as the row title, e.g. `"Protobuf"`. */
  targetLabel: string;
  /** Fidelity tier of the conversion at export time (MFX-2.5). */
  tier: ExportFidelityTier;
  /** Share of constructs carried faithfully, 0–100, at export time. */
  preservedPercent: number;
  /** Filename of the emitted document. */
  filename: string;
  /** When the export happened (epoch milliseconds). */
  exportedAt: number;
};

/** A recent-export record minus the timestamp, which `recordRecentExport` stamps itself. */
export type RecentExportInput = Omit<RecentExport, 'exportedAt'>;

const STORAGE_PREFIX = 'apiome:recent-exports:';

/** How many exports the per-version list keeps (newest first). */
export const MAX_RECENT_EXPORTS = 8;

const FIDELITY_TIERS: readonly ExportFidelityTier[] = ['lossless', 'lossy', 'types-only'];

/**
 * The localStorage key for one artifact version's recent exports.
 *
 * @param artifact The artifact (project) id the exports belong to.
 * @param version The version selector the exports were made for (revision UUID or label);
 *   a missing selector means "latest" and gets its own bucket.
 * @returns The namespaced storage key.
 */
export function recentExportsStorageKey(
  artifact: string,
  version: string | null | undefined,
): string {
  return `${STORAGE_PREFIX}${artifact}:${version || 'latest'}`;
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/**
 * Runtime shape check for one stored entry — malformed or foreign values are dropped on load
 * so a corrupted storage bucket can never break the panel.
 *
 * @param v Any parsed JSON value.
 * @returns Whether `v` is a well-formed {@link RecentExport}.
 */
export function isRecentExport(v: unknown): v is RecentExport {
  if (!isPlainObject(v)) return false;
  return (
    typeof v.targetKey === 'string' &&
    v.targetKey.length > 0 &&
    typeof v.targetLabel === 'string' &&
    v.targetLabel.length > 0 &&
    FIDELITY_TIERS.includes(v.tier as ExportFidelityTier) &&
    typeof v.preservedPercent === 'number' &&
    Number.isFinite(v.preservedPercent) &&
    typeof v.filename === 'string' &&
    typeof v.exportedAt === 'number' &&
    Number.isFinite(v.exportedAt)
  );
}

/**
 * Load the recent exports recorded for one artifact version, newest first.
 * Safe everywhere: returns `[]` on the server, on parse errors, and on foreign data.
 *
 * @param artifact The artifact (project) id.
 * @param version The version selector (see {@link recentExportsStorageKey}).
 * @returns Well-formed entries sorted by `exportedAt` descending.
 */
export function loadRecentExports(
  artifact: string,
  version: string | null | undefined,
): RecentExport[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem(recentExportsStorageKey(artifact, version));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isRecentExport).sort((a, b) => b.exportedAt - a.exportedAt);
  } catch {
    return [];
  }
}

/**
 * Persist a version's recent-export list verbatim.
 *
 * @param artifact The artifact (project) id.
 * @param version The version selector.
 * @param items The full list to store.
 * @returns Whether the write succeeded (quota errors and SSR return `false`).
 */
export function saveRecentExports(
  artifact: string,
  version: string | null | undefined,
  items: RecentExport[],
): boolean {
  if (typeof window === 'undefined') return false;
  try {
    localStorage.setItem(recentExportsStorageKey(artifact, version), JSON.stringify(items));
    return true;
  } catch {
    return false;
  }
}

/**
 * Record one export at the head of the version's list, capped at {@link MAX_RECENT_EXPORTS}.
 * Every export is its own event — re-exporting the same target adds a new row rather than
 * bumping an old one, since each run may have different options and fidelity.
 *
 * @param artifact The artifact (project) id that was exported.
 * @param version The version selector that was exported.
 * @param entry What was exported (timestamp is stamped here).
 * @returns Whether the write persisted, plus the updated list (newest first).
 */
export function recordRecentExport(
  artifact: string,
  version: string | null | undefined,
  entry: RecentExportInput,
): { persisted: boolean; items: RecentExport[] } {
  const newEntry: RecentExport = { ...entry, exportedAt: Date.now() };
  const next = [newEntry, ...loadRecentExports(artifact, version)].slice(0, MAX_RECENT_EXPORTS);
  const persisted = saveRecentExports(artifact, version, next);
  return { persisted, items: next };
}

/**
 * The row's fidelity badge text, per the mockup: `lossless` for a clean conversion, else the
 * preserved share as `N% fidelity`.
 *
 * @param entry The export's tier and preserved-%.
 * @returns The badge label.
 */
export function fidelityBadgeLabel(
  entry: Pick<RecentExport, 'tier' | 'preservedPercent'>,
): string {
  return entry.tier === 'lossless' ? 'lossless' : `${entry.preservedPercent}% fidelity`;
}
