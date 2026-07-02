/**
 * Reserved name detection for import (#756).
 * Prevents conflicts with JavaScript/TypeScript keywords, JSON Schema keywords,
 * and built-in object properties when used as class or property names.
 */

import type { NormalizedClass, NormalizedProperty } from './index';

/** Lowercase reserved identifiers (checked case-insensitively). */
const RESERVED_LOWER = new Set<string>([
  // JavaScript/TypeScript keywords
  'break', 'case', 'catch', 'class', 'const', 'continue', 'debugger', 'default',
  'delete', 'do', 'else', 'export', 'extends', 'finally', 'for', 'function',
  'if', 'import', 'in', 'instanceof', 'new', 'return', 'super', 'switch',
  'this', 'throw', 'try', 'typeof', 'var', 'void', 'while', 'with', 'yield',
  'let', 'static', 'await', 'enum', 'implements', 'interface', 'package',
  'private', 'protected', 'public', 'async', 'of',
  // JSON Schema / OpenAPI keywords (problematic as property names)
  'type', 'enum', 'const', 'default', 'if', 'then', 'else', 'allof', 'anyof',
  'oneof', 'not', 'ref', 'id', 'schema', 'definitions', 'properties',
  'items', 'required', 'description', 'title', 'examples', 'nullable',
  'format', 'minimum', 'maximum', 'exclusiveminimum', 'exclusivemaximum',
  'minlength', 'maxlength', 'pattern', 'minitems', 'maxitems', 'uniqueitems',
  'contentencoding', 'contentmediatype', 'contentschema',
  // Object.prototype / built-in (avoid as property names)
  'constructor', 'prototype', 'valueof', 'tostring', 'hasownproperty',
  'isprototypeof', 'propertyisenumerable', '__proto__',
]);

/**
 * Returns true if the given name is reserved (case-insensitive).
 * Use for class names and property names during import.
 */
export function isReservedName(name: string): boolean {
  if (typeof name !== 'string' || !name.trim()) return false;
  return RESERVED_LOWER.has(name.toLowerCase());
}

/**
 * Collects user-facing warnings for reserved names used as class or property names.
 * Recursively checks classes and all properties (including nested).
 */
export function collectReservedNameWarnings(classes: NormalizedClass[]): string[] {
  const warnings: string[] = [];

  for (const cls of classes) {
    if (isReservedName(cls.name)) {
      const schemaRef = cls.originalSchemaKey ? ` (schema "${cls.originalSchemaKey}")` : '';
      warnings.push(`Reserved name used as class name: "${cls.name}"${schemaRef}. Consider renaming to avoid codegen conflicts.`);
    }

    const checkProperties = (props: NormalizedProperty[], context: string) => {
      for (const p of props) {
        if (isReservedName(p.name)) {
          warnings.push(`Reserved name used as property: "${p.name}" in ${context}. Consider renaming to avoid codegen conflicts.`);
        }
        if (p.children?.length) {
          checkProperties(p.children, `${context} → "${p.name}"`);
        }
      }
    };

    checkProperties(cls.properties ?? [], `class "${cls.name}"`);
  }

  return warnings;
}
