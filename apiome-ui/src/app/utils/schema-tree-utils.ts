/**
 * Schema tree utilities for import preview (#576).
 * Builds a hierarchical view of schemas from $ref relationships.
 */

export interface SchemaTreeNode {
  name: string;
  children: SchemaTreeNode[];
}

/**
 * Extract all schema reference names from a schema object (recursive).
 * Handles $ref in properties, items, allOf, oneOf, anyOf, etc.
 */
export function extractSchemaReferences(schema: unknown): string[] {
  const refs: string[] = [];

  const findRefs = (obj: unknown) => {
    if (obj == null || typeof obj !== 'object') return;

    if (
      typeof obj === 'object' &&
      '$ref' in obj &&
      typeof (obj as { $ref: unknown }).$ref === 'string'
    ) {
      const ref = (obj as { $ref: string }).$ref;
      const refName = ref.split('/').pop();
      if (refName && !refs.includes(refName)) {
        refs.push(refName);
      }
    }

    for (const key in obj as Record<string, unknown>) {
      if (Object.prototype.hasOwnProperty.call(obj, key)) {
        findRefs((obj as Record<string, unknown>)[key]);
      }
    }
  };

  findRefs(schema);
  return refs;
}

/**
 * Result for one reference from a schema (for relationship diagram edge labels).
 */
export interface SchemaRefEdge {
  refName: string;
  /** Property name when ref is under schema.properties[prop]; "items" for array items; null for allOf/oneOf/anyOf */
  propertyName: string | null;
}

/**
 * Extract schema reference edges with property context (for relationship diagram #578).
 * Returns each $ref with the property name that leads to it when under properties, or "items" for array items.
 */
export function extractSchemaReferenceEdges(schema: unknown): SchemaRefEdge[] {
  const result: SchemaRefEdge[] = [];

  const findRefs = (obj: unknown, propertyName: string | null) => {
    if (obj == null || typeof obj !== 'object') return;

    if (
      typeof obj === 'object' &&
      '$ref' in obj &&
      typeof (obj as { $ref: unknown }).$ref === 'string'
    ) {
      const ref = (obj as { $ref: string }).$ref;
      const refName = ref.split('/').pop();
      if (refName) {
        result.push({ refName, propertyName });
      }
      return;
    }

    const rec = obj as Record<string, unknown>;
    if (rec.properties && typeof rec.properties === 'object') {
      const props = rec.properties as Record<string, unknown>;
      for (const key of Object.keys(props)) {
        findRefs(props[key], key);
      }
    }
    if (rec.items && typeof rec.items === 'object') {
      findRefs(rec.items, 'items');
    }
    if (Array.isArray(rec.allOf)) {
      rec.allOf.forEach((item) => findRefs(item, null));
    }
    if (Array.isArray(rec.oneOf)) {
      rec.oneOf.forEach((item) => findRefs(item, null));
    }
    if (Array.isArray(rec.anyOf)) {
      rec.anyOf.forEach((item) => findRefs(item, null));
    }
    // Fallback: any other key that might contain $ref (e.g. additionalProperties)
    for (const key of Object.keys(rec)) {
      if (key === 'properties' || key === 'items' || key === 'allOf' || key === 'oneOf' || key === 'anyOf') continue;
      findRefs(rec[key], null);
    }
  };

  findRefs(schema, null);
  return result;
}

/**
 * One edge in the relationship diagram (for unit testing #578).
 */
export interface RelationshipDiagramEdge {
  source: string;
  target: string;
  label: string;
}

/**
 * Build relationship diagram edges from schema object and filtered schema names (#578).
 * Only includes edges where both source and target are in filteredSchemaNames.
 * Labels show the property name(s) that reference the target; multiple properties
 * are combined (e.g. "category, tags" or "first, +2").
 */
export function buildRelationshipDiagramEdges(
  schemaObj: Record<string, unknown>,
  filteredSchemaNames: string[]
): RelationshipDiagramEdge[] {
  if (filteredSchemaNames.length === 0) return [];

  const schemaNameSet = new Set(filteredSchemaNames);
  const edgeMap = new Map<string, { source: string; target: string; labels: string[] }>();

  filteredSchemaNames.forEach((name) => {
    const schema = schemaObj[name];
    const refEdges = extractSchemaReferenceEdges(schema);

    refEdges.forEach(({ refName, propertyName }) => {
      if (!schemaNameSet.has(refName)) return;
      const key = `${name}\0${refName}`;
      const label = propertyName ?? 'ref';
      const existing = edgeMap.get(key);
      if (existing) {
        if (!existing.labels.includes(label)) existing.labels.push(label);
      } else {
        edgeMap.set(key, { source: name, target: refName, labels: [label] });
      }
    });
  });

  return Array.from(edgeMap.values()).map(({ source, target, labels }) => ({
    source,
    target,
    label: labels.length <= 2 ? labels.join(', ') : `${labels[0]}, +${labels.length - 1}`,
  }));
}

