/**
 * Merge strategies for an import into an existing project: additive (#591) and override (#592).
 *
 * Both keep what the project's latest version has and the spec leaves out, and add what the spec
 * newly defines. They differ only where both sides define the same thing:
 *
 * - **additive** — "add what is new, keep what exists": the existing definition wins. A schema both
 *   sides define keeps its properties and metadata and gains the spec's new properties (nested ones
 *   too) — {@link mergeClasses} with the `additive` strategy. A path both sides define keeps its
 *   operations and gains the spec's new methods.
 * - **override** — "imported values take precedence": the spec's definition wins. A property both
 *   sides define takes the spec's definition (its nested properties are merged the same way); the
 *   schema takes the spec's description and schema. A path both sides define takes the spec's
 *   operation for every method the spec declares, and keeps its other operations.
 *
 * In both, a schema or path only the spec defines is added, and one only the latest version has is
 * carried forward unchanged.
 *
 * Pure: the importer (`lib/db/import-helper.ts`) loads the latest version and writes the result.
 */

import type { NormalizedClass, NormalizedProperty } from './importers';
import type { ParsedOperation, ParsedPath } from '../src/app/utils/openapi-import';
import { mergeClasses } from '../src/app/utils/schema-merge';

/** How an import combines with the project's latest version. Omitted = the import replaces it. */
export type ImportMergeStrategy = 'additive' | 'override';

/** What a merge did, for the import log and the Done step. */
export interface ImportMergeStats {
  /** The strategy that ran. */
  strategy: ImportMergeStrategy;
  /** Schemas both sides define. */
  schemasMerged: number;
  /** Properties (at any depth) the spec adds to those schemas. */
  propertiesAdded: number;
  /** Properties (at any depth) both sides define whose definition the spec replaced (override only). */
  propertiesUpdated: number;
  /** Schemas only the latest version has, carried forward unchanged. */
  schemasCarried: number;
  /** Paths only the latest version has, carried forward unchanged. */
  pathsCarried: number;
  /** Operations the spec adds to paths the latest version already has. */
  operationsAdded: number;
  /** Operations both sides define that the spec's definition replaced (override only). */
  operationsUpdated: number;
}

/** The class side of a merge. */
export interface MergeClassPlan {
  /** The classes to write: the import's, with each same-named class replaced by its merge. */
  classes: NormalizedClass[];
  /** Names of the latest version's classes the import does not define (copied forward as stored). */
  carriedClassNames: string[];
  schemasMerged: number;
  propertiesAdded: number;
  propertiesUpdated: number;
}

/** The path side of a merge. */
export interface MergePathPlan {
  /** The paths to write: existing ones (merged with the spec's), then the spec's new ones. */
  paths: ParsedPath[];
  pathsCarried: number;
  operationsAdded: number;
  operationsUpdated: number;
}

/**
 * JSON with object keys sorted, so two equal definitions compare equal whatever their key order.
 *
 * @param value - Any JSON value.
 * @returns Its canonical string.
 */
function canonical(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value) ?? 'undefined';
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  const obj = value as Record<string, unknown>;
  // A key set to undefined is the same as a missing key (parsed operations carry many).
  return `{${Object.keys(obj)
    .filter((k) => obj[k] !== undefined)
    .sort()
    .map((k) => `${JSON.stringify(k)}:${canonical(obj[k])}`)
    .join(',')}}`;
}

/**
 * Count properties at every depth.
 *
 * @param list - A property list (nested properties under `children`).
 * @returns The number of properties, children included.
 */
function countProperties(list: readonly NormalizedProperty[] | undefined): number {
  let n = 0;
  for (const p of list ?? []) n += 1 + countProperties(p.children);
  return n;
}

/** Counts gathered while merging property lists. */
interface PropertyCounts {
  added: number;
  updated: number;
}

/**
 * Override-merge two property lists (#592): the spec's definition wins for a property both define;
 * nested properties are merged the same way; properties only one side has are kept. Order: existing
 * properties first, then the spec's new ones.
 *
 * @param existing - The latest version's properties.
 * @param imported - The spec's properties.
 * @param counts - Accumulates added and updated properties.
 * @returns The merged list.
 */
function overrideProperties(
  existing: readonly NormalizedProperty[],
  imported: readonly NormalizedProperty[],
  counts: PropertyCounts,
): NormalizedProperty[] {
  const importedByName = new Map(imported.map((p) => [p.name, p]));
  const existingNames = new Set(existing.map((p) => p.name));
  const merged: NormalizedProperty[] = existing.map((e) => {
    const i = importedByName.get(e.name);
    if (!i) return e;
    if (canonical(e.data) !== canonical(i.data)) counts.updated += 1;
    const children =
      e.children?.length || i.children?.length ? overrideProperties(e.children ?? [], i.children ?? [], counts) : undefined;
    return {
      name: i.name,
      data: i.data,
      description: i.description ?? e.description,
      children: children?.length ? children : undefined,
    };
  });
  for (const i of imported) {
    if (existingNames.has(i.name)) continue;
    counts.added += 1 + countProperties(i.children);
    merged.push(i);
  }
  return merged;
}

/**
 * Plan the class side of a merge.
 *
 * @param parentClasses - The latest version's classes, normalized (see `dbClassToNormalized`).
 * @param importedClasses - The classes the import normalized from the spec.
 * @param strategy - `additive` (existing wins) or `override` (the spec wins).
 * @returns The classes to write, the classes to carry forward, and counts.
 */
