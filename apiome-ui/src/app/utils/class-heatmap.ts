/**
 * The class heatmap for one revision (#560).
 *
 * Every class of a revision becomes a tile whose warmth (a 0–4 heat level) reads one of four
 * metrics, so a reader can see at a glance where a schema is heavy, busy, load-bearing or
 * thin on documentation:
 *
 * | Metric          | Value                                                     | Warmer means          |
 * | --------------- | --------------------------------------------------------- | --------------------- |
 * | `complexity`    | properties + nesting depth + outgoing class references    | more complex          |
 * | `change`        | days since the class was last modified                    | modified more recently|
 * | `references`    | other classes in the revision that `$ref` this class      | used by more classes  |
 * | `documentation` | % of the class and its properties that have a description | better documented     |
 *
 * Everything here is pure: the dialog hands in the classes it loaded and the current time.
 */

import { buildRelationshipGraphData } from './relationship-graph';

/** The four ways the heatmap can colour a class. */
export type HeatmapMetric = 'complexity' | 'change' | 'references' | 'documentation';

/** The metrics in the order the switch lists them. */
export const HEATMAP_METRICS: readonly HeatmapMetric[] = ['complexity', 'change', 'references', 'documentation'];

/** A heat level: 0 is cold (none / oldest / undocumented), 4 is the warmest. */
export type HeatLevel = 0 | 1 | 2 | 3 | 4;

/** The label and legend wording for each metric. */
export const HEATMAP_METRIC_COPY: Readonly<Record<HeatmapMetric, { label: string; cold: string; warm: string }>> = {
  complexity: { label: 'Complexity', cold: 'Simpler', warm: 'More complex' },
  change: { label: 'Recent change', cold: 'Older', warm: 'Changed recently' },
  references: { label: 'References', cold: 'Unreferenced', warm: 'Most referenced' },
  documentation: { label: 'Documentation', cold: 'Undocumented', warm: 'Fully documented' },
};

/** A property row as `getPropertiesForClass` returns it (only the fields read here). */
export interface HeatmapProperty {
  id: string;
  name: string;
  description?: string | null;
  data?: unknown;
  parent_id?: string | null;
}

/** A class row as `getClassesForVersion` returns it, with its properties attached. */
export interface HeatmapClass {
  id: string;
  name: string;
  description?: string | null;
  updated_at?: string | null;
  created_at?: string | null;
  properties?: HeatmapProperty[];
}

/** The measured facts for one class, before any metric is chosen. */
export interface ClassHeatmapCell {
  id: string;
  name: string;
  /** Property rows, nested ones included. */
  propertyCount: number;
  /** Deepest property nesting (0 = no properties, 1 = top-level only). */
  depth: number;
  /** Distinct other classes this class references. */
  outgoingRefs: number;
  /** `propertyCount + depth + outgoingRefs`. */
  complexity: number;
  /** Distinct other classes that reference this class. */
  references: number;
  /** Last-modified time as an ISO string, or `null` when unknown. */
  modifiedAt: string | null;
  /** Whole days between `modifiedAt` and `now`, or `null` when unknown. */
  ageDays: number | null;
  /** Items that carry a description (class + properties). */
  documented: number;
  /** Items that could carry one (1 + `propertyCount`). */
  documentable: number;
  /** `documented / documentable` as a whole percentage. */
  documentationPct: number;
}

const DAY_MS = 86_400_000;

/** True when `text` holds something other than whitespace. */
function hasText(text: string | null | undefined): boolean {
  return typeof text === 'string' && text.trim().length > 0;
}

/**
 * Deepest `parent_id` chain among a class's properties.
 *
 * @param properties The class's property rows.
 * @returns 0 for none, 1 when every property is top-level, and so on. A cycle or a parent
 *   that is not in the list stops the walk rather than looping.
 */
function nestingDepth(properties: HeatmapProperty[]): number {
  const parentOf = new Map(properties.map((p) => [p.id, p.parent_id ?? null]));
  let deepest = 0;
  for (const prop of properties) {
    let depth = 1;
    let parent = prop.parent_id ?? null;
    const seen = new Set<string>([prop.id]);
    while (parent && parentOf.has(parent) && !seen.has(parent)) {
      seen.add(parent);
      depth += 1;
      parent = parentOf.get(parent) ?? null;
    }
    deepest = Math.max(deepest, depth);
  }
  return deepest;
}

/**
 * Measure every class of a revision.
 *
 * @param classes The revision's classes, each with its `properties`.
 * @param now The time "recently" is measured from.
 * @returns One cell per class, in the order given.
 */
export function buildClassHeatmap(classes: HeatmapClass[], now: Date = new Date()): ClassHeatmapCell[] {
  const { edges } = buildRelationshipGraphData(
    classes.map((cls) => ({
      id: cls.id,
      name: cls.name,
      properties: (cls.properties ?? []).map((p) => ({ id: p.id, name: p.name, data: p.data })),
    }))
  );
  const outgoing = new Map<string, number>();
  const incoming = new Map<string, number>();
  for (const edge of edges) {
    outgoing.set(edge.source, (outgoing.get(edge.source) ?? 0) + 1);
    incoming.set(edge.target, (incoming.get(edge.target) ?? 0) + 1);
  }

  return classes.map((cls) => {
    const properties = cls.properties ?? [];
    const depth = nestingDepth(properties);
    const outgoingRefs = outgoing.get(cls.id) ?? 0;
    const modifiedAt = cls.updated_at ?? cls.created_at ?? null;
    const modifiedMs = modifiedAt ? Date.parse(modifiedAt) : NaN;
    const ageDays = Number.isNaN(modifiedMs) ? null : Math.max(0, Math.floor((now.getTime() - modifiedMs) / DAY_MS));
    const documentable = 1 + properties.length;
    const documented = (hasText(cls.description) ? 1 : 0) + properties.filter((p) => hasText(p.description)).length;
    return {
      id: cls.id,
      name: cls.name || cls.id,
      propertyCount: properties.length,
      depth,
      outgoingRefs,
      complexity: properties.length + depth + outgoingRefs,
      references: incoming.get(cls.id) ?? 0,
      modifiedAt: Number.isNaN(modifiedMs) ? null : modifiedAt,
      ageDays,
      documented,
      documentable,
      documentationPct: Math.round((documented / documentable) * 100),
    };
  });
}

