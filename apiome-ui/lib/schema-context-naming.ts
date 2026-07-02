/**
 * Smart class naming from schema context (#753).
 * Derives a preferred class name from OpenAPI/JSON Schema fields when available.
 */

/**
 * Returns a valid identifier-like string (letters, digits, underscores).
 * Trims and collapses internal spaces to a single separator; keeps alphanumeric and _.
 */
function toIdentifierLike(str: string): string {
  if (!str || typeof str !== 'string') return '';
  return str
    .trim()
    .replace(/\s+/g, ' ')
    .replace(/[^a-zA-Z0-9_\s]/g, '')
    .trim();
}

/**
 * Derive a smart class name from schema context.
 * Priority: x-class-name / x-className > title > schema key.
 */
export function getSmartClassName(schemaKey: string, schema: any): string {
  if (!schemaKey || typeof schemaKey !== 'string') return 'Unnamed';
  const key = schemaKey.trim();
  if (!schema || typeof schema !== 'object') return key;

  const ext = (name: string) => {
    const v = schema[name];
    if (v != null && typeof v === 'string' && v.trim()) return toIdentifierLike(v.trim()) || null;
    return null;
  };

  const fromTitle = () => {
    const t = schema.title;
    if (t != null && typeof t === 'string' && t.trim()) return toIdentifierLike(t.trim()) || null;
    return null;
  };

  const fromExt = ext('x-class-name') ?? ext('x-className') ?? ext('x_class_name');
  if (fromExt) return fromExt.replace(/\s+/g, ' ');
  const fromTitleVal = fromTitle();
  if (fromTitleVal) return fromTitleVal.replace(/\s+/g, ' ');
  return key;
}