/**
 * Build a forest of schema trees. Each root is a schema name; children are
 * schemas it references via $ref. Cycles are avoided per path.
 */
export function buildSchemaTree(
  schemaObj: Record<string, unknown>,
  schemaNames: string[],
  nameFilter?: (name: string) => boolean
): SchemaTreeNode[] {
  const nameSet = new Set(schemaNames);
  const roots = nameFilter ? schemaNames.filter(nameFilter) : schemaNames;

  function buildNode(schemaName: string, path: Set<string>): SchemaTreeNode {
    const schema = schemaObj[schemaName];
    const refs = schema ? extractSchemaReferences(schema) : [];
    const childRefs = refs.filter((r) => nameSet.has(r) && !path.has(r));
    const childPath = new Set(path);
    childPath.add(schemaName);
    const children = childRefs.map((refName) => buildNode(refName, childPath));
    return { name: schemaName, children };
  }

  return roots.map((name) => buildNode(name, new Set()));
}

/**
 * Schema selection info for dependency resolution (#579).
 * Used to determine if a schema can be deselected (not referenced by others).
 */
export interface SchemaSelectionInfo {
  name: string;
  selected: boolean;
  exists: boolean;
}

/**
 * Get all schema names that the given schema references (transitively),
 * only from schemaObj. Used for auto-selecting dependencies on import (#579).
 */
export function getTransitiveDependencies(
  schemaName: string,
  schemaObj: Record<string, unknown>,
  visited = new Set<string>()
): string[] {
  if (visited.has(schemaName)) return [];
  visited.add(schemaName);
  const schema = schemaObj[schemaName];
  if (!schema) return [];
  const refs = extractSchemaReferences(schema);
  const result: string[] = [];
  for (const ref of refs) {
    if (schemaObj[ref]) {
      if (!visited.has(ref)) {
        result.push(ref);
        result.push(...getTransitiveDependencies(ref, schemaObj, visited));
      }
    }
  }
  return [...new Set(result)];
}

/**
 * True if any other selected (non-existing) schema references schemaName.
 * Used to prevent deselecting schemas that are required by others (#579).
 */
export function isReferencedBySelectedSchemas(
  schemaName: string,
  schemas: SchemaSelectionInfo[],
  schemaObj: Record<string, unknown>
): boolean {
  const selectedNames = schemas.filter((s) => s.selected && !s.exists).map((s) => s.name);
  for (const name of selectedNames) {
    if (name === schemaName) continue;
    const refs = extractSchemaReferences(schemaObj[name] ?? {});
    if (refs.includes(schemaName)) return true;
  }
  return false;
}

/** Schema type for filtering (#580). Composition takes precedence over JSON Schema type. */
export type SchemaDisplayType =
  | 'object'
  | 'array'
  | 'string'
  | 'number'
  | 'integer'
  | 'boolean'
  | 'allOf'
  | 'oneOf'
  | 'anyOf'
  | 'enum'
  | 'null'
  | 'unknown';

/**
 * Derive a display type from a schema for search/filter (#580).
 * Composition (allOf/oneOf/anyOf) takes precedence; then enum; then type.
 */
export function getSchemaType(schema: unknown): SchemaDisplayType {
  if (schema == null || typeof schema !== 'object') return 'unknown';
  const s = schema as Record<string, unknown>;
  if (Array.isArray(s.allOf) && s.allOf.length > 0) return 'allOf';
  if (Array.isArray(s.oneOf) && s.oneOf.length > 0) return 'oneOf';
  if (Array.isArray(s.anyOf) && s.anyOf.length > 0) return 'anyOf';
  if (Array.isArray(s.enum) && s.enum.length > 0) return 'enum';
  const t = s.type;
  if (t === 'object' || t === 'array' || t === 'string' || t === 'number' || t === 'integer' || t === 'boolean' || t === 'null') {
    return t as SchemaDisplayType;
  }
  if (s.properties && typeof s.properties === 'object') return 'object';
  return 'unknown';
}

/**
 * Extract tags from a schema for search/filter (#580).
 * Supports x-tags (array), x-tag (string), and tags (array).
 */
export function getSchemaTags(schema: unknown): string[] {
  if (schema == null || typeof schema !== 'object') return [];
  const s = schema as Record<string, unknown>;
  const out: string[] = [];
  if (Array.isArray(s['x-tags'])) {
    s['x-tags'].forEach((v) => {
      if (typeof v === 'string' && v.trim()) out.push(v.trim());
    });
  }
  if (typeof s['x-tag'] === 'string' && s['x-tag'].trim()) {
    out.push((s['x-tag'] as string).trim());
  }
  if (Array.isArray(s.tags)) {
    s.tags.forEach((v) => {
      if (typeof v === 'string' && v.trim()) out.push(v.trim());
    });
  }
  return [...new Set(out)];
}
