/**
 * Detect incompatible type assignments (#585): within a schema, the same property
 * is assigned different types (e.g. via allOf branches or top-level vs allOf).
 * Reported in the conflict detection section as type_mismatch.
 */

import type { ImportConflict } from '../components/ade/dashboard/ConflictReport';

/**
 * Collect every (propertyName, propSchema) from a schema without merging:
 * top-level properties plus each allOf branch that defines properties.
 * So the same property can appear multiple times with different definitions.
 */
function getPropertyOccurrences(schema: any): Array<{ propName: string; propSchema: any }> {
  const out: Array<{ propName: string; propSchema: any }> = [];
  if (!schema || typeof schema !== 'object') return out;

  if (schema.properties && typeof schema.properties === 'object') {
    for (const [propName, propSchema] of Object.entries(schema.properties)) {
      if (propSchema != null && typeof propSchema === 'object') {
        out.push({ propName, propSchema });
      }
    }
  }

  if (Array.isArray(schema.allOf)) {
    for (const item of schema.allOf) {
      if (!item || typeof item !== 'object') continue;
      if (item.$ref != null || item.if !== undefined) continue;
      if (item.properties && typeof item.properties === 'object') {
        for (const [propName, propSchema] of Object.entries(item.properties)) {
          if (propSchema != null && typeof propSchema === 'object') {
            out.push({ propName, propSchema });
          }
        }
      }
    }
  }

  return out;
}

/**
 * Single type signature string for comparison (type, format, array item type, $ref).
 */
function typeSignature(propSchema: any): string {
  if (!propSchema || typeof propSchema !== 'object') return 'unknown';
  if (propSchema.$ref) return `$ref:${String(propSchema.$ref).split('/').pop() ?? ''}`;
  const t = propSchema.type ?? 'any';
  const f = propSchema.format ? `:${propSchema.format}` : '';
  if (t === 'array') {
    const item = propSchema.items;
    const itemSig = item?.$ref ? `$ref:${String(item.$ref).split('/').pop()}` : item?.type ?? 'any';
    return `array<${itemSig}>${f}`;
  }
  return `${t}${f}`;
}

/**
 * Human-readable type description for conflict detail.
 */
function describeType(propSchema: any): string {
  if (!propSchema || typeof propSchema !== 'object') return 'unknown';
  if (propSchema.$ref) return `$ref (${String(propSchema.$ref).split('/').pop() ?? ''})`;
  const t = propSchema.type ?? 'any';
  const f = propSchema.format ? ` ${propSchema.format}` : '';
  if (t === 'array') {
    const item = propSchema.items;
    const itemDesc = item?.$ref ? `$ref` : item?.type ?? 'any';
    return `array<${itemDesc}>${f}`;
  }
  return `${t}${f}`;
}

export interface TypeMismatchInput {
  /** OpenAPI document (components.schemas or definitions) */
  document: any;
  /** Schema names to consider (e.g. all or selected) */
  schemaNames: string[];
}

/**
 * Detect incompatible type assignments (#585): within each schema, find properties
 * that are assigned more than one distinct type (e.g. string in one allOf branch,
 * integer in another). Returns one ImportConflict per (schema, property) with
 * type mismatch.
 */
export function detectTypeMismatches(input: TypeMismatchInput): ImportConflict[] {
  const { document, schemaNames } = input;
  const schemas = document?.components?.schemas || document?.definitions || {};
  const nameSet = new Set(schemaNames);
  if (nameSet.size === 0) return [];

  const conflicts: ImportConflict[] = [];

  for (const schemaName of nameSet) {
    const schema = schemas[schemaName];
    if (!schema) continue;

    const occurrences = getPropertyOccurrences(schema);
    // propertyName -> set of type signatures
    const byProp = new Map<string, Set<string>>();
    // propertyName -> sample definitions for description (signature -> describeType)
    const samples = new Map<string, Map<string, string>>();

    for (const { propName, propSchema } of occurrences) {
      const sig = typeSignature(propSchema);
      const desc = describeType(propSchema);
      if (!byProp.has(propName)) {
        byProp.set(propName, new Set());
        samples.set(propName, new Map());
      }
      byProp.get(propName)!.add(sig);
      samples.get(propName)!.set(sig, desc);
    }

    for (const [propName, sigs] of byProp) {
      if (sigs.size < 2) continue;

      const typeList = Array.from(samples.get(propName)!.values());
      const detail =
        typeList.length <= 4
          ? typeList.join(' vs ')
          : `${typeList.slice(0, 3).join(', ')}, and ${typeList.length - 3} more`;

      conflicts.push({
        kind: 'type_mismatch',
        schemaName,
        message: `Property "${propName}" has incompatible type assignments within this schema.`,
        detail,
        impactIfResolved:
          'The chosen type will be applied; property type will be updated in the imported schema.',
      });
    }
  }

  return conflicts;
}
