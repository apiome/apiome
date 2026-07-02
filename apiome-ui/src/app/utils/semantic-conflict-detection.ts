/**
 * Detect semantically incompatible constraints (#586): within a schema (and nested
 * schemas), constraints that can never be satisfied together (e.g. minLength > maxLength,
 * minimum > maximum, empty enum). Reported in the conflict detection section as semantic_conflict.
 */

import type { ImportConflict } from '../components/ade/dashboard/ConflictReport';

export interface SemanticConflictInput {
  /** OpenAPI document (components.schemas or definitions) */
  document: any;
  /** Schema names to consider (e.g. all or selected) */
  schemaNames: string[];
}

type Issue = { path: string; description: string };

/**
 * Check a single schema node for logically incompatible constraints.
 * Returns a list of issue descriptions (path + message). Path is relative (e.g. "name", "items").
 */
function checkSchemaNode(schema: any, path: string): Issue[] {
  const issues: Issue[] = [];
  if (!schema || typeof schema !== 'object') return issues;

  // String: minLength > maxLength
  const minLen = schema.minLength;
  const maxLen = schema.maxLength;
  if (
    typeof minLen === 'number' &&
    typeof maxLen === 'number' &&
    minLen > maxLen
  ) {
    issues.push({
      path,
      description: `minLength (${minLen}) is greater than maxLength (${maxLen}); no string can satisfy both.`,
    });
  }

  // Number/integer: minimum > maximum
  const min = schema.minimum;
  const max = schema.maximum;
  if (typeof min === 'number' && typeof max === 'number' && min > max) {
    issues.push({
      path,
      description: `minimum (${min}) is greater than maximum (${max}); no value can satisfy both.`,
    });
  }

  // exclusiveMinimum (number in JSON Schema 6+) vs maximum
  const exclMin = schema.exclusiveMinimum;
  if (typeof exclMin === 'number' && typeof max === 'number' && exclMin >= max) {
    issues.push({
      path,
      description: `exclusiveMinimum (${exclMin}) is >= maximum (${max}); no value can satisfy both.`,
    });
  }

  // minimum vs exclusiveMaximum (number in JSON Schema 6+)
  const exclMax = schema.exclusiveMaximum;
  if (typeof min === 'number' && typeof exclMax === 'number' && min >= exclMax) {
    issues.push({
      path,
      description: `minimum (${min}) is >= exclusiveMaximum (${exclMax}); no value can satisfy both.`,
    });
  }

  // Array: minItems > maxItems
  const minItems = schema.minItems;
  const maxItems = schema.maxItems;
  if (
    typeof minItems === 'number' &&
    typeof maxItems === 'number' &&
    minItems > maxItems
  ) {
    issues.push({
      path,
      description: `minItems (${minItems}) is greater than maxItems (${maxItems}); no array length can satisfy both.`,
    });
  }

  // Object: minProperties > maxProperties
  const minProps = schema.minProperties;
  const maxProps = schema.maxProperties;
  if (
    typeof minProps === 'number' &&
    typeof maxProps === 'number' &&
    minProps > maxProps
  ) {
    issues.push({
      path,
      description: `minProperties (${minProps}) is greater than maxProperties (${maxProps}); no object can satisfy both.`,
    });
  }

  // Empty enum: no value can satisfy
  if (Array.isArray(schema.enum) && schema.enum.length === 0) {
    issues.push({
      path,
      description: 'enum is empty; no value can satisfy this constraint.',
    });
  }

  return issues;
}

/**
 * Recursively collect all schema nodes that can carry constraints (no $ref expansion).
 * Visits: root, properties.*, items, additionalProperties, allOf/oneOf/anyOf branches.
 * pathPrefix is the path so far (e.g. "name", "items", "allOf[0]").
 */
function collectConstraintNodes(
  schema: any,
  pathPrefix: string,
  visited: Set<any>
): Array<{ schema: any; path: string }> {
  const out: Array<{ schema: any; path: string }> = [];
  if (!schema || typeof schema !== 'object') return out;
  if (visited.has(schema)) return out;
  visited.add(schema);

  out.push({ schema, path: pathPrefix || 'root' });

  if (schema.properties && typeof schema.properties === 'object') {
    for (const [key, sub] of Object.entries(schema.properties)) {
      if (sub && typeof sub === 'object' && !(sub as any).$ref) {
        out.push(
          ...collectConstraintNodes(
            sub,
            pathPrefix ? `${pathPrefix}.${key}` : key,
            visited
          )
        );
      }
    }
  }

  if (schema.items && typeof schema.items === 'object') {
    const items = Array.isArray(schema.items) ? schema.items : [schema.items];
    items.forEach((item: any, i: number) => {
      if (item && typeof item === 'object' && !item.$ref) {
        const seg = Array.isArray(schema.items)
          ? `items[${i}]`
          : 'items';
        const path = pathPrefix ? `${pathPrefix}.${seg}` : seg;
        out.push(...collectConstraintNodes(item, path, visited));
      }
    });
  }

  if (schema.additionalProperties && typeof schema.additionalProperties === 'object' && !(schema.additionalProperties as any).$ref) {
    out.push(
      ...collectConstraintNodes(
        schema.additionalProperties,
        pathPrefix ? `${pathPrefix}.additionalProperties` : 'additionalProperties',
        visited
      )
    );
  }

  for (const key of ['allOf', 'oneOf', 'anyOf'] as const) {
    const arr = schema[key];
    if (!Array.isArray(arr)) continue;
    arr.forEach((item: any, i: number) => {
      if (item && typeof item === 'object' && !item.$ref) {
        const path = pathPrefix ? `${pathPrefix}.${key}[${i}]` : `${key}[${i}]`;
        out.push(...collectConstraintNodes(item, path, visited));
      }
    });
  }

  return out;
}

/**
 * Detect logically incompatible constraints (#586): for each schema, walk all constraint-bearing
 * nodes and report one ImportConflict per schema that has at least one such issue.
 */
export function detectSemanticConflicts(
  input: SemanticConflictInput
): ImportConflict[] {
  const { document, schemaNames } = input;
  const schemas = document?.components?.schemas || document?.definitions || {};
  const nameSet = new Set(schemaNames);
  if (nameSet.size === 0) return [];

  const conflicts: ImportConflict[] = [];

  for (const schemaName of nameSet) {
    const schema = schemas[schemaName];
    if (!schema) continue;

    const visited = new Set<any>();
    const nodes = collectConstraintNodes(schema, '', visited);
    const allIssues: Issue[] = [];

    for (const { schema: node, path } of nodes) {
      allIssues.push(...checkSchemaNode(node, path));
    }

    if (allIssues.length === 0) continue;

    const detail =
      allIssues.length <= 5
        ? allIssues.map((i) => (i.path === 'root' ? i.description : `At "${i.path}": ${i.description}`)).join(' ')
        : allIssues
            .slice(0, 4)
            .map((i) => (i.path === 'root' ? i.description : `At "${i.path}": ${i.description}`))
            .join(' ') + ` (and ${allIssues.length - 4} more)`;

    conflicts.push({
      kind: 'semantic_conflict',
      schemaName,
      message: `Schema has logically incompatible constraints that can never be satisfied together.`,
      detail,
      impactIfResolved:
        'The chosen constraints or semantics will be applied; conflicting rules will be updated.',
    });
  }

  return conflicts;
}
