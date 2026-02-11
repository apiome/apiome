/**
 * Naming Convention Utilities (#581)
 *
 * Enforce and convert naming conventions (camelCase, PascalCase, snake_case, kebab-case)
 * during import of classes and properties.
 */

export type NamingConvention = 'PascalCase' | 'camelCase' | 'snake_case' | 'kebab-case' | 'none';

/** Split a string into word segments (handles camelCase, PascalCase, snake_case, kebab-case) */
function splitIntoWords(str: string): string[] {
  if (!str || typeof str !== 'string') return [];
  return str
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/([A-Z])([A-Z][a-z])/g, '$1 $2')
    .replace(/[\s_-]+/g, ' ')
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map(w => w.toLowerCase());
}

/** Convert to PascalCase (e.g. user_name → UserName) */
function toPascalCase(str: string): string {
  const words = splitIntoWords(str);
  return words.map(w => w.charAt(0).toUpperCase() + w.slice(1)).join('');
}

/** Convert to camelCase (e.g. user_name → userName) */
function toCamelCase(str: string): string {
  const words = splitIntoWords(str);
  if (words.length === 0) return str;
  return words[0] + words.slice(1).map(w => w.charAt(0).toUpperCase() + w.slice(1)).join('');
}

/** Convert to snake_case (e.g. UserName → user_name) */
function toSnakeCase(str: string): string {
  const words = splitIntoWords(str);
  return words.join('_');
}

/** Convert to kebab-case (e.g. UserName → user-name) */
function toKebabCase(str: string): string {
  const words = splitIntoWords(str);
  return words.join('-');
}

/**
 * Convert a name to the target naming convention.
 */
export function convertToNamingConvention(
  name: string,
  convention: NamingConvention
): string {
  if (!name || convention === 'none') return name;
  switch (convention) {
    case 'PascalCase':
      return toPascalCase(name);
    case 'camelCase':
      return toCamelCase(name);
    case 'snake_case':
      return toSnakeCase(name);
    case 'kebab-case':
      return toKebabCase(name);
    default:
      return name;
  }
}

/** Check if a string matches a naming convention */
function matchesConvention(str: string, convention: NamingConvention): boolean {
  if (!str || convention === 'none') return true;
  const converted = convertToNamingConvention(str, convention);
  return str === converted;
}

/**
 * Validate that a name matches the target naming convention.
 * Returns validation result with optional suggested conversion.
 */
export function validateNamingConvention(
  name: string,
  convention: NamingConvention
): { valid: boolean; suggested?: string } {
  if (!name || convention === 'none') return { valid: true };
  const valid = matchesConvention(name, convention);
  const suggested = valid ? undefined : convertToNamingConvention(name, convention);
  return { valid, suggested };
}

/** Update $ref in data to use new class names from the mapping */
function updateRefsInData(data: any, nameMap: Map<string, string>): any {
  if (!data || typeof data !== 'object') return data;
  const result = { ...data };
  if (typeof result.$ref === 'string') {
    const match = result.$ref.match(/#\/components\/schemas\/(.+)$/);
    if (match && nameMap.has(match[1])) {
      result.$ref = `#/components/schemas/${nameMap.get(match[1])}`;
    }
  }
  if (result.items && typeof result.items === 'object' && result.items.$ref) {
    const match = result.items.$ref.match(/#\/components\/schemas\/(.+)$/);
    if (match && nameMap.has(match[1])) {
      result.items = { ...result.items, $ref: `#/components/schemas/${nameMap.get(match[1])}` };
    }
  }
  return result;
}

/**
 * Apply naming conventions to a normalized class.
 * - classNamingConvention: applied to class name
 * - propertyNamingConvention: applied to all property names (including nested)
 * - nameMap: optional mapping of original class names to new names, used to update $ref in property data
 */
export function applyNamingConventionToClass<T extends { name: string; properties?: Array<{ name: string; data?: any; children?: unknown[] }> }>(
  cls: T,
  options: {
    classNamingConvention?: NamingConvention;
    propertyNamingConvention?: NamingConvention;
    applyNamingConvention?: boolean;
    nameMap?: Map<string, string>;
  }
): T {
  const { classNamingConvention = 'PascalCase', propertyNamingConvention = 'camelCase', applyNamingConvention = true, nameMap } = options;
  if (!applyNamingConvention) return cls;

  const newClassName = classNamingConvention === 'none' ? cls.name : convertToNamingConvention(cls.name, classNamingConvention);

  const transformProp = (p: { name: string; data?: any; children?: unknown[] }): typeof p => {
    const newName = propertyNamingConvention === 'none' ? p.name : convertToNamingConvention(p.name, propertyNamingConvention);
    const newData = nameMap && p.data ? updateRefsInData(p.data, nameMap) : p.data;
    const result: typeof p = { ...p, name: newName, data: newData };
    if (p.children && Array.isArray(p.children) && p.children.length > 0) {
      result.children = p.children.map((c) => transformProp(c as typeof p));
    }
    return result;
  };

  const newProperties = cls.properties?.map(transformProp);

  return {
    ...cls,
    name: newClassName,
    properties: newProperties ?? cls.properties,
  };
}

/**
 * Apply naming conventions to multiple classes.
 * Builds a name map and updates $ref in properties so references point to renamed classes.
 */
export function applyNamingConventionToClasses<T extends { name: string; properties?: Array<{ name: string; data?: any; children?: unknown[] }> }>(
  classes: T[],
  options: {
    classNamingConvention?: NamingConvention;
    propertyNamingConvention?: NamingConvention;
    applyNamingConvention?: boolean;
  }
): T[] {
  const { classNamingConvention = 'PascalCase', propertyNamingConvention = 'camelCase', applyNamingConvention = true } = options;
  if (!applyNamingConvention) return classes;

  const nameMap = new Map<string, string>();
  for (const cls of classes) {
    const newName = classNamingConvention === 'none' ? cls.name : convertToNamingConvention(cls.name, classNamingConvention);
    nameMap.set(cls.name, newName);
  }

  return classes.map((cls) =>
    applyNamingConventionToClass(cls, { classNamingConvention, propertyNamingConvention, applyNamingConvention: true, nameMap })
  );
}
