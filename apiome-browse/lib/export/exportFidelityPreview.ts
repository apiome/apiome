/**
 * Fidelity preview envelope + warning-panel presentation helpers (MFX-7.2, #3861).
 *
 * Mirrors the authenticated ADE's `exportFidelityPreview.ts` against the public
 * `POST …/export/preview` response. Pure helpers only — no React, no fetch — so they
 * are unit-tested under the browse Vitest setup.
 */

import type { ExportAdvisory } from './export-advisory';
import type {
  ExportFidelityTier,
  ExportTargetDescriptor,
  TargetFidelitySummary,
} from './publicExport';

/** Representational outcome of one construct (mirrors Python `LossinessKind`). */
export type LossinessKind = 'drop' | 'approx' | 'synth' | 'ok';

/** How much a loss matters (mirrors Python `LossinessSeverity`). */
export type LossinessSeverity = 'info' | 'warn' | 'critical';

/** One construct's fate when exported to the target (mirrors Python `LossItem`). */
export interface LossItem {
  construct: string;
  kind: LossinessKind;
  severity: LossinessSeverity;
  message: string;
  target_mapping?: string | null;
}

/** Full per-construct lossiness report (mirrors Python `LossinessReport`). */
export interface LossinessReport {
  items: LossItem[];
  kind_counts: Record<string, number>;
  severity_counts: Record<string, number>;
}

/** Full fidelity envelope for one (source, target) export (mirrors Python `ExportFidelity`). */
export interface ExportFidelityEnvelope {
  target: ExportTargetDescriptor;
  summary: TargetFidelitySummary;
  report: LossinessReport;
  advisory: ExportAdvisory;
}

/** `POST …/export/preview` response on the public browse surface. */
export interface PublicExportPreviewResponse {
  tenant_slug: string;
  project_slug: string;
  version_slug: string;
  version_record_id: string;
  version_label?: string | null;
  fidelity: ExportFidelityEnvelope;
}

/** Count chip for the preserved-% ring row (`N dropped · N approximated · … · N clean`). */
export interface FidelityChip {
  key: 'dropped' | 'approximated' | 'synthesized' | 'preserved';
  label: string;
  count: number;
  className: string;
}

const KIND_ORDER: Record<LossinessKind, number> = { drop: 0, approx: 1, synth: 2, ok: 3 };
const SEVERITY_ORDER: Record<LossinessSeverity, number> = { critical: 0, warn: 1, info: 2 };

/** Human label for a loss kind badge (e.g. `DROP`). */
export function kindLabel(kind: LossinessKind): string {
  return kind.toUpperCase();
}

/** CSS classes for a report row's kind badge. */
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

/** Order report items worst-first for the expandable panel. */
export function sortReportItemsWorstFirst(items: LossItem[]): LossItem[] {
  return [...items].sort(
    (a, b) =>
      KIND_ORDER[a.kind] - KIND_ORDER[b.kind] ||
      SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] ||
      a.construct.localeCompare(b.construct)
  );
}

/** SVG geometry for the preserved-% ring. */
export interface RingGeometry {
  circumference: number;
  dashOffset: number;
}

/** Compute ring stroke geometry; clamps percent to 0–100. */
export function ringGeometry(percent: number, radius: number): RingGeometry {
  const clamped = Math.min(100, Math.max(0, percent));
  const circumference = 2 * Math.PI * radius;
  return { circumference, dashOffset: circumference * (1 - clamped / 100) };
}

/** CSS classes for the ring progress stroke, keyed by fidelity tier. */
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

/**
 * Break a target's fidelity summary into count chips — `N dropped · N approximated ·
 * N synthesized · N clean` — dropping empty loss buckets. The `clean` chip always renders.
 */
export function fidelityChips(fidelity: TargetFidelitySummary): FidelityChip[] {
  const lossChips: FidelityChip[] = [
    {
      key: 'dropped',
      label: 'dropped',
      count: fidelity.dropped,
      className: 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300',
    },
    {
      key: 'approximated',
      label: 'approximated',
      count: fidelity.approximated,
      className: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
    },
    {
      key: 'synthesized',
      label: 'synthesized',
      count: fidelity.synthesized,
      className: 'bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300',
    },
  ];
  const chips = lossChips.filter((chip) => chip.count > 0);
  chips.push({
    key: 'preserved',
    label: 'clean',
    count: fidelity.preserved,
    className: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300',
  });
  return chips;
}
