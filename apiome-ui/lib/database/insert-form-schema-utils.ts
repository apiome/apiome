/**
 * Utilities for building insert form state from JSON Schema (class_schema).
 * Used by the database insert modal to derive initial form data, property types, enum, pattern, and money detection.
 */

export type SchemaProperty = Record<string, unknown>;

export function getPropertyType(propSchema: SchemaProperty): string {
  const t = propSchema.type;
  if (typeof t === 'string') return t;
  if (Array.isArray(t) && t.length > 0) {
    const first = t.find((x) => x !== 'null');
    return typeof first === 'string' ? first : 'string';
  }
  return 'string';
}

export function getEnumOptions(propSchema: SchemaProperty): unknown[] {
  const e = propSchema.enum;
  return Array.isArray(e) ? e : [];
}

export function getPattern(propSchema: SchemaProperty): string | undefined {
  const p = propSchema.pattern;
  return typeof p === 'string' ? p : undefined;
}

/** True if the property schema allows null (e.g. type: ["string", "null"]). */
export function isNullable(propSchema: SchemaProperty): boolean {
  const t = propSchema.type;
  if (Array.isArray(t)) return t.includes('null');
  return false;
}

export function isMoneyField(propSchema: SchemaProperty, key: string): boolean {
  const format = (propSchema.format as string) || '';
  const keyLower = key.toLowerCase();
  const moneyFormats = ['currency', 'amount', 'money'];
  const moneyKeys = ['price', 'amount', 'cost', 'money', 'currency', 'total', 'subtotal', 'fee'];
  return (
    moneyFormats.some((f) => format.toLowerCase().includes(f)) ||
    moneyKeys.some((k) => keyLower.includes(k))
  );
}

/** True if the property is a UUID (format or key name). */
export function isUuidField(propSchema: SchemaProperty, key: string): boolean {
  const format = (propSchema.format as string) || '';
  if (format.toLowerCase() === 'uuid') return true;
  const keyLower = key.toLowerCase();
  return keyLower === 'id' || keyLower.endsWith('_id') || keyLower.endsWith('_uuid') || keyLower.includes('uuid');
}

/** True if the property is a timestamp (format date-time or default CURRENT_TIMESTAMP/NOW()). */
export function isTimestampField(propSchema: SchemaProperty, key: string): boolean {
  const format = (propSchema.format as string) || '';
  if (format === 'date-time' || format === 'date') return true;
  const kind = getTimestampDefaultKind(propSchema);
  if (kind !== null) return true;
  const keyLower = key.toLowerCase();
  return keyLower.includes('timestamp') || keyLower.includes('created_at') || keyLower.includes('updated_at');
}

/**
 * Parse default/const to detect timestamp semantics: CURRENT_TIMESTAMP, NOW(), or ISO.
 * Used to decide how to generate a value when the user clicks "Generate".
 */
export function getTimestampDefaultKind(propSchema: SchemaProperty): 'CURRENT_TIMESTAMP' | 'NOW()' | 'iso' | null {
  const def = propSchema.default !== undefined ? propSchema.default : propSchema.const;
  if (def === undefined || def === null) return null;
  const s = String(def).trim().toUpperCase();
  if (s === 'CURRENT_TIMESTAMP') return 'CURRENT_TIMESTAMP';
  if (s === 'NOW()') return 'NOW()';
  if (s === 'NOW') return 'NOW()';
  // ISO-like default (e.g. "2024-01-01T00:00:00.000Z")
  if (typeof def === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/.test(def)) return 'iso';
  return null;
}

/**
 * Build initial form data from a JSON Schema (e.g. class_schema.schema).
 * Uses default or const when present; otherwise empty value by type.
 * Deep-clones object/array defaults so form state is independent.
 */
export function getInitialFormData(schema: Record<string, unknown>): Record<string, unknown> {
  const props = schema.properties as Record<string, SchemaProperty> | undefined;
  if (!props || typeof props !== 'object') return {};
  const out: Record<string, unknown> = {};
  for (const [key, propSchema] of Object.entries(props)) {
    if (typeof propSchema !== 'object' || propSchema === null) continue;
    const def = propSchema.default !== undefined ? propSchema.default : propSchema.const;
    if (def !== undefined) {
      out[key] =
        typeof def === 'object' && def !== null
          ? JSON.parse(JSON.stringify(def))
          : def;
      continue;
    }
    const type = getPropertyType(propSchema);
    if (type === 'string') out[key] = '';
    else if (type === 'number' || type === 'integer') out[key] = undefined;
    else if (type === 'boolean') out[key] = false;
    else if (type === 'array') out[key] = [];
    else if (type === 'object') out[key] = {};
    else out[key] = '';
  }
  return out;
}

export function getOrderedPropertyEntries(
  schema: Record<string, unknown>
): [string, SchemaProperty][] {
  const props = schema.properties as Record<string, SchemaProperty> | undefined;
  if (!props || typeof props !== 'object') return [];
  return Object.entries(props).filter(
    (entry): entry is [string, SchemaProperty] =>
      typeof entry[1] === 'object' && entry[1] !== null
  );
}
