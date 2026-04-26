'use client';

import type { ReactNode } from 'react';
import {
  projectStatusChipBaseClass,
  projectStatusChipToneClass,
  type ProjectStatusChipTone,
} from './dashboardScreenClasses';

/**
 * Canonical project status. Today the API only persists `enabled` and
 * `deleted_at`, but the chip palette includes the lifecycle states the UI is
 * already designed for so version-driven derivations can plug in without a
 * new component.
 */
export type ProjectStatusKind =
  | 'enabled'
  | 'disabled'
  | 'attention'
  | 'inReview'
  | 'draft'
  | 'published'
  | 'deprecated'
  | 'deleted'
  | 'pii'
  | 'domain'
  | 'neutral';

const LABELS: Record<ProjectStatusKind, string> = {
  enabled: 'Enabled',
  disabled: 'Disabled',
  attention: 'Attention',
  inReview: 'In review',
  draft: 'Draft',
  published: 'Published',
  deprecated: 'Deprecated',
  deleted: 'Deleted',
  pii: 'PII',
  domain: 'Domain',
  neutral: '—',
};

export function formatProjectStatusLabel(kind: ProjectStatusKind): string {
  return LABELS[kind];
}

export interface ProjectStatusChipProps {
  kind: ProjectStatusKind;
  /** Optional override label; defaults to the canonical label for `kind`. */
  label?: ReactNode;
  /** Render a coloured leading dot. Default = on for `enabled`/`disabled`/`draft`. */
  showDot?: boolean;
  /** Tone override (rare — use when a derived state should display as another). */
  toneOverride?: ProjectStatusChipTone;
  className?: string;
}

const DEFAULT_DOT_KINDS = new Set<ProjectStatusKind>([
  'enabled',
  'disabled',
  'draft',
  'published',
]);

/**
 * Compact uppercase status pill. Centralises the colour mapping for every
 * project lifecycle state so cards / detail headers / settings tab stay
 * visually consistent.
 */
export function ProjectStatusChip({
  kind,
  label,
  showDot,
  toneOverride,
  className,
}: ProjectStatusChipProps) {
  const tone = toneOverride ?? kind;
  const renderDot = showDot ?? DEFAULT_DOT_KINDS.has(kind);
  return (
    <span
      className={`${projectStatusChipBaseClass} ${projectStatusChipToneClass[tone]}${className ? ` ${className}` : ''}`}
    >
      {renderDot ? (
        <span aria-hidden="true" className="w-1 h-1 rounded-full bg-current opacity-80" />
      ) : null}
      {label ?? LABELS[kind]}
    </span>
  );
}