export function planMergeClasses(
  parentClasses: readonly NormalizedClass[],
  importedClasses: readonly NormalizedClass[],
  strategy: ImportMergeStrategy,
): MergeClassPlan {
  const parentByName = new Map(parentClasses.map((c) => [c.name, c]));
  const importedNames = new Set(importedClasses.map((c) => c.name));
  let schemasMerged = 0;
  const counts: PropertyCounts = { added: 0, updated: 0 };

  const classes = importedClasses.map((imported): NormalizedClass => {
    const existing = parentByName.get(imported.name);
    if (!existing) return imported;
    schemasMerged += 1;
    if (strategy === 'additive') {
      const merged = mergeClasses(existing, imported, 'additive');
      // Additive keeps every existing property, so the difference is exactly what was added.
      counts.added += countProperties(merged.properties) - countProperties(existing.properties);
      return merged;
    }
    return {
      name: imported.name,
      originalSchemaKey: imported.originalSchemaKey ?? existing.originalSchemaKey,
      description: imported.description ?? existing.description,
      schema: imported.schema ?? existing.schema ?? { type: 'object' },
      properties: overrideProperties(existing.properties ?? [], imported.properties ?? [], counts),
    };
  });

  const carriedClassNames = parentClasses.map((c) => c.name).filter((name) => !importedNames.has(name));
  return { classes, carriedClassNames, schemasMerged, propertiesAdded: counts.added, propertiesUpdated: counts.updated };
}

/**
 * Plan the path side of a merge.
 *
 * @param parentPaths - The latest version's paths, parsed (see `loadCarriedPaths`).
 * @param incomingPaths - The paths the spec defines.
 * @param strategy - `additive` (existing operations win) or `override` (the spec's operations win).
 * @returns The merged path list and counts.
 */
export function planMergePaths(
  parentPaths: readonly ParsedPath[],
  incomingPaths: readonly ParsedPath[],
  strategy: ImportMergeStrategy,
): MergePathPlan {
  const incomingByPath = new Map(incomingPaths.map((p) => [p.path, p]));
  const parentNames = new Set(parentPaths.map((p) => p.path));
  let pathsCarried = 0;
  let operationsAdded = 0;
  let operationsUpdated = 0;

  const paths: ParsedPath[] = parentPaths.map((existing) => {
    const incoming = incomingByPath.get(existing.path);
    if (!incoming) {
      pathsCarried += 1;
      return existing;
    }
    const incomingByMethod = new Map(incoming.operations.map((o) => [o.method, o]));
    const existingMethods = new Set(existing.operations.map((o) => o.method));
    const added = incoming.operations.filter((o) => !existingMethods.has(o.method));
    operationsAdded += added.length;
    if (strategy === 'additive') {
      return added.length > 0 ? { ...existing, operations: [...existing.operations, ...added] } : existing;
    }
    const operations: ParsedOperation[] = existing.operations.map((e) => {
      const i = incomingByMethod.get(e.method);
      if (!i) return e;
      if (canonical(e) !== canonical(i)) operationsUpdated += 1;
      return i;
    });
    return {
      ...existing,
      summary: incoming.summary ?? existing.summary,
      description: incoming.description ?? existing.description,
      parameters: incoming.parameters ?? existing.parameters,
      operations: [...operations, ...added],
    };
  });
  for (const incoming of incomingPaths) {
    if (!parentNames.has(incoming.path)) paths.push(incoming);
  }
  return { paths, pathsCarried, operationsAdded, operationsUpdated };
}

/**
 * Pluralise a count for {@link describeImportMerge}.
 *
 * @param n - The count.
 * @param one - The singular noun.
 * @param many - The plural noun.
 * @returns e.g. `1 schema`, `3 schemas`.
 */
function count(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** The Done step's label for each strategy. */
const STRATEGY_LABEL: Readonly<Record<ImportMergeStrategy, string>> = {
  additive: 'Additive',
  override: 'Override',
};

/**
 * One line describing a merge, for the Done step (#591, #592).
 *
 * @param stats - What the merge did.
 * @returns e.g. `Additive — 2 schemas merged (3 properties added), 1 operation added; 4 schemas and
 *   5 paths kept from the latest version`, or for override `Override — 2 schemas merged
 *   (1 property added, 2 updated), 1 operation updated; …`.
 */
export function describeImportMerge(stats: ImportMergeStats): string {
  const properties =
    stats.strategy === 'override'
      ? `${count(stats.propertiesAdded, 'property', 'properties')} added, ${stats.propertiesUpdated} updated`
      : `${count(stats.propertiesAdded, 'property', 'properties')} added`;
  const parts = [`${count(stats.schemasMerged, 'schema', 'schemas')} merged (${properties})`];
  if (stats.operationsAdded > 0) parts.push(`${count(stats.operationsAdded, 'operation', 'operations')} added`);
  if (stats.operationsUpdated > 0) parts.push(`${count(stats.operationsUpdated, 'operation', 'operations')} updated`);
  const kept = `${count(stats.schemasCarried, 'schema', 'schemas')} and ${count(stats.pathsCarried, 'path', 'paths')} kept from the latest version`;
  return `${STRATEGY_LABEL[stats.strategy]} — ${parts.join(', ')}; ${kept}`;
}
