/**
 * RAML to OpenAPI 3.1.x Converter (for Import) — #237
 *
 * Converts RAML 0.8 / 1.0 definition files to an OpenAPI 3.1–shaped document
 * so the existing import pipeline (components.schemas, $ref) can be reused.
 *
 * - RAML 1.0: types (and legacy schemas alias) → components.schemas (JSON Schema)
 * - RAML 0.8: schemas (JSON Schema strings or inline) → components.schemas
 * - baseUri → servers; title/version/description → info
 */

export interface RAMLConversionResult {
  success: boolean;
  document: any;
  error?: string;
  warnings: string[];
}

/** RAML version comment or typical root keys (title + baseUri, version, types, or schemas) */
export function isRAML(doc: any): boolean {
  if (doc == null || typeof doc !== 'object') return false;
  if (doc['#%RAML']) return true;
  // RAML root: title plus at least one of baseUri, version, types, or schemas
  const hasTitle = typeof doc.title === 'string';
  const hasRamlIndicator =
    typeof doc.baseUri === 'string' ||
    typeof doc.version === 'string' ||
    (doc.types && typeof doc.types === 'object') ||
    (doc.schemas && typeof doc.schemas === 'object');
  if (hasTitle && hasRamlIndicator && !doc.openapi && !doc.swagger && !doc.asyncapi) return true;
  return false;
}

const RAML_PRIMITIVES = new Set(['string', 'number', 'integer', 'boolean', 'object', 'array', 'date-only', 'time-only', 'datetime-only', 'datetime', 'file', 'nil', 'any']);

/**
 * Convert a RAML type expression (string or object) to a JSON Schema fragment.
 * - "string" -> { type: "string" }
 * - "TypeName" -> { $ref: "#/components/schemas/TypeName" }
 * - "TypeName[]" -> { type: "array", items: { $ref: ... } }
 * - { type: "string", pattern: "..." } -> pass through (JSON Schema–like)
 */
function ramlTypeToJsonSchema(typeVal: any, typeNames: Set<string>): any {
  if (typeVal === undefined || typeVal === null) return undefined;

  if (typeof typeVal === 'string') {
    const s = typeVal.trim();
    if (RAML_PRIMITIVES.has(s)) {
      const t = s === 'datetime' || s === 'datetime-only' ? 'string' : s === 'date-only' || s === 'time-only' ? 'string' : s === 'nil' ? 'null' : s === 'any' ? undefined : s;
      if (t === undefined) return {}; // any
      return { type: t };
    }
    if (s.endsWith('[]')) {
      const name = s.slice(0, -2).trim();
      return {
        type: 'array',
        items: typeNames.has(name) ? { $ref: `#/components/schemas/${name}` } : { type: 'string' }
      };
    }
    if (typeNames.has(s)) return { $ref: `#/components/schemas/${s}` };
    return { type: 'string' };
  }

  if (typeof typeVal === 'object') {
    const out: any = {};
    if (typeVal.type !== undefined) {
      const t = ramlTypeToJsonSchema(typeVal.type, typeNames);
      if (t && t.$ref) {
        out.$ref = t.$ref;
        return out;
      }
      if (t && typeof t === 'object' && Object.keys(t).length > 0) Object.assign(out, t);
    }
    if (typeVal.description) out.description = typeVal.description;
    if (typeVal.enum) out.enum = typeVal.enum;
    if (typeVal.pattern) out.pattern = typeVal.pattern;
    if (typeVal.minLength !== undefined) out.minLength = typeVal.minLength;
    if (typeVal.maxLength !== undefined) out.maxLength = typeVal.maxLength;
    if (typeVal.minimum !== undefined) out.minimum = typeVal.minimum;
    if (typeVal.maximum !== undefined) out.maximum = typeVal.maximum;
    if (typeVal.format) out.format = typeVal.format;
    if (typeVal.properties) {
      const props: any = {};
      const required: string[] = [];
      for (const [k, v] of Object.entries(typeVal.properties)) {
        const propName = k.replace(/\?$/, '');
        const isRequired = !k.endsWith('?');
        if (isRequired) required.push(propName);
        const propSchema = ramlTypeToJsonSchema(v, typeNames);
        if (propSchema) props[propName] = propSchema;
      }
      out.properties = props;
      if (required.length) out.required = required;
    }
    if (typeVal.required && Array.isArray(typeVal.required)) out.required = typeVal.required;
    if (typeVal.items) out.items = ramlTypeToJsonSchema(typeVal.items, typeNames);
    return Object.keys(out).length ? out : undefined;
  }

  return undefined;
}

/**
 * Convert one RAML type declaration (value in types/TypeName) to OpenAPI schema.
 */
