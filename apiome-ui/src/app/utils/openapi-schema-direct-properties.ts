/**
 * Shared extraction of "direct" JSON Schema properties for OpenAPI import.
 * Merges top-level `properties` / `required` with inline fragments from `allOf`
 * (excluding `$ref` items and JSON Schema `if` subschemas).
 */

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** OpenAPI / JSON Schema property defs are intentionally untyped. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type SchemaPropertyMap = Record<string, any>;

export function extractDirectProperties(schema: unknown): { properties: SchemaPropertyMap; required: string[] } {
  const result: { properties: SchemaPropertyMap; required: string[] } = {
    properties: {},
    required: [],
  };
  if (!isPlainObject(schema)) return result;

  const topProps = schema.properties;
  if (isPlainObject(topProps)) {
    Object.assign(result.properties, topProps);
  }
  if (Array.isArray(schema.required)) {
    for (const r of schema.required) {
      if (typeof r === 'string') result.required.push(r);
    }
  }

  const allOf = schema.allOf;
  if (Array.isArray(allOf)) {
    for (const item of allOf) {
      if (!isPlainObject(item)) continue;
      if ('$ref' in item) continue;
      if (item.if !== undefined) continue;
      const fragProps = item.properties;
      if (isPlainObject(fragProps)) {
        Object.assign(result.properties, fragProps);
      }
      if (Array.isArray(item.required)) {
        for (const r of item.required) {
          if (typeof r === 'string') result.required.push(r);
        }
      }
    }
  }

  return result;
}
