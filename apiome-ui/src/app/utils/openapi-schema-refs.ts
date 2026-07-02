/**
 * Pure helpers for walking JSON Schema / OpenAPI schema objects and collecting
 * `#/components/schemas/...` ref targets. Kept separate from openapi.ts so Jest
 * and lightweight callers avoid the Handlebars template loader (#156).
 */

export function extractClassNameFromRef(ref: string): string | null {
  if (!ref) return null;

  if (ref.includes('/')) {
    const parts = ref.split('/');
    return parts[parts.length - 1] || null;
  }
  return ref;
}

/** Recursively finds all class names referenced in a schema object via $ref */
export function findReferencedClasses(obj: any, refs: Set<string>): void {
  if (!obj || typeof obj !== 'object') return;

  if (obj.$ref && typeof obj.$ref === 'string') {
    const className = extractClassNameFromRef(obj.$ref);
    if (className) refs.add(className);
  }

  for (const key in obj) {
    if (Object.prototype.hasOwnProperty.call(obj, key)) {
      findReferencedClasses(obj[key], refs);
    }
  }
}
