/**
 * Apache Avro (.avsc / JSON schema) to OpenAPI 3.1.x Converter (for Import) — #239
 *
 * Converts Avro schema JSON to an OpenAPI 3.1–shaped document so the existing
 * import pipeline (components.schemas, $ref) can be reused.
 *
 * - record → object schema with properties
 * - enum → string schema with enum array
 * - array → array of item type
 * - map → object with additionalProperties
 * - union → oneOf (or nullable when union includes "null")
 * - fixed → string format byte
 */

export interface AvroConversionResult {
  success: boolean;
  document: any;
  error?: string;
  warnings: string[];
}

type AvroSchema =
  | string
  | { type: string; [k: string]: any }
  | AvroSchema[];

/**
 * Detect if the content looks like an Apache Avro schema (JSON with type/record or type/enum).
 */
export function isAvro(content: string): boolean {
  if (!content || typeof content !== 'string') return false;
  const trimmed = content.trim();
  if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) return false;
  try {
    const data = JSON.parse(trimmed);
    return isAvroSchemaObject(data);
  } catch {
    return false;
  }
}

/**
 * Check if a parsed value is an Avro schema (record, enum, or array of same).
 */
export function isAvroSchemaObject(doc: any): boolean {
  if (!doc || typeof doc !== 'object') return false;
  if (Array.isArray(doc)) {
    return doc.length > 0 && doc.every((item) => isAvroSchemaObject(item) || isAvroRecordOrEnum(item));
  }
  return isAvroRecordOrEnum(doc);
}

function isAvroRecordOrEnum(obj: any): boolean {
  if (!obj || typeof obj !== 'object') return false;
  const t = obj.type;
  if (t === 'record' && Array.isArray(obj.fields)) return true;
  if (t === 'enum' && Array.isArray(obj.symbols)) return true;
  return false;
}

function fullName(schema: { name: string; namespace?: string }): string {
  if (schema.namespace) {
    return `${schema.namespace}.${schema.name}`;
  }
  return schema.name;
}

/**
 * Collect all named types (record, enum, fixed) from an Avro schema tree.
 */
function collectNamedTypes(
  schema: AvroSchema,
  into: Map<string, { type: string; schema: any }>,
  namespace?: string
): void {
  if (typeof schema === 'string') return; // reference
  if (Array.isArray(schema)) {
    schema.forEach((s) => collectNamedTypes(s, into, namespace));
    return;
  }
  if (!schema || typeof schema !== 'object') return;
  const t = schema.type;
  const ns = schema.namespace ?? namespace;
  const named = schema as unknown as { name: string; namespace?: string };
  if (t === 'record' && named.name) {
    const name = fullName(named);
    if (!into.has(name)) {
      into.set(name, { type: 'record', schema });
      (schema.fields || []).forEach((f: any) => {
        if (f && f.type) collectNamedTypes(f.type, into, ns);
      });
    }
  } else if (t === 'enum' && named.name) {
    const name = fullName(named);
    if (!into.has(name)) into.set(name, { type: 'enum', schema });
  } else if (t === 'fixed' && named.name) {
    const name = fullName(named);
    if (!into.has(name)) into.set(name, { type: 'fixed', schema });
  } else if (t === 'array' && schema.items) {
    collectNamedTypes(schema.items, into, ns);
  } else if (t === 'map' && schema.values) {
    collectNamedTypes(schema.values, into, ns);
  } else if (Array.isArray(schema)) {
    schema.forEach((s) => collectNamedTypes(s, into, ns));
  }
}

const AVRO_PRIMITIVES: Record<string, any> = {
  null: { type: 'null' },
  boolean: { type: 'boolean' },
  int: { type: 'integer', format: 'int32' },
  long: { type: 'integer', format: 'int64' },
  float: { type: 'number', format: 'float' },
  double: { type: 'number', format: 'double' },
  bytes: { type: 'string', format: 'byte' },
  string: { type: 'string' },
};

