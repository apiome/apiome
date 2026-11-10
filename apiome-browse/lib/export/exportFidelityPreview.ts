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
      return 'bg-danger-soft text-danger-fg';
    case 'approx':
      return 'bg-warn-soft text-warn-fg';
    case 'synth':
      return 'bg-violet-soft text-violet-fg';
    case 'ok':
    default:
      return 'bg-ok-soft text-ok-fg';
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
      return 'stroke-ok';
    case 'lossy':
      return 'stroke-warn';
    case 'types-only':
    default:
      return 'stroke-danger';
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
      className: 'bg-danger-soft text-danger-fg',
    },
    {
      key: 'approximated',
      label: 'approximated',
      count: fidelity.approximated,
      className: 'bg-warn-soft text-warn-fg',
    },
    {
      key: 'synthesized',
      label: 'synthesized',
      count: fidelity.synthesized,
      className: 'bg-violet-soft text-violet-fg',
    },
  ];
  const chips = lossChips.filter((chip) => chip.count > 0);
  chips.push({
    key: 'preserved',
    label: 'clean',
    count: fidelity.preserved,
    className: 'bg-ok-soft text-ok-fg',
  });
  return chips;
}
