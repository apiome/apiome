/**
 * Merge strategies for an import into an existing project: additive (#591) and override (#592).
 *
 * Both keep what the project's latest version has and the spec leaves out, and add what the spec
 * newly defines. They differ only where both sides define the same thing:
 *
 * - **additive** — "add what is new, keep what exists": the existing definition wins. A schema both
 *   sides define keeps its properties and metadata and gains the spec's new properties (nested ones
 *   too). A path both sides define keeps its operations and gains the spec's new methods.
 * - **override** — "imported values take precedence": the spec's definition wins. A property both
 *   sides define takes the spec's definition (its nested properties are merged the same way); the
 *   schema takes the spec's description and schema. A path both sides define takes the spec's
 *   operation for every method the spec declares, and keeps its other operations.
 *
 * In both, a schema or path only the spec defines is added, and one only the latest version has is
 * carried forward unchanged.
 *
 * **Arrays** (#595): where both sides define a property or schema holding the same array (`enum`,
 * `required`, `examples`, …), the arrays are combined by an {@link ArrayMergeStrategy} — `replace`
 * (default) keeps the winning side's, `append` adds the other side's items after it, `deduplicate`
 * does the same without repeats. Operation arrays are not combined.
 *
 * Pure: the importer (`lib/db/import-helper.ts`) loads the latest version and writes the result.
 */

import type { NormalizedClass, NormalizedProperty } from './importers';
import type { ParsedOperation, ParsedPath } from '../src/app/utils/openapi-import';

/** How an import combines with the project's latest version. Omitted = the import replaces it. */
export type ImportMergeStrategy = 'additive' | 'override';

/**
 * How a merge combines an array both sides define (#595): `replace` keeps the winning side's array
 * (the stored one under additive, the spec's under override); `append` adds the other side's items
 * after the winner's; `deduplicate` does the same without repeats.
 */
export type ArrayMergeStrategy = 'replace' | 'append' | 'deduplicate';

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
  /** How arrays both sides define were combined (#595). */
  arrayStrategy: ArrayMergeStrategy;
  /** Arrays whose combined value differs from the winning side's (#595). */
  arraysCombined: number;
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
  /** Arrays whose combined value differs from the winning side's (#595). */
  arraysCombined: number;
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

/** Counts gathered while merging property lists and schemas. */
interface MergeCounts {
  added: number;
  updated: number;
  /** Arrays whose combined value differs from the winning side's (#595). */
  arraysCombined: number;
}

/**
 * Whether a value is a plain JSON object (not an array, not null).
 *
 * @param value - Any value.
 * @returns True for a plain object.
 */
function isPlainObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/**
 * Combine two arrays (#595).
 *
 * @param winner - The winning side's array (stored under additive, the spec's under override).
 * @param other - The other side's array.
 * @param mode - `replace` keeps `winner`; `append` adds `other`'s items after it (repeats kept);
 *   `deduplicate` does the same without repeats (items compared canonically, the first kept).
 * @returns The combined array.
 */
export function combineArray(winner: readonly unknown[], other: readonly unknown[], mode: ArrayMergeStrategy): unknown[] {
  if (mode === 'replace') return [...winner];
  if (mode === 'append') return [...winner, ...other];
  const seen = new Set<string>();
  const out: unknown[] = [];
  for (const item of [...winner, ...other]) {
    const key = canonical(item);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(item);
  }
  return out;
}

/**
 * Combine the arrays two JSON definitions both hold (#595), keeping everything else from the winner.
 *
 * Walks `winner`: where both sides hold an array at the same key, the arrays are combined by `mode`;
 * where both hold plain objects (e.g. `items`), it recurses; any other value is the winner's. Keys
 * only `other` has are not added — which side wins is the merge strategy's call, not this one's.
 *
 * @param winner - The winning side's definition.
 * @param other - The other side's definition.
 * @param mode - How arrays are combined; `replace` returns `winner` unchanged.
 * @param counts - `arraysCombined` counts the arrays whose result differs from the winner's.
 * @returns The definition with its arrays combined.
 */
function combineArrayValues(winner: unknown, other: unknown, mode: ArrayMergeStrategy, counts: MergeCounts): unknown {
  if (mode === 'replace' || !isPlainObject(winner) || !isPlainObject(other)) return winner;
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(winner)) {
    const theirs = other[key];
    if (Array.isArray(value) && Array.isArray(theirs)) {
      const combined = combineArray(value, theirs, mode);
      if (canonical(combined) !== canonical(value)) counts.arraysCombined += 1;
      out[key] = combined;
    } else if (isPlainObject(value) && isPlainObject(theirs)) {
      out[key] = combineArrayValues(value, theirs, mode, counts);
    } else {
      out[key] = value;
    }
  }
  return out;
}