function avroTypeToOpenAPI(
  schema: AvroSchema,
  named: Map<string, { type: string; schema: any }>,
  warnings: string[],
  schemaNameToRef: (name: string) => string
): any {
  if (typeof schema === 'string') {
    const prim = AVRO_PRIMITIVES[schema];
    if (prim) return { ...prim };
    const ref = schemaNameToRef(schema);
    if (ref) return { $ref: ref };
    warnings.push(`Unknown Avro type reference: ${schema}`);
    return { type: 'string' };
  }
  if (Array.isArray(schema)) {
    const nonNull = schema.filter((s) => s !== 'null' && (typeof s !== 'string' || s !== 'null'));
    const hasNull = schema.some((s) => s === 'null');
    if (nonNull.length === 0) return { type: 'string', description: 'null' };
    if (nonNull.length === 1) {
      const inner = avroTypeToOpenAPI(nonNull[0], named, warnings, schemaNameToRef);
      return hasNull ? { oneOf: [{ type: 'null' }, inner] } : inner;
    }
    const oneOf = schema.map((s) =>
      s === 'null' ? { type: 'null' } : avroTypeToOpenAPI(s, named, warnings, schemaNameToRef)
    );
    return { oneOf };
  }
  if (!schema || typeof schema !== 'object') return { type: 'string' };

  const t = schema.type;
  switch (t) {
    case 'null':
      return { type: 'null' };
    case 'boolean':
      return { type: 'boolean' };
    case 'int':
      return { type: 'integer', format: 'int32' };
    case 'long':
      return { type: 'integer', format: 'int64' };
    case 'float':
      return { type: 'number', format: 'float' };
    case 'double':
      return { type: 'number', format: 'double' };
    case 'bytes':
      return { type: 'string', format: 'byte' };
    case 'string':
      return { type: 'string' };
    case 'record': {
      const recordNamed = schema as unknown as { name: string; namespace?: string };
      const name = fullName(recordNamed);
      if (recordNamed.name && named.has(name)) {
        const ref = schemaNameToRef(name);
        if (ref) return { $ref: ref };
      }
      const properties: Record<string, any> = {};
      const required: string[] = [];
      for (const f of schema.fields || []) {
        if (!f || f.name == null) continue;
        properties[f.name] = avroTypeToOpenAPI(f.type, named, warnings, schemaNameToRef);
        if (f.default === undefined && !isOptional(f.type)) required.push(f.name);
      }
      return {
        type: 'object',
        properties,
        ...(required.length ? { required } : {}),
        ...(schema.doc ? { description: schema.doc } : {}),
      };
    }
    case 'enum': {
      const enumNamed = schema as unknown as { name: string; namespace?: string };
      const enumName = fullName(enumNamed);
      if (enumNamed.name && named.has(enumName)) {
        const ref = schemaNameToRef(enumName);
        if (ref) return { $ref: ref };
      }
      return {
        type: 'string',
        enum: (schema.symbols || []).length ? schema.symbols : ['UNKNOWN'],
        ...(schema.doc ? { description: schema.doc } : {}),
      };
    }
    case 'array':
      return {
        type: 'array',
        items: avroTypeToOpenAPI(schema.items, named, warnings, schemaNameToRef),
      };
    case 'map':
      return {
        type: 'object',
        additionalProperties: avroTypeToOpenAPI(schema.values, named, warnings, schemaNameToRef),
      };
    case 'fixed':
      return { type: 'string', format: 'byte', description: `Fixed size ${schema.size ?? 0} bytes` };
    default:
      warnings.push(`Unsupported Avro type: ${t}`);
      return { type: 'string' };
  }
}

function isOptional(schema: AvroSchema): boolean {
  if (Array.isArray(schema)) return schema.includes('null');
  return false;
}

/**
 * Normalize schema name for OpenAPI component key (no dots; use last segment or full with underscores).
 */
function componentKey(name: string): string {
  return name.includes('.') ? name.split('.').join('_') : name;
}

/**
 * Convert one or more Avro schemas (object or array) to OpenAPI 3.1 document.
 */
export function convertAvroToOpenAPI(
  input: any,
  _fileName?: string
): AvroConversionResult {
  const warnings: string[] = [];
  warnings.push(
    'Imported from Apache Avro. Only record, enum, and fixed types are imported as schemas.'
  );

  if (input == null) {
    return {
      success: false,
      document: null,
      error: 'Invalid or empty Avro schema',
      warnings: [],
    };
  }

  const roots: any[] = Array.isArray(input) ? input : [input];
  const named = new Map<string, { type: string; schema: any }>();
  for (const root of roots) {
    if (root && typeof root === 'object') collectNamedTypes(root, named);
  }

  if (named.size === 0) {
    const first = roots[0];
    if (first && typeof first === 'object' && (first.type === 'record' || first.type === 'enum')) {
      collectNamedTypes(first, named);
    }
  }
  if (named.size === 0) {
    return {
      success: false,
      document: null,
      error: 'No Avro record or enum definitions found',
      warnings,
    };
  }

  const schemas: Record<string, any> = {};
  const nameToKey: Record<string, string> = {};
  const shortNameToFull: Record<string, string> = {};
  Array.from(named.keys()).forEach((name) => {
    nameToKey[name] = componentKey(name);
    const short = name.includes('.') ? name.split('.').pop()! : name;
    if (!shortNameToFull[short] || short === name) shortNameToFull[short] = name;
  });
  const schemaNameToRef = (name: string): string => {
    const full = nameToKey[name] ? name : shortNameToFull[name];
    const resolved = full || name;
    const key = nameToKey[resolved];
    if (key) return `#/components/schemas/${key}`;
    if (named.has(resolved)) return `#/components/schemas/${componentKey(resolved)}`;
    return '';
  };

  for (const [name, { type: kind, schema }] of named) {
    const key = componentKey(name);
    if (kind === 'record') {
      const properties: Record<string, any> = {};
      const required: string[] = [];
      for (const f of schema.fields || []) {
        if (!f || f.name == null) continue;
        properties[f.name] = avroTypeToOpenAPI(f.type, named, warnings, schemaNameToRef);
        if (f.default === undefined && !isOptional(f.type)) required.push(f.name);
      }
      schemas[key] = {
        type: 'object',
        properties,
        ...(required.length ? { required } : {}),
        ...(schema.doc ? { description: schema.doc } : {}),
      };
    } else if (kind === 'enum') {
      schemas[key] = {
        type: 'string',
        enum: (schema.symbols || []).length ? schema.symbols : ['UNKNOWN'],
        ...(schema.doc ? { description: schema.doc } : {}),
      };
    } else if (kind === 'fixed') {
      schemas[key] = {
        type: 'string',
        format: 'byte',
        description: schema.doc || `Fixed ${schema.size ?? 0} bytes`,
      };
    }
  }

  const openApiDoc = {
    openapi: '3.1.0',
    info: {
      title: 'Imported from Apache Avro',
      version: '1.0.0',
      description: 'Converted from Avro schema. Only record, enum, and fixed types are imported.',
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
