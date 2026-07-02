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

export interface PropertyConflictInput {
  /** OpenAPI document (components.schemas or definitions) */
  document: any;
  /** Schema names to consider (e.g. all or selected) */
  schemaNames: string[];
}

/**
 * Detect property definition conflicts (#583): for each property name that appears
 * in more than one schema with different definitions, returns one ImportConflict.
 */
export function detectPropertyConflicts(input: PropertyConflictInput): ImportConflict[] {
  const { document, schemaNames } = input;
  const schemas = document?.components?.schemas || document?.definitions || {};
  const nameSet = new Set(schemaNames);
  if (nameSet.size === 0) return [];

  // propertyName -> { signature -> { schemaNames, sampleSchema for description } }
  const byPropName = new Map<
    string,
    Map<string, { schemaNames: string[]; sample: any }>
  >();

  for (const schemaName of nameSet) {
    const schema = schemas[schemaName];
    if (!schema) continue;
    const properties = extractDirectProperties(schema);
    for (const [propName, propSchema] of Object.entries(properties)) {
      if (!propSchema || typeof propSchema !== 'object') continue;
      const sig = propertyDefinitionSignature(propSchema);
      if (!byPropName.has(propName)) {
        byPropName.set(propName, new Map());
      }
      const bySig = byPropName.get(propName)!;
      if (!bySig.has(sig)) {
        bySig.set(sig, { schemaNames: [], sample: propSchema });
      }
      const entry = bySig.get(sig)!;
      if (!entry.schemaNames.includes(schemaName)) {
        entry.schemaNames.push(schemaName);
      }
    }
  }

  const conflicts: ImportConflict[] = [];
  for (const [propName, bySig] of byPropName) {
    const definitions = Array.from(bySig.entries());
    if (definitions.length < 2) continue; // same definition everywhere or only one schema

    const allSchemaNames = definitions.flatMap(([, e]) => e.schemaNames);
    const uniqueSchemaNames = Array.from(new Set(allSchemaNames));
    const parts = definitions.map(([_, e]) => {
      const desc = describeDefinition(e.sample);
      const names = e.schemaNames.slice(0, 3).join(', ');
      const more = e.schemaNames.length > 3 ? ` +${e.schemaNames.length - 3} more` : '';
      return `${names}${more} (${desc})`;
    });
    const firstSchema = uniqueSchemaNames[0];
    conflicts.push({
      kind: 'property_conflict',
      schemaName: firstSchema,
      message: `Property "${propName}" has incompatible definitions across schemas.`,
      detail: parts.join('; '),
      impactIfResolved:
        'The chosen property definition will be applied; the other will be discarded or merged per strategy.',
    });
  }

  return conflicts;
}
