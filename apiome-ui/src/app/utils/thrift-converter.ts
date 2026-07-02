/**
 * Apache Thrift (.thrift IDL) to OpenAPI 3.1.x Converter (for Import) — #240
 *
 * Converts Thrift IDL to an OpenAPI 3.1–shaped document so the existing
 * import pipeline (components.schemas, $ref) can be reused.
 *
 * - struct / union / exception → object schema with properties
 * - enum → string schema with enum array
 * - list<T> → array of item type
 * - set<T> → array of item type (uniqueItems: true)
 * - map<K,V> → object with additionalProperties
 */

export interface ThriftConversionResult {
  success: boolean;
  document: any;
  error?: string;
  warnings: string[];
}

const THRIFT_BASE_TO_JSON: Record<string, { type: string; format?: string }> = {
  bool: { type: 'boolean' },
  byte: { type: 'integer', format: 'int8' },
  i8: { type: 'integer', format: 'int8' },
  i16: { type: 'integer', format: 'int16' },
  i32: { type: 'integer', format: 'int32' },
  i64: { type: 'integer', format: 'int64' },
  double: { type: 'number', format: 'double' },
  string: { type: 'string' },
  binary: { type: 'string', format: 'byte' },
  uuid: { type: 'string', format: 'uuid' },
};

/**
 * Detect if the content looks like a Thrift IDL (.thrift) definition.
 */
