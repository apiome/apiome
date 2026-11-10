/**
 * The user-facing fidelity advisory for a cross-format export (MFX-2.4, #3841).
 *
 * Wording is computed server-side once in apiome-rest and rendered verbatim in browse,
 * apiome-ui, and the CLI. This module mirrors Python `ExportAdvisory` field-for-field and
 * maps severity to CSS utility classes — it never re-templates the copy.
 */

/** How much a fidelity loss matters (mirrors Python `LossinessSeverity`). */
export type AdvisorySeverity = 'info' | 'warn' | 'critical';

/** The single user-facing advisory for one export (mirrors Python `ExportAdvisory`). */
export interface ExportAdvisory {
  show: boolean;
  severity: AdvisorySeverity | null;
  requires_ack: boolean;
  target_format: string;
  dropped: number;
  approximated: number;
  synthesized: number;
  affected: number;
  headline: string;
  message: string;
}

/** How the advisory banner presents: CSS palette strength and acknowledgement gate. */
export interface AdvisoryPresentation {
  strength: 'critical' | 'warning' | 'info';
  requiresAck: boolean;
}

/** Map an advisory to banner presentation strength and acknowledgement gate. */
export function advisoryPresentation(advisory: ExportAdvisory): AdvisoryPresentation {
  const strength: AdvisoryPresentation['strength'] =
    advisory.severity === 'critical'
      ? 'critical'
      : advisory.severity === 'warn'
        ? 'warning'
        : 'info';
  return { strength, requiresAck: advisory.requires_ack };
}

/** CSS utility classes for the advisory banner container. */
export function advisoryBannerClass(strength: AdvisoryPresentation['strength']): string {
  switch (strength) {
    case 'critical':
      return 'border-danger/30 bg-danger-soft text-danger-fg';
    case 'warning':
      return 'border-warn/30 bg-warn-soft text-warn-fg';
    case 'info':
    default:
      return 'border-accent/30 bg-accent-soft text-accent-fg';
  }
}

/** CSS utility classes for the severity pill in the advisory header. */
export function advisorySeverityPillClass(severity: AdvisorySeverity | null): string {
  switch (severity) {
    case 'critical':
      return 'bg-danger-soft text-danger-fg';
    case 'warn':
      return 'bg-warn-soft text-warn-fg';
    case 'info':
    default:
      return 'bg-accent-soft text-accent-fg';
  }
}

/** One row of advisory count chips (dropped, approximated, synthesized). */
export interface AdvisoryChip {
  key: 'dropped' | 'approximated' | 'synthesized';
  label: string;
  count: number;
}

/** Break advisory counts into chips, worst-first, omitting empty buckets. */
export function advisoryChips(advisory: ExportAdvisory): AdvisoryChip[] {
  const all: AdvisoryChip[] = [
    { key: 'dropped', label: 'dropped', count: advisory.dropped },
    { key: 'approximated', label: 'approximated', count: advisory.approximated },
    { key: 'synthesized', label: 'synthesized', count: advisory.synthesized },
  ];
  return all.filter((chip) => chip.count > 0);
}
