/**
 * Inference provenance on the catalog detail — FMT-8.6 (#5467).
 *
 * The REST detail read stamps every parsed entity with the provenance of the construct behind it
 * (`apiome-rest` `app/inference_provenance.py`): **declared** — the source stated it; **inferred**
 * — Apiome deduced it from an example or from code; **synthesized** — Apiome supplied it, such as
 * a name for an anonymous type. An entity with no stamp (an older read) is declared.
 *
 * Everything here is pure so the badge copy, the filter and the ratio line are testable without a
 * DOM; the components in `CatalogParsedModel.tsx` only render what these return.
 */

import { STATUS_TONE_SOFT_CLASS } from '@/app/components/ui/statusVocabulary';

/** The three provenance classes, in the order the filter lists them. */
export const PROVENANCE_CLASSES = ['declared', 'inferred', 'synthesized'] as const;

/** One provenance class. */
export type ProvenanceClass = (typeof PROVENANCE_CLASSES)[number];

/** The filter value: one class, or every entity. */
export type ProvenanceFilter = ProvenanceClass | 'all';

/** The per-class counts the detail read carries as `provenanceSummary`. */
export interface CatalogProvenanceSummary {
  declared: number;
  inferred: number;
  synthesized: number;
  total: number;
  /** `inferred / total`, `0` for an empty model. */
  inferredRatio: number;
}

/** The shape of an entity the helpers read (structurally compatible with `CatalogParsedEntity`). */
export interface ProvenanceStamped {
  provenance?: string | null;
  provenanceEvidence?: string | null;
}

/** How each class reads in the product: its label, its badge tone and what it means. */
export const PROVENANCE_PRESENTATION: Readonly<
  Record<ProvenanceClass, { label: string; toneClass: string; meaning: string }>
> = {
  declared: {
    label: 'Declared',
    toneClass: STATUS_TONE_SOFT_CLASS.neutral,
    meaning: 'The source states this.',
  },
  inferred: {
    label: 'Inferred',
    toneClass: STATUS_TONE_SOFT_CLASS.warn,
    meaning: 'Apiome deduced this from an example or from code.',
  },
  synthesized: {
    label: 'Synthesized',
    toneClass: STATUS_TONE_SOFT_CLASS.violet,
    meaning: 'Apiome supplied this, such as a name for an anonymous type.',
  },
};

/**
 * The provenance class of an entity.
 *
 * @param entity The parsed entity.
 * @returns Its class; `declared` when it carries none or an unknown value.
 */
export function provenanceClassOf(entity: ProvenanceStamped): ProvenanceClass {
  const value = entity.provenance;
  return value === 'inferred' || value === 'synthesized' ? value : 'declared';
}

/**
 * The tooltip/accessible description of an entity's provenance badge.
 *
 * @param entity The parsed entity.
 * @returns The class's meaning, followed by the entity's own evidence when it has some.
 */
export function provenanceDescription(entity: ProvenanceStamped): string {
  const { meaning } = PROVENANCE_PRESENTATION[provenanceClassOf(entity)];
  const evidence = entity.provenanceEvidence?.trim();
  return evidence ? `${meaning} ${evidence}` : meaning;
}

/**
 * Whether an entity passes the provenance filter.
 *
 * @param entity The parsed entity.
 * @param filter The selected class, or `all`.
 * @returns `true` for `all`, otherwise whether the entity's class matches.
 */
export function matchesProvenanceFilter(entity: ProvenanceStamped, filter: ProvenanceFilter): boolean {
  return filter === 'all' || provenanceClassOf(entity) === filter;
}

/**
 * Count the parsed entities per class — the numbers the filter options show.
 *
 * @param groups The parsed groups.
 * @returns Each class's entity count plus `all`.
 */
export function countEntitiesByProvenance(
  groups: ReadonlyArray<{ entities: ReadonlyArray<ProvenanceStamped> }> | null | undefined,
): Record<ProvenanceFilter, number> {
  const counts: Record<ProvenanceFilter, number> = { all: 0, declared: 0, inferred: 0, synthesized: 0 };
  for (const group of groups ?? []) {
    for (const entity of group.entities) {
      counts.all += 1;
      counts[provenanceClassOf(entity)] += 1;
    }
  }
  return counts;
}

/**
 * Whether the provenance filter is worth showing: only when some entity is not declared, so a
 * fully declarative item (OpenAPI, protobuf …) keeps its Overview unchanged.
 *
 * @param counts The per-class entity counts.
 * @returns `true` when at least one entity is inferred or synthesized.
 */
export function hasNonDeclaredEntities(counts: Record<ProvenanceFilter, number>): boolean {
  return counts.inferred + counts.synthesized > 0;
}

/**
 * The line under the filter that states how much of the item Apiome inferred — the same figure
 * the `provenance.inferred-construct-ratio` lint finding reports.
 *
 * @param summary The read's `provenanceSummary`, when present.
 * @returns e.g. "62% of this item's constructs are inferred (13 of 21) · 2 synthesized", or `null`
 *   when nothing is inferred or synthesized (or there is no summary).
 */
export function provenanceRatioLine(summary: CatalogProvenanceSummary | null | undefined): string | null {
  if (!summary || summary.total <= 0) return null;
  if (summary.inferred === 0 && summary.synthesized === 0) return null;
  const percent = Math.round((summary.inferred / summary.total) * 100);
  const parts = [`${percent}% of this item's constructs are inferred (${summary.inferred} of ${summary.total})`];
  if (summary.synthesized > 0) parts.push(`${summary.synthesized} synthesized`);
  return parts.join(' · ');
}
