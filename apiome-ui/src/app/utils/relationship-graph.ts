/**
 * Build nodes and edges for a schema relationship graph (#322).
 * From classes with their properties, extract $ref / items.$ref and produce graph data.
 */

export interface RelationshipGraphNode {
  id: string;
  name: string;
}

export interface RelationshipGraphEdge {
  source: string;
  target: string;
}

export interface RelationshipGraphData {
  nodes: RelationshipGraphNode[];
  edges: RelationshipGraphEdge[];
}

function extractClassNameFromRef(ref: string): string | null {
  if (typeof ref !== 'string') return null;
  if (ref.includes('/')) {
    const parts = ref.split('/');
    return parts[parts.length - 1] || null;
  }
  return ref;
}

/** Collect all schema class names referenced from a schema object ($ref, items.$ref, allOf, anyOf, oneOf) */
function getAllRefTargets(data: Record<string, unknown> | null): string[] {
  if (!data || typeof data !== 'object') return [];
  const out: string[] = [];

  const add = (ref: unknown) => {
    if (typeof ref === 'string') {
      const name = extractClassNameFromRef(ref);
      if (name && name !== '__unassigned__') out.push(name);
    }
  };

  if (data.$ref) add(data.$ref);

  const type = Array.isArray(data.type) ? (data.type as string[]).find((t) => t !== 'null') : data.type;
  if (type === 'array' && data.items && typeof data.items === 'object') {
    const items = data.items as Record<string, unknown>;
    if (items.$ref) add(items.$ref);
    for (const key of ['allOf', 'anyOf', 'oneOf'] as const) {
      const arr = items[key];
      if (Array.isArray(arr)) {
        for (const item of arr) {
          if (item && typeof item === 'object' && (item as Record<string, unknown>).$ref) {
            add((item as Record<string, unknown>).$ref);
          }
        }
      }
    }
  }

  for (const key of ['allOf', 'anyOf', 'oneOf'] as const) {
    const arr = data[key];
    if (Array.isArray(arr)) {
      for (const item of arr) {
        if (item && typeof item === 'object' && (item as Record<string, unknown>).$ref) {
          add((item as Record<string, unknown>).$ref);
        }
      }
    }
  }

  return out;
}

/** Class shape as returned by getClassesForVersion + getPropertiesForClass */
export interface ClassWithProperties {
  id: string;
  name: string;
  properties?: Array<{ id: string; name: string; data: unknown }>;
}

/**
 * Build graph nodes and edges from version classes and their properties.
 * Nodes = classes; edges = property $ref / items.$ref to another class.
 */
export function buildRelationshipGraphData(classes: ClassWithProperties[]): RelationshipGraphData {
  const nameToId = new Map<string, string>();
  for (const cls of classes) {
    if (cls.name) nameToId.set(cls.name, cls.id);
  }

  const nodes: RelationshipGraphNode[] = classes.map((cls) => ({
    id: cls.id,
    name: cls.name || cls.id,
  }));

  const edgeSet = new Set<string>();
  const edges: RelationshipGraphEdge[] = [];

  for (const cls of classes) {
    const props = cls.properties || [];
    for (const prop of props) {
      const raw =
        (prop as Record<string, unknown>).data ??
        (prop as Record<string, unknown>).schema ??
        (prop as Record<string, unknown>).schema_data;
      const data = (typeof raw === 'string' ? (() => { try { return JSON.parse(raw) as Record<string, unknown>; } catch { return {}; } })() : (raw as Record<string, unknown>)) || {};
      const targetNames = getAllRefTargets(data);
      for (const targetName of targetNames) {
        const targetId = nameToId.get(targetName);
        if (!targetId || targetId === cls.id) continue;
        const key = `${cls.id}\t${targetId}`;
        if (edgeSet.has(key)) continue;
        edgeSet.add(key);
        edges.push({ source: cls.id, target: targetId });
      }
    }
  }

  return { nodes, edges };
}
