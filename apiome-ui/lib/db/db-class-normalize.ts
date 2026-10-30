/**
 * Turn a stored class back into the importer's normalized shape, so it can be merged with an
 * imported class (#588 class import, #591 additive merge in the Import wizard).
 */

import type { NormalizedClass, NormalizedProperty } from '../importers';

/**
 * Convert a DB class row with its property links to a {@link NormalizedClass}.
 *
 * Accepts the shape returned by `getClassWithPropertiesAndTags` and `getClassesWithPropertiesAndTagsTx`:
 * the class columns plus `properties`, a flat list of `class_properties` rows whose `parent_id`
 * links a nested property to its parent. Nested properties become `children`.
 *
 * @param raw - The class row: `name`, `description`, `schema` (object or JSON string) and `properties`.
 * @returns The normalized class (root properties in the order given, `schema` defaulting to an object).
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- DB rows are untyped JSON
export function dbClassToNormalized(raw: any): NormalizedClass {
  const schema = typeof raw.schema === 'string' ? JSON.parse(raw.schema) : raw.schema;
  const props = raw.properties || [];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- DB rows are untyped JSON
  const byParent = new Map<string | null, any[]>();
  byParent.set(null, []);
  for (const p of props) {
    const key = p.parent_id ?? null;
    if (!byParent.has(key)) byParent.set(key, []);
    byParent.get(key)!.push(p);
  }
  function buildChildren(parentId: string | null): NormalizedProperty[] {
    const list = byParent.get(parentId) || [];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- DB rows are untyped JSON
    return list.map((p: any) => ({
      name: p.name,
      data: p.data || {},
      description: p.description ?? undefined,
      children: byParent.has(p.id) && byParent.get(p.id)!.length > 0 ? buildChildren(p.id) : undefined,
    }));
  }
  const rootChildren = buildChildren(null);
  return {
    name: raw.name,
    description: raw.description ?? undefined,
    schema: schema || { type: 'object' },
    properties: rootChildren,
  };
}