/**
 * Merge two property lists (#591 additive, #592 override, #595 arrays).
 *
 * Properties only one side has are kept; nested properties are merged the same way. Order: existing
 * properties first, then the spec's new ones. For a property both define:
 * - additive — the stored property is kept (definition and description);
 * - override — the spec's definition wins as a whole, its description when it has one.
 * Then the arrays both definitions hold are combined by `arrays`, the winner's items first.
 *
 * @param existing - The latest version's properties.
 * @param imported - The spec's properties.
 * @param strategy - Which side wins.
 * @param arrays - How arrays both sides define are combined.
 * @param counts - Accumulates added and updated properties and combined arrays.
 * @returns The merged list.
 */
function mergeProperties(
  existing: readonly NormalizedProperty[],
  imported: readonly NormalizedProperty[],
  strategy: ImportMergeStrategy,
  arrays: ArrayMergeStrategy,
  counts: MergeCounts,
): NormalizedProperty[] {
  const importedByName = new Map(imported.map((p) => [p.name, p]));
  const existingNames = new Set(existing.map((p) => p.name));
  const merged: NormalizedProperty[] = existing.map((e) => {
    const i = importedByName.get(e.name);
    if (!i) return e;
    const children =
      e.children?.length || i.children?.length
        ? mergeProperties(e.children ?? [], i.children ?? [], strategy, arrays, counts)
        : undefined;
    if (strategy === 'additive') {
      return {
        ...e,
        data: combineArrayValues(e.data, i.data, arrays, counts),
        ...(children !== undefined ? { children } : {}),
      };
    }
    if (canonical(e.data) !== canonical(i.data)) counts.updated += 1;
    return {
      name: i.name,
      data: combineArrayValues(i.data, e.data, arrays, counts),
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
 * @param arrays - How arrays both sides define are combined (#595); default `replace` (the winner's).
 * @returns The classes to write, the classes to carry forward, and counts.
 */
export function planMergeClasses(
  parentClasses: readonly NormalizedClass[],
  importedClasses: readonly NormalizedClass[],
  strategy: ImportMergeStrategy,
  arrays: ArrayMergeStrategy = 'replace',
): MergeClassPlan {
  const parentByName = new Map(parentClasses.map((c) => [c.name, c]));
  const importedNames = new Set(importedClasses.map((c) => c.name));
  let schemasMerged = 0;
  const counts: MergeCounts = { added: 0, updated: 0, arraysCombined: 0 };

  const classes = importedClasses.map((imported): NormalizedClass => {
    const existing = parentByName.get(imported.name);
    if (!existing) return imported;
    schemasMerged += 1;
    const properties = mergeProperties(existing.properties ?? [], imported.properties ?? [], strategy, arrays, counts);
    if (strategy === 'additive') {
      // The stored class wins: its name, description and schema (with arrays combined).
      return {
        name: existing.name,
        originalSchemaKey: imported.originalSchemaKey ?? existing.originalSchemaKey,
        description: existing.description ?? imported.description,
        schema: combineArrayValues(existing.schema ?? imported.schema ?? { type: 'object' }, imported.schema, arrays, counts),
        properties,
      };
    }
    return {
      name: imported.name,
      originalSchemaKey: imported.originalSchemaKey ?? existing.originalSchemaKey,
      description: imported.description ?? existing.description,
      schema: combineArrayValues(imported.schema ?? existing.schema ?? { type: 'object' }, existing.schema, arrays, counts),
      properties,
    };
  });

  const carriedClassNames = parentClasses.map((c) => c.name).filter((name) => !importedNames.has(name));
  return {
    classes,
    carriedClassNames,
    schemasMerged,
    propertiesAdded: counts.added,
    propertiesUpdated: counts.updated,
    arraysCombined: counts.arraysCombined,
  };
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
  if (stats.arraysCombined > 0 && stats.arrayStrategy !== 'replace') {
    parts.push(`${count(stats.arraysCombined, 'array', 'arrays')} ${stats.arrayStrategy === 'append' ? 'appended' : 'deduplicated'}`);
  }
  const kept = `${count(stats.schemasCarried, 'schema', 'schemas')} and ${count(stats.pathsCarried, 'path', 'paths')} kept from the latest version`;
  return `${STRATEGY_LABEL[stats.strategy]} — ${parts.join(', ')}; ${kept}`;
}
