/**
 * Additive merge for an import into an existing project (#591).
 *
 * "Add what is new, keep what exists": the new version keeps everything the project's latest
 * version has and adds what the imported spec newly defines.
 *
 * - A schema both sides define keeps its existing properties and metadata; properties only the spec
 *   has are added (nested ones too) — {@link mergeClasses} with the `additive` strategy.
 * - A schema only the spec defines is added; one only the latest version has is carried forward.
 * - A path both sides define keeps its existing operations; methods only the spec declares are added.
 *   A path only the spec defines is added; one only the latest version has is carried forward.
 *
 * Pure: the importer (`lib/db/import-helper.ts`) loads the latest version and writes the result.
 */

import type { NormalizedClass, NormalizedProperty } from './importers';
import type { ParsedPath } from '../src/app/utils/openapi-import';
import { mergeClasses } from '../src/app/utils/schema-merge';

/** How an import combines with the project's latest version. Omitted = the import replaces it. */
export type ImportMergeStrategy = 'additive';

/** What an additive merge did, for the import log and the Done step. */
export interface AdditiveMergeStats {
  /** Schemas both sides define (existing kept, new properties added). */
  schemasMerged: number;
  /** Properties (at any depth) added to those schemas from the spec. */
  propertiesAdded: number;
  /** Schemas only the latest version has, carried forward unchanged. */
  schemasCarried: number;
  /** Paths only the latest version has, carried forward unchanged. */
  pathsCarried: number;
  /** Operations the spec adds to paths the latest version already has. */
  operationsAdded: number;
}

/** The class side of an additive merge. */
export interface AdditiveClassPlan {
  /** The classes to write: the import's, with each same-named class replaced by its merge. */
  classes: NormalizedClass[];
  /** Names of the latest version's classes the import does not define (copied forward as stored). */
  carriedClassNames: string[];
  schemasMerged: number;
  propertiesAdded: number;
}

/** The path side of an additive merge. */
export interface AdditivePathPlan {
  /** The paths to write: existing ones (with any new operations), then the spec's new ones. */
  paths: ParsedPath[];
  pathsCarried: number;
  operationsAdded: number;
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

/**
 * Plan the class side of an additive merge.
 *
 * @param parentClasses - The latest version's classes, normalized (see `dbClassToNormalized`).
 * @param importedClasses - The classes the import normalized from the spec.
 * @returns The classes to write, the classes to carry forward, and counts.
 */
export function planAdditiveClasses(
  parentClasses: readonly NormalizedClass[],
  importedClasses: readonly NormalizedClass[],
): AdditiveClassPlan {
  const parentByName = new Map(parentClasses.map((c) => [c.name, c]));
  const importedNames = new Set(importedClasses.map((c) => c.name));
  let schemasMerged = 0;
  let propertiesAdded = 0;

  const classes = importedClasses.map((imported) => {
    const existing = parentByName.get(imported.name);
    if (!existing) return imported;
    const merged = mergeClasses(existing, imported, 'additive');
    schemasMerged += 1;
    // Additive keeps every existing property, so the difference is exactly what was added.
    propertiesAdded += countProperties(merged.properties) - countProperties(existing.properties);
    return merged;
  });

  const carriedClassNames = parentClasses.map((c) => c.name).filter((name) => !importedNames.has(name));
  return { classes, carriedClassNames, schemasMerged, propertiesAdded };
}

/**
 * Plan the path side of an additive merge.
 *
 * @param parentPaths - The latest version's paths, parsed (see `loadCarriedPaths`).
 * @param incomingPaths - The paths the spec defines.
 * @returns The merged path list and counts.
 */
export function planAdditivePaths(
  parentPaths: readonly ParsedPath[],
  incomingPaths: readonly ParsedPath[],
): AdditivePathPlan {
  const incomingByPath = new Map(incomingPaths.map((p) => [p.path, p]));
  const parentNames = new Set(parentPaths.map((p) => p.path));
  let pathsCarried = 0;
  let operationsAdded = 0;

  const paths: ParsedPath[] = parentPaths.map((existing) => {
    const incoming = incomingByPath.get(existing.path);
    if (!incoming) {
      pathsCarried += 1;
      return existing;
    }
    const methods = new Set(existing.operations.map((o) => o.method));
    const added = incoming.operations.filter((o) => !methods.has(o.method));
    operationsAdded += added.length;
    return added.length > 0 ? { ...existing, operations: [...existing.operations, ...added] } : existing;
  });
  for (const incoming of incomingPaths) {
    if (!parentNames.has(incoming.path)) paths.push(incoming);
  }
  return { paths, pathsCarried, operationsAdded };
}

/**
 * Pluralise a count for {@link describeAdditiveMerge}.
 *
 * @param n - The count.
 * @param one - The singular noun.
 * @param many - The plural noun.
 * @returns e.g. `1 schema`, `3 schemas`.
 */
function count(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/**
 * One line describing an additive merge, for the Done step (#591).
 *
 * @param stats - What the merge did.
 * @returns e.g. `Additive — 2 schemas merged (3 properties added), 1 operation added; 4 schemas and
 *   5 paths kept from the latest version`.
 */
export function describeAdditiveMerge(stats: AdditiveMergeStats): string {
  const added = [
    `${count(stats.schemasMerged, 'schema', 'schemas')} merged (${count(stats.propertiesAdded, 'property', 'properties')} added)`,
  ];
  if (stats.operationsAdded > 0) added.push(`${count(stats.operationsAdded, 'operation', 'operations')} added`);
  const kept = `${count(stats.schemasCarried, 'schema', 'schemas')} and ${count(stats.pathsCarried, 'path', 'paths')} kept from the latest version`;
  return `Additive — ${added.join(', ')}; ${kept}`;
}
