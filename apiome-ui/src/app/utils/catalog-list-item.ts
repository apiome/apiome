/**
 * Normalise catalog list rows from `/api/catalog` (MFI-23.2).
 *
 * The REST spine emits camelCase aliases (`sourceFormat`, `formatMetadata`, …) but tolerates both
 * shapes so a proxy or older payload still renders and filters correctly.
 */

import { parseEntityOwner, type EntityOwner } from '@lib/owners';

export interface NormalizedCatalogListItem {
  id: string;
  tenant_id: string;
  creator_id?: string | null;
  name: string;
  slug?: string | null;
  description?: string | null;
  enabled: boolean;
  deleted_at: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  creator_name?: string | null;
  creator_email?: string | null;
  metadata?: Record<string, unknown> | null;
  qualityScore?: number | null;
  qualityGrade?: string | null;
  versionsCount?: number;
  publishable?: boolean;
  sourceFormat?: string | null;
  protocol?: string | null;
  formatMetadata?: Record<string, unknown> | null;
  identityGroupId?: string | null;
  conversion?: unknown;
  /** The owner team (CDG-2.4). */
  owner?: EntityOwner | null;
  /** Categorization (MFI-6.3): auto-derived paradigm, manual domain, free-form tags. */
  paradigm?: string | null;
  domain?: string | null;
  tags?: string[];
}

function pick<T>(raw: Record<string, unknown>, camel: string, snake: string): T | undefined {
  if (raw[camel] !== undefined) return raw[camel] as T;
  if (raw[snake] !== undefined) return raw[snake] as T;
  return undefined;
}

/** Coerce one catalog list row to the camelCase shape the dashboard expects. */
export function normalizeCatalogListItem(raw: Record<string, unknown>): NormalizedCatalogListItem {
  const base = raw as unknown as NormalizedCatalogListItem;
  return {
    ...base,
    qualityScore: pick<number | null>(raw, 'qualityScore', 'quality_score') ?? base.qualityScore,
    qualityGrade: pick<string | null>(raw, 'qualityGrade', 'quality_grade') ?? base.qualityGrade,
    versionsCount: pick<number>(raw, 'versionsCount', 'versions_count') ?? base.versionsCount,
    sourceFormat: pick<string | null>(raw, 'sourceFormat', 'source_format') ?? base.sourceFormat,
    formatMetadata:
      pick<Record<string, unknown>>(raw, 'formatMetadata', 'format_metadata') ?? base.formatMetadata,
    identityGroupId:
      pick<string | null>(raw, 'identityGroupId', 'identity_group_id') ?? base.identityGroupId,
    // An older API without MFI-6.3 sends no tags; an empty list keeps every reader simple.
    tags: Array.isArray(raw.tags) ? (raw.tags as unknown[]).filter((t): t is string => typeof t === 'string') : [],
    // CDG-2.4: the owner team, validated once here so every reader gets the typed shape.
    owner: parseEntityOwner(raw.owner),
  };
}