export function isThrift(content: string): boolean {
  if (!content || typeof content !== 'string') return false;
  const trimmed = content.trim();
  // Thrift `include` uses a quoted path; plain English ("include a link…") must not match.
  if (/\binclude\s+"/.test(trimmed)) return true;
  // Thrift `namespace <lang> <name>` — anchor to line start so keys like `x-namespace:` are not matched.
  if (/^\s*namespace\s+\w+\s+/m.test(trimmed)) return true;
  if (/\bstruct\s+\w+\s*\{/.test(trimmed)) return true;
  if (/\benum\s+\w+\s*\{/.test(trimmed)) return true;
  if (/\bunion\s+\w+\s*\{/.test(trimmed)) return true;
  if (/\bexception\s+\w+\s*\{/.test(trimmed)) return true;
  if (/\bservice\s+\w+\s*\{/.test(trimmed)) return true;
  if (/\btypedef\s+/.test(trimmed)) return true;
  return false;
}

function stripComments(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/\/\/[^\n]*/g, ' ')
    .replace(/#[^\n]*/g, ' ');
}

function findMatchingBrace(s: string, start: number): number {
  let depth = 1;
  let i = start;
  while (i < s.length && depth > 0) {
    const c = s[i];
    if (c === '{') depth++;
    else if (c === '}') depth--;
    i++;
  }
  return depth === 0 ? i - 1 : -1;
}

interface ThriftEnum {
  name: string;
  values: string[];
}

interface ThriftStruct {
  name: string;
  kind: 'struct' | 'union' | 'exception';
  fields: Array<{
    name: string;
    required: boolean; // required = true, optional/default = false
    type: string; // resolved type name or base/container expression for later resolution
    rawType: string;
  }>;
}

/** Resolve typedefs: map alias -> underlying type (base or named). */
function collectTypedefs(cleaned: string): Map<string, string> {
  const typedefs = new Map<string, string>();
  const re = /\btypedef\s+([\w.<>, \t]+?)\s+(\w+)\s*[,;]/g;
  let m;
  while ((m = re.exec(cleaned)) !== null) {
    const rawType = m[1].trim();
    const alias = m[2].trim();
    typedefs.set(alias, rawType);
  }
  return typedefs;
}

/**
 * Recursively resolve typedefs in a type expression (e.g. list<MyAlias> -> list<string>).
 */
function resolveTypedefInType(
  typeExpr: string,
  typedefs: Map<string, string>,
  visited: Set<string> = new Set()
): string {
  const t = typeExpr.trim();
  const listMatch = t.match(/^list\s*<\s*([\w.<>, \t]+)\s*>$/);
  if (listMatch) {
    return `list<${resolveTypedefInType(listMatch[1].trim(), typedefs, visited)}>`;
  }
  const setMatch = t.match(/^set\s*<\s*([\w.<>, \t]+)\s*>$/);
  if (setMatch) {
    return `set<${resolveTypedefInType(setMatch[1].trim(), typedefs, visited)}>`;
  }
  const mapMatch = t.match(/^map\s*<\s*([\w.<>, \t]+)\s*,\s*([\w.<>, \t]+)\s*>$/);
  if (mapMatch) {
    return `map<${resolveTypedefInType(mapMatch[1].trim(), typedefs, visited)},${resolveTypedefInType(mapMatch[2].trim(), typedefs, visited)}>`;
  }
  if (visited.has(t)) return t;
  const resolved = typedefs.get(t);
  if (!resolved) return t;
  visited.add(t);
  return resolveTypedefInType(resolved, typedefs, visited);
}

/**
 * Parse Thrift IDL and collect enums and struct/union/exception definitions.
 */
function parseThrift(
  cleaned: string,
  warnings: string[]
): { enums: Map<string, ThriftEnum>; structs: Map<string, ThriftStruct>; typedefs: Map<string, string> } {
  const enums = new Map<string, ThriftEnum>();
  const structs = new Map<string, ThriftStruct>();
  const typedefs = collectTypedefs(cleaned);

  const enumRegex = /\benum\s+(\w+)\s*\{/g;
  const structRegex = /\b(struct|union|exception)\s+(\w+)\s*(?:xsd_all)?\s*\{/g;
  let match;

  const enumBlocks: Array<{ name: string; start: number }> = [];
  while ((match = enumRegex.exec(cleaned)) !== null) {
    const open = cleaned.indexOf('{', match.index);
    if (open === -1) continue;
    enumBlocks.push({ name: match[1], start: match.index });
  }

  const structBlocks: Array<{ kind: 'struct' | 'union' | 'exception'; name: string; start: number }> = [];
  while ((match = structRegex.exec(cleaned)) !== null) {
    structBlocks.push({
      kind: match[1] as 'struct' | 'union' | 'exception',
      name: match[2],
      start: match.index,
    });
  }

  for (const { name, start } of enumBlocks) {
    const open = cleaned.indexOf('{', start);
    const close = findMatchingBrace(cleaned, open + 1);
    if (close === -1) continue;
    const inner = cleaned.slice(open + 1, close);
    const values: string[] = [];
    // Match identifier, optional = number, then optional separator (comma, semicolon, or newline)
    const valueRe = /(\w+)\s*(?:=\s*-?[\w.]+)?\s*[,;\n]?/g;
    let vm;
    while ((vm = valueRe.exec(inner)) !== null) {
      if (vm[1]) values.push(vm[1]);
    }
    if (!enums.has(name)) enums.set(name, { name, values });
  }

  // Field: (FieldID)? (required|optional)? FieldType Identifier (= ConstValue)? [,;]
  // Parse fields by reading type (with balanced <>) then identifier.
  function parseFieldType(s: string, start: number): { type: string; end: number } {
    let i = start;
    while (i < s.length && /[\s\t]/.test(s[i])) i++;
    if (i >= s.length) return { type: '', end: i };
    const typeStart = i;
    if (s.substring(i).match(/^(list|set|map)\s*</)) {
      const kw = s.substring(i).match(/^(list|set|map)/)![1];
      i += kw.length;
      while (i < s.length && /[\s\t]/.test(s[i])) i++;
      if (s[i] !== '<') return { type: s.slice(typeStart, i).trim(), end: i };
      i++;
      let depth = 1;
      if (kw === 'map') {
        while (i < s.length && depth > 0) {
          if (s[i] === '<') depth++;
          else if (s[i] === '>') depth--;
          else if (s[i] === ',' && depth === 1) { /* key, value */ }
          i++;
        }
      } else {
        while (i < s.length && depth > 0) {
          if (s[i] === '<') depth++;
          else if (s[i] === '>') depth--;
          i++;
        }
      }
      return { type: s.slice(typeStart, i).trim(), end: i };
    }
    while (i < s.length && /[\w.]/.test(s[i])) i++;
    return { type: s.slice(typeStart, i).trim(), end: i };
  }

  for (const { kind, name, start } of structBlocks) {
    const open = cleaned.indexOf('{', start);
    const close = findMatchingBrace(cleaned, open + 1);
    if (close === -1) continue;
    const inner = cleaned.slice(open + 1, close);
    const fields: ThriftStruct['fields'] = [];
    let i = 0;
    while (i < inner.length) {
      while (i < inner.length && /[\s\t,;]/.test(inner[i])) i++;
      if (i >= inner.length) break;
      const idMatch = inner.slice(i).match(/^(\d+)\s*:/);
      if (idMatch) i += idMatch[0].length;
      while (i < inner.length && /[\s\t]/.test(inner[i])) i++;
      const reqMatch = inner.slice(i).match(/^(required|optional)\s+/);
      const required = reqMatch && reqMatch[1] === 'required';
      if (reqMatch) i += reqMatch[0].length;
      const { type: rawType, end: typeEnd } = parseFieldType(inner, i);
      i = typeEnd;
      if (!rawType) break;
      while (i < inner.length && /[\s\t]/.test(inner[i])) i++;
      const nameMatch = inner.slice(i).match(/^(\w+)\s*(=\s*[^,;\n]*)?\s*[,;\n]/);
      if (!nameMatch) break;
      const fieldName = nameMatch[1];
      i += nameMatch[0].length;
      const resolved = resolveTypedefInType(rawType.replace(/\s+/g, ' '), typedefs);
      fields.push({
        name: fieldName,
        required: required ?? false,
        type: resolved,
        rawType,
      });
    }
    if (!structs.has(name)) {
      structs.set(name, { name, kind, fields });
    }
  }

  return { enums, structs, typedefs };
}

function componentKey(name: string): string {
  return name.includes('.') ? name.split('.').join('_') : name;
}

/**
 * Convert a Thrift field type to OpenAPI schema.
 */
function thriftTypeToOpenAPI(
  typeExpr: string,
  enums: Map<string, ThriftEnum>,
  structs: Map<string, ThriftStruct>,
  schemaRef: (name: string) => string,
  warnings: string[]
): any {
  const t = typeExpr.trim();

  const base = THRIFT_BASE_TO_JSON[t];
  if (base) return { ...base };

  const listMatch = t.match(/^list\s*<\s*([\w.<>, \t]+)\s*>$/);
  if (listMatch) {
    return {
      type: 'array',
      items: thriftTypeToOpenAPI(listMatch[1].trim(), enums, structs, schemaRef, warnings),
    };
  }

  const setMatch = t.match(/^set\s*<\s*([\w.<>, \t]+)\s*>$/);
  if (setMatch) {
    return {
      type: 'array',
      items: thriftTypeToOpenAPI(setMatch[1].trim(), enums, structs, schemaRef, warnings),
      uniqueItems: true,
    };
  }

  const mapMatch = t.match(/^map\s*<\s*([\w.<>, \t]+)\s*,\s*([\w.<>, \t]+)\s*>$/);
  if (mapMatch) {
    const valueSchema = thriftTypeToOpenAPI(
      mapMatch[2].trim(),
      enums,
      structs,
      schemaRef,
      warnings
    );
    return {
      type: 'object',
      additionalProperties: valueSchema,
      description: 'Map type (keys are strings in JSON)',
    };
  }

  const e = enums.get(t);
  if (e) {
    const ref = schemaRef(t);
    if (ref) return { $ref: ref };
    return {
      type: 'string',
      enum: e.values.length ? e.values : ['UNSPECIFIED'],
    };
  }

  if (structs.has(t)) {
    const ref = schemaRef(t);
    if (ref) return { $ref: ref };
  }

  warnings.push(`Unknown Thrift type: ${t}`);
  return { type: 'string' };
}

/**
 * Convert Thrift IDL content to an OpenAPI 3.1–like document for import.
 */
export function convertThriftToOpenAPI(
  content: string,
  _fileName?: string
): ThriftConversionResult {
  const warnings: string[] = [];
  warnings.push(
    'Imported from Apache Thrift IDL. Only struct, union, exception, and enum definitions are imported as schemas; services are not imported.'
  );

  if (!content || typeof content !== 'string') {
    return {
      success: false,
      document: null,
      error: 'Invalid or empty Thrift content',
      warnings: [],
    };
  }

  if (!isThrift(content)) {
    return {
      success: false,
      document: null,
      error: 'Content does not appear to be a Thrift IDL definition',
      warnings: [],
    };
  }

  const cleaned = stripComments(content);
  const { enums, structs } = parseThrift(cleaned, warnings);

  const schemaRef = (name: string): string => {
    const key = componentKey(name);
    return `#/components/schemas/${key}`;
  };

  const schemas: Record<string, any> = {};

  for (const [name, e] of enums) {
    const key = componentKey(name);
    schemas[key] = {
      type: 'string',
      enum: e.values.length ? e.values : ['UNSPECIFIED'],
      description: `Enum: ${e.name}`,
    };
  }

  for (const [name, st] of structs) {
    const key = componentKey(name);
    const properties: Record<string, any> = {};
    const required: string[] = [];
    for (const f of st.fields) {
      properties[f.name] = thriftTypeToOpenAPI(
        f.type,
        enums,
        structs,
        (n) => schemaRef(componentKey(n)),
        warnings
      );
      if (f.required) required.push(f.name);
    }
    const desc =
      st.kind === 'union'
        ? 'Union: exactly one field may be set'
        : st.kind === 'exception'
          ? `Exception: ${st.name}`
          : `Struct: ${st.name}`;
    schemas[key] = {
      type: 'object',
      properties: Object.keys(properties).length ? properties : {},
      ...(required.length ? { required } : {}),
      description: desc,
    };
  }

  if (Object.keys(schemas).length === 0) {
    return {
      success: false,
      document: null,
      error: 'No struct, union, exception, or enum definitions found in the Thrift file',
      warnings,
    };
  }

  const openApiDoc = {
    openapi: '3.1.0',
    info: {
      title: 'Imported from Apache Thrift',
      version: '1.0.0',
      description:
        'Converted from Thrift IDL. Only struct, union, exception, and enum types are imported.',
    },
    components: {
      schemas,
    },
  };

  return {
    success: true,
    document: openApiDoc,
    warnings,
  };
}