function convertRAMLTypeDeclaration(
  name: string,
  decl: any,
  allTypeNames: Set<string>,
  schemasAcc: Record<string, any>,
  warnings: string[]
): void {
  if (decl == null) return;

  // String: inline JSON Schema (possibly)
  if (typeof decl === 'string') {
    const trimmed = decl.trim();
    if (trimmed.startsWith('{')) {
      try {
        const parsed = JSON.parse(trimmed);
        if (parsed && typeof parsed === 'object') {
          schemasAcc[name] = parsed;
          return;
        }
      } catch {
        warnings.push(`RAML type "${name}" is a string that could not be parsed as JSON Schema; treated as empty object.`);
      }
    }
    schemasAcc[name] = { type: 'object', description: 'Imported from RAML (string type declaration)' };
    return;
  }

  if (typeof decl !== 'object') return;

  // type: OtherType (inheritance) -> allOf with $ref
  const typeFacet = decl.type ?? decl.schema;
  if (typeof typeFacet === 'string' && allTypeNames.has(typeFacet) && typeFacet !== name) {
    const baseRef = { $ref: `#/components/schemas/${typeFacet}` };
    const schema: any = {
      allOf: [baseRef],
      description: decl.description
    };
    const propSchema = ramlTypeToJsonSchema({ type: 'object', properties: decl.properties }, allTypeNames);
    if (propSchema && propSchema.properties && Object.keys(propSchema.properties).length > 0) {
      schema.allOf.push({ type: 'object', properties: propSchema.properties, required: propSchema.required });
    }
    if (decl.required && Array.isArray(decl.required)) {
      const last = schema.allOf[schema.allOf.length - 1];
      if (last && last.type === 'object') last.required = decl.required;
    }
    schemasAcc[name] = schema;
    return;
  }

  const schema = ramlTypeToJsonSchema(decl, allTypeNames);
  if (schema) {
    if (decl.description) schema.description = decl.description;
    schemasAcc[name] = schema;
    return;
  }

  // Full object with type: object, properties, etc.
  const out: any = {};
  if (decl.description) out.description = decl.description;
  if (decl.type === 'object' && decl.properties) {
    const props: any = {};
    const required: string[] = [];
    for (const [k, v] of Object.entries(decl.properties)) {
      const propName = (k as string).replace(/\?$/, '');
      const isRequired = !(k as string).endsWith('?');
      if (isRequired) required.push(propName);
      const propSchema = ramlTypeToJsonSchema(v, allTypeNames);
      if (propSchema) props[propName] = propSchema;
    }
    out.type = 'object';
    out.properties = props;
    if (required.length) out.required = required;
  } else if (decl.enum) {
    out.enum = decl.enum;
    if (decl.description) out.description = decl.description;
  } else {
    out.type = 'object';
  }
  schemasAcc[name] = out;
}

/**
 * Convert RAML document to OpenAPI 3.1–like document for import.
 */
export function convertRAMLToOpenAPI(doc: any, _fileName?: string): RAMLConversionResult {
  const warnings: string[] = [];

  if (!doc || typeof doc !== 'object') {
    return {
      success: false,
      document: null,
      error: 'Invalid or empty document',
      warnings: []
    };
  }

  if (!isRAML(doc)) {
    return {
      success: false,
      document: null,
      error: 'Document is not a RAML specification',
      warnings: []
    };
  }

  const ramlVersion = doc['#%RAML'] || '1.0';
  const typesSource = doc.types ?? doc.schemas;
  const typeNames = new Set<string>();

  if (typesSource && typeof typesSource === 'object') {
    for (const key of Object.keys(typesSource)) typeNames.add(key);
  }

  const schemas: Record<string, any> = {};

  if (typesSource && typeof typesSource === 'object') {
    for (const name of Object.keys(typesSource)) {
      convertRAMLTypeDeclaration(name, typesSource[name], typeNames, schemas, warnings);
    }
  }

  const schemaCount = Object.keys(schemas).length;
  if (schemaCount === 0) {
    warnings.push('No types or schemas found. RAML resources and bodies are not extracted; only root-level types are imported.');
  }

  const baseUri = doc.baseUri;
  const servers = baseUri
    ? [{ url: typeof baseUri === 'string' ? baseUri.replace(/\{version\}/g, doc.version || '1.0') : String(baseUri), description: 'From RAML baseUri' }]
    : [];

  const openApiDoc = {
    openapi: '3.1.0',
    info: {
      title: doc.title ?? 'Imported from RAML',
      version: doc.version ?? '1.0.0',
      description: doc.description ?? `Converted from RAML ${ramlVersion}`
    },
    servers: servers.length ? servers : undefined,
    components: {
      schemas: Object.keys(schemas).length ? schemas : undefined
    }
  };

  if (!openApiDoc.components!.schemas) {
    openApiDoc.components = { schemas: {} };
  }

  return {
    success: true,
    document: openApiDoc,
    warnings
  };
}
