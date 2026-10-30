/**
 * Detect property definition conflicts (#583): same property name used with
 * incompatible definitions across schemas in an OpenAPI document.
 */

import type { ImportConflict } from '../components/ade/dashboard/ConflictReport';
import { extractDirectProperties as extractDirectPropertiesFromSchema } from './openapi-schema-direct-properties';

const VOLATILE_KEYS = new Set(['$id', '$schema']);

/**
 * Property map only (same merge rules as OpenAPI import / unified importer).
 * Exported for schema-import-property-diff and conflict detection.
 */
export function extractDirectProperties(schema: any): Record<string, any> {
  return extractDirectPropertiesFromSchema(schema).properties;
}

/**
 * Normalize a property definition for comparison: sort keys, strip volatile and x-* fields.
 */
function normalizePropertyDefinition(value: unknown): unknown {
  if (value === null || value === undefined) return value;
  if (typeof value !== 'object') return value;
  if (Array.isArray(value)) return value.map(normalizePropertyDefinition);

  const obj = value as Record<string, unknown>;
  const sorted: Record<string, unknown> = {};
  const keys = Object.keys(obj)
    .filter((k) => !VOLATILE_KEYS.has(k) && !k.startsWith('x-'))
    .sort();

  for (const k of keys) {
    sorted[k] = normalizePropertyDefinition(obj[k]);
  }
  return sorted;
}

function propertyDefinitionSignature(propSchema: any): string {
  return JSON.stringify(normalizePropertyDefinition(propSchema));
}

/**
 * Describe a property definition briefly for conflict messages (type, format, enum hint).
 */
function describeDefinition(propSchema: any): string {
  if (!propSchema || typeof propSchema !== 'object') return 'unknown';
  if (propSchema.$ref) return `$ref`;
  const t = propSchema.type ?? 'any';
  const f = propSchema.format ? ` ${propSchema.format}` : '';
  const e = Array.isArray(propSchema.enum) && propSchema.enum.length
    ? ` enum(${propSchema.enum.length})`
    : '';
  if (propSchema.type === 'array') {
    const item = propSchema.items;
    const itemDesc = item?.$ref ? '$ref' : item?.type ?? 'any';
    return `array<${itemDesc}>`;
  }
  return `${t}${f}${e}`;
}

/** The longest definition summary shown before it is cut (#583). */
const SUMMARY_MAX_LENGTH = 120;

/**
 * One definition as a reader compares it: its normalized JSON (sorted keys, no `$id` / `$schema`
 * or `x-` fields), cut at {@link SUMMARY_MAX_LENGTH}. Always distinct for two distinct definitions
 * up to the cut, which a type-only summary (`string` vs `string`) is not.
 *
 * @param propSchema The property schema.
 * @returns The summary.
 */
export function summarizePropertyDefinition(propSchema: unknown): string {
  const json = JSON.stringify(normalizePropertyDefinition(propSchema)) ?? 'undefined';
  return json.length > SUMMARY_MAX_LENGTH ? `${json.slice(0, SUMMARY_MAX_LENGTH - 1)}…` : json;
}

/** One property name defined more than one way (#583). */
export interface PropertyConflict {
  /** The property name. */
  property: string;
  /** Each distinct definition, in the order first seen, with the schemas that use it. */
  definitions: Array<{ schemas: string[]; summary: string }>;
}

export interface PropertyConflictInput {
  /** OpenAPI document (components.schemas or definitions) */
  document: any;
  /** Schema names to consider (e.g. all or selected) */
  schemaNames: string[];
}

/**
 * Find every property name that the given schemas define in more than one way (#583).
 *
 * Definitions are compared after normalization: key order, `$id` / `$schema` and `x-` extensions do
 * not count. Everything else does — a different `description` too, because the importer stores each
 * distinct definition as its own library property.
 *
 * @param input The document and the schema names to compare.
 * @returns One entry per conflicting property name, in the order the names were first seen.
 */
export function findPropertyConflicts(input: PropertyConflictInput): PropertyConflict[] {
  const { document, schemaNames } = input;
  const schemas = document?.components?.schemas || document?.definitions || {};
  const nameSet = new Set(schemaNames);
  if (nameSet.size === 0) return [];

  // propertyName -> { signature -> { schemaNames, sample } }
  const byPropName = new Map<string, Map<string, { schemaNames: string[]; sample: any }>>();
  for (const schemaName of nameSet) {
    const schema = schemas[schemaName];
    if (!schema) continue;
    for (const [propName, propSchema] of Object.entries(extractDirectProperties(schema))) {
      if (!propSchema || typeof propSchema !== 'object') continue;
      const sig = propertyDefinitionSignature(propSchema);
      if (!byPropName.has(propName)) byPropName.set(propName, new Map());
      const bySig = byPropName.get(propName)!;
      if (!bySig.has(sig)) bySig.set(sig, { schemaNames: [], sample: propSchema });
      const entry = bySig.get(sig)!;
      if (!entry.schemaNames.includes(schemaName)) entry.schemaNames.push(schemaName);
    }
  }

  const conflicts: PropertyConflict[] = [];
  for (const [property, bySig] of byPropName) {
    if (bySig.size < 2) continue; // one definition everywhere
    conflicts.push({
      property,
      definitions: Array.from(bySig.values()).map((entry) => ({
        schemas: entry.schemaNames,
        summary: summarizePropertyDefinition(entry.sample),
      })),
    });
  }
  return conflicts;
}

/** What the import does with a conflicting property (#583). */
const PROPERTY_CONFLICT_IMPACT =
  'Each definition is imported as its own property in the project library (for example "status" and ' +
  '"status_1"); every schema keeps its own definition.';

/**
 * Detect property definition conflicts (#583): for each property name that appears
 * in more than one schema with different definitions, returns one ImportConflict.
 */
export function detectPropertyConflicts(input: PropertyConflictInput): ImportConflict[] {
  const schemas = input.document?.components?.schemas || input.document?.definitions || {};
  return findPropertyConflicts(input).map(({ property, definitions }) => ({
    kind: 'property_conflict',
    schemaName: definitions[0].schemas[0],
    message: `Property "${property}" has incompatible definitions across schemas.`,
    detail: definitions
      .map(({ schemas: names }) => {
        const sample = extractDirectProperties(schemas[names[0]])[property];
        const shown = names.slice(0, 3).join(', ');
        const more = names.length > 3 ? ` +${names.length - 3} more` : '';
        return `${shown}${more} (${describeDefinition(sample)})`;
      })
      .join('; '),
    impactIfResolved: PROPERTY_CONFLICT_IMPACT,
  }));
}