/**
 * Place a count on the 0–4 scale relative to the largest count in the revision.
 *
 * @param value The class's count.
 * @param max The largest count among the revision's classes.
 * @returns 0 for a zero count, otherwise 1–4 by quarter of `max`.
 */
function relativeLevel(value: number, max: number): HeatLevel {
  if (value <= 0 || max <= 0) return 0;
  return Math.min(4, Math.max(1, Math.ceil((value / max) * 4))) as HeatLevel;
}

/**
 * Days since a change on the 0–4 scale: today 4, this week 3, this month 2, this quarter 1.
 *
 * @param ageDays Whole days since the last change, or `null` when unknown.
 * @returns The level; unknown and older than 90 days are 0.
 */
export function changeLevel(ageDays: number | null): HeatLevel {
  if (ageDays === null) return 0;
  if (ageDays <= 1) return 4;
  if (ageDays <= 7) return 3;
  if (ageDays <= 30) return 2;
  if (ageDays <= 90) return 1;
  return 0;
}

/**
 * Documentation coverage on the 0–4 scale: none 0, under 40 % 1, under 70 % 2, under 100 % 3,
 * complete 4.
 *
 * @param pct Whole-number coverage percentage.
 * @returns The level.
 */
export function documentationLevel(pct: number): HeatLevel {
  if (pct <= 0) return 0;
  if (pct < 40) return 1;
  if (pct < 70) return 2;
  if (pct < 100) return 3;
  return 4;
}

/**
 * The heat level of every cell for one metric.
 *
 * @param cells The revision's cells from {@link buildClassHeatmap}.
 * @param metric The metric to colour by.
 * @returns A level per cell id.
 */
export function heatLevels(cells: ClassHeatmapCell[], metric: HeatmapMetric): Map<string, HeatLevel> {
  const maxComplexity = Math.max(0, ...cells.map((c) => c.complexity));
  const maxReferences = Math.max(0, ...cells.map((c) => c.references));
  const levels = new Map<string, HeatLevel>();
  for (const cell of cells) {
    let level: HeatLevel;
    switch (metric) {
      case 'complexity':
        level = relativeLevel(cell.complexity, maxComplexity);
        break;
      case 'change':
        level = changeLevel(cell.ageDays);
        break;
      case 'references':
        level = relativeLevel(cell.references, maxReferences);
        break;
      case 'documentation':
        level = documentationLevel(cell.documentationPct);
        break;
    }
    levels.set(cell.id, level);
  }
  return levels;
}

/**
 * The short value a tile prints under its class name for one metric.
 *
 * @param cell The class's cell.
 * @param metric The metric being shown.
 * @returns E.g. `"12 (3 props)"`, `"Today"`, `"4 refs"`, `"75%"`.
 */
export function heatmapValueLabel(cell: ClassHeatmapCell, metric: HeatmapMetric): string {
  switch (metric) {
    case 'complexity':
      return `${cell.complexity} (${cell.propertyCount} prop${cell.propertyCount === 1 ? '' : 's'})`;
    case 'change':
      if (cell.ageDays === null) return 'Unknown';
      if (cell.ageDays === 0) return 'Today';
      return `${cell.ageDays} day${cell.ageDays === 1 ? '' : 's'} ago`;
    case 'references':
      return `${cell.references} ref${cell.references === 1 ? '' : 's'}`;
    case 'documentation':
      return `${cell.documentationPct}%`;
  }
}

/**
 * The full explanation a tile carries as its accessible description and tooltip.
 *
 * @param cell The class's cell.
 * @returns One sentence with all four measurements.
 */
export function heatmapCellSummary(cell: ClassHeatmapCell): string {
  const changed = cell.ageDays === null ? 'last change unknown' : `changed ${heatmapValueLabel(cell, 'change').toLowerCase()}`;
  return (
    `${cell.name}: complexity ${cell.complexity} (${cell.propertyCount} properties, depth ${cell.depth}, ` +
    `${cell.outgoingRefs} outgoing references); ${changed}; referenced by ${cell.references} ` +
    `class${cell.references === 1 ? '' : 'es'}; ${cell.documented} of ${cell.documentable} items documented ` +
    `(${cell.documentationPct}%).`
  );
}

/**
 * Order cells warmest first for a metric, then by name, so the hot spots lead the grid.
 *
 * @param cells The cells.
 * @param levels The levels from {@link heatLevels}.
 * @param metric The metric, whose raw value breaks ties between equal levels.
 * @returns A new, sorted array.
 */
export function sortCellsByHeat(
  cells: ClassHeatmapCell[],
  levels: Map<string, HeatLevel>,
  metric: HeatmapMetric
): ClassHeatmapCell[] {
  const raw = (c: ClassHeatmapCell): number => {
    switch (metric) {
      case 'complexity':
        return c.complexity;
      case 'change':
        return c.ageDays === null ? -Infinity : -c.ageDays;
      case 'references':
        return c.references;
      case 'documentation':
        return c.documentationPct;
    }
  };
  return [...cells].sort(
    (a, b) =>
      (levels.get(b.id) ?? 0) - (levels.get(a.id) ?? 0) || raw(b) - raw(a) || a.name.localeCompare(b.name)
  );
}
