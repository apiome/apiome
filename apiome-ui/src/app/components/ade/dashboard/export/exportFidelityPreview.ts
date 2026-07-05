/**
 * Fidelity preview envelope + warning-panel presentation helpers (MFX-6.2, #3856).
 *
 * The ExportDialog's fidelity warning panel renders from `POST /api/export/preview` — the
 * dry-run fidelity preview (MFX-2.5) that carries the full per-construct
 * `LossinessReport`, the user-facing advisory (MFX-2.4), and the coarse tier summary,
 * without emitting an artifact. This module mirrors those REST models field-for-field so
 * the response deserialises directly, and adds the pure presentation helpers the panel
 * needs: per-kind badge labels/classes, the worst-first report ordering, the preserved-%
 * ring geometry, and the "Export anyway" gate.
 *
 * Everything here is pure (no React, no fetch) so it can be unit-tested directly —
 * mirroring `./exportTargetCatalog.ts`.
 */

import type { ExportAdvisory } from '../../../../utils/export-advisory';
import type {
  ExportFidelityTier,
  ExportTargetDescriptor,
  TargetFidelitySummary,
} from './exportTargetCatalog';

/** The representational outcome of one construct (mirrors Python `LossinessKind`). */
export type LossinessKind = 'drop' | 'approx' | 'synth' | 'ok';

/** How much a loss matters (mirrors Python `LossinessSeverity`). */
export type LossinessSeverity = 'info' | 'warn' | 'critical';

/** One construct's fate when exported to the target (mirrors Python `LossItem`). */
export interface LossItem {
  /** Stable canonical construct key — the source path (e.g. `User.email`, `GET /pets/{id}`). */
  construct: string;
  /** Representational outcome: drop / approx / synth / ok. */
  kind: LossinessKind;
  /** How much the loss matters: info / warn / critical. */
  severity: LossinessSeverity;
  /** Human-readable explanation of what happened to the construct. */
  message: string;
  /** How the construct lands in the target when not dropped (e.g. `constraint → doc comment`). */
  target_mapping?: string | null;
}

/** The full per-construct lossiness report (mirrors Python `LossinessReport`). */
export interface LossinessReport {
  /** The loss items, in the server's deterministic canonical order. */
  items: LossItem[];
  /** Count of items per kind, zero-filled for every kind. */
  kind_counts: Record<string, number>;
  /** Count of items per severity, zero-filled for every severity. */
  severity_counts: Record<string, number>;
}

/** The full fidelity envelope for one (source, target) export (mirrors Python `ExportFidelity`). */
export interface ExportFidelityEnvelope {
  /** The resolved target emitter's descriptor. */
  target: ExportTargetDescriptor;
  /** The coarse tier / preserved-% summary, matching the `/api/export/targets` badge. */
  summary: TargetFidelitySummary;
  /** The full per-construct lossiness report (DROP/APPROX/SYNTH/OK + severity). */
  report: LossinessReport;
  /** The user-facing "may lose fidelity" advisory (MFX-2.4), rendered verbatim. */
  advisory: ExportAdvisory;
}

/** The `POST /api/export/preview` response (mirrors REST `ExportPreviewResponse`). */
export interface ExportPreviewResponse {
  /** The artifact (project) id the preview was computed for. */
  artifact: string;
  /** The version selector as requested (label, UUID, or null for latest). */
  version?: string | null;
  /** The resolved revision record id. */
  version_record_id: string;
  /** The resolved revision's version label, e.g. `"1.2.0"`. */
  version_label?: string | null;
  /** The full fidelity envelope (target + summary + report + advisory). */
  fidelity: ExportFidelityEnvelope;
}

/** Display rank per kind: loss reads before invention before clean (worst-first). */
const KIND_ORDER: Record<LossinessKind, number> = { drop: 0, approx: 1, synth: 2, ok: 3 };

/** Display rank per severity: worse severities read first. */
const SEVERITY_ORDER: Record<LossinessSeverity, number> = { critical: 0, warn: 1, info: 2 };

/** Human label for a loss kind, as printed on the report row badge (e.g. `DROP`). */
export function kindLabel(kind: LossinessKind): string {
  return kind.toUpperCase();
}

/**
 * CSS utility classes for a report row's kind badge. The palette matches the count chips
 * (`fidelityChips`): drop → red, approx → amber, synth → violet, ok → green.
 */
export function kindBadgeClass(kind: LossinessKind): string {
  switch (kind) {
    case 'drop':
      return 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300';
    case 'approx':
      return 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300';
    case 'synth':
      return 'bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300';
    case 'ok':
    default:
      return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300';
  }
}

/**
 * Order report items for the warning panel: worst-first by kind (drop → approx → synth → ok),
 * then by severity (critical → warn → info), then by construct key for a stable read. The
 * server's canonical order is by construct key; the panel instead leads with what the user
 * must review. Returns a new array — the input is not mutated.
 *
 * @param items The report items in any order.
 * @returns The items sorted worst-first.
 */
export function sortReportItemsWorstFirst(items: LossItem[]): LossItem[] {
  return [...items].sort(
    (a, b) =>
      KIND_ORDER[a.kind] - KIND_ORDER[b.kind] ||
      SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] ||
      a.construct.localeCompare(b.construct),
  );
}

/**
 * Whether the export needs the explicit "Export anyway" acknowledgement before the download
 * is allowed (MFX-6.2 acceptance: required when lossy, absent when clean). Gated on the tier
 * so it works from the cheap `/api/export/targets` summary alone — the gate never waits on
 * (or is defeated by a failure of) the detailed preview fetch.
 *
 * @param tier The target's fidelity tier for this source.
 * @returns True when the conversion is lossy (or types-only) and must be acknowledged.
 */
export function requiresExportAcknowledgement(tier: ExportFidelityTier): boolean {
  return tier !== 'lossless';
}

/** The SVG geometry for the preserved-% ring, precomputed so the component stays declarative. */
export interface RingGeometry {
  /** The ring circle's circumference (the `stroke-dasharray`). */
  circumference: number;
  /** The dash offset hiding the unpreserved share (the `stroke-dashoffset`). */
  dashOffset: number;
}

/**
 * Compute the preserved-% ring's stroke geometry for an SVG circle of the given radius.
 * The visible arc covers `percent`% of the circumference; the remainder is offset away.
 * Out-of-range percentages are clamped to 0–100.
 *
 * @param percent The preserved percentage, 0–100.
 * @param radius The ring circle's radius in SVG user units.
 * @returns The dash geometry to apply to the circle.
 */
export function ringGeometry(percent: number, radius: number): RingGeometry {
  const clamped = Math.min(100, Math.max(0, percent));
  const circumference = 2 * Math.PI * radius;
  return { circumference, dashOffset: circumference * (1 - clamped / 100) };
}

/**
 * CSS utility classes for the ring's progress stroke, keyed by fidelity tier so the ring
 * reads with the same palette as the tier badge: lossless → green, lossy → amber,
 * types-only → red.
 */
export function ringStrokeClass(tier: ExportFidelityTier): string {
  switch (tier) {
    case 'lossless':
      return 'stroke-emerald-500 dark:stroke-emerald-400';
    case 'lossy':
      return 'stroke-amber-500 dark:stroke-amber-400';
    case 'types-only':
    default:
      return 'stroke-rose-500 dark:stroke-rose-400';
  }
}
