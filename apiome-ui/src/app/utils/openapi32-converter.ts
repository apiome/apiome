/**
 * OpenAPI 3.2.0 to OpenAPI 3.1.x Normalization Layer (OA2, #3499)
 *
 * Converts OpenAPI 3.2.0 specifications into a 3.1.x-shaped document that the
 * existing 3.1 importer/analyzer can consume without re-parsing, mirroring the
 * contract of {@link ./openapi30-converter.ts}.
 *
 * The converter does three things with 3.2-only / changed constructs:
 *
 *  1. **Transform (safe / lossless)** — normalizations that the 3.1 importer can
 *     consume directly:
 *       - `example` (deprecated on Media Type / Parameter in 3.2) folded into the
 *         `examples` map; the deprecation is surfaced as an informational warning.
 *       - XML Object `nodeType` (which replaces the legacy boolean `attribute`)
 *         mapped back to the legacy `attribute` field where there is an equivalent.
 *
 *  2. **Preserve (lossless, already valid in 3.1)** — constructs that are valid in
 *     3.1 and simply carried through:
 *       - `summary` / `description` siblings on a `$ref` (Reference Object metadata,
 *         added in 3.1). Recorded for OA6 so it can attach them to resolved nodes.
 *
 *  3. **Stash (owned by OA3–OA6)** — 3.2-only constructs that the importer does not
 *     understand yet. Instead of being silently dropped they are carried forward on
 *     `x-apiome-*` extensions (or left in place where harmless) and reported in
 *     {@link OpenAPI32ConversionResult.unsupportedConstructs} so the downstream
 *     issues can light them up incrementally without re-parsing:
 *       - `additionalOperations` and the `QUERY` HTTP method (OA4).
 *       - sequential media types / `itemSchema` (OA3).
 *       - `tags[].summary` / `parent` / `kind` (OA5).
 *
 * The emitted document carries `openapi: '3.1.0'` so the downstream importer treats
 * it natively as 3.1.
 */

/**
 * The roadmap issue that owns the follow-up handling for a carried-forward construct.
 */
export type OpenAPI32ConstructOwner = 'OA3' | 'OA4' | 'OA5' | 'OA6';

/**
 * A 3.2-only construct that was carried forward (transformed, preserved, or stashed)
 * rather than silently dropped, so a downstream issue can act on it later.
 */
export interface OpenAPI32UnsupportedConstruct {
  /** Stable identifier (e.g. `additional-operations`). */
  id: string;
  /** Short human-readable label. */
  label: string;
  /** Explanation of what was carried forward and how. */
  description: string;
  /** Roadmap issue that owns the follow-up handling. */
  ownedBy: OpenAPI32ConstructOwner;
  /** Number of occurrences found in the document. */
  count: number;
  /** Severity for surfacing in the analyzer's unsupported-features list. */
  severity: 'warning' | 'info';
}

/**
 * Result of an OpenAPI 3.2.0 to 3.1.x conversion.
 */
export interface OpenAPI32ConversionResult {
  /** Whether the conversion succeeded. */
  success: boolean;
  /** The converted 3.1.x-shaped document (null on failure). */
  document: any;
  /** Error message when {@link success} is false. */
  error?: string;
  /** Informational/transformation notes (e.g. deprecation notices). */
  warnings: string[];
  /** 3.2-only constructs carried forward for downstream issues (OA3–OA6). */
  unsupportedConstructs: OpenAPI32UnsupportedConstruct[];
}

/**
 * Mutable bookkeeping passed through the recursive walk so warnings and
 * carried-forward constructs accumulate in one place.
 */
interface ConversionContext {
  warnings: string[];
  /** Carried-forward constructs keyed by id so counts aggregate. */
  constructs: Map<string, OpenAPI32UnsupportedConstruct>;
}

/** HTTP methods recognized as operations by the 3.1 importer. */
const KNOWN_OPERATIONS = ['get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace'] as const;

/**
 * Check if a document is OpenAPI 3.2.x.
 *
 * @param doc - the parsed document to inspect.
 * @returns true when the document declares an `openapi` version in the 3.2 line.
 */
export function isOpenAPI32(doc: any): boolean {
  if (!doc || typeof doc !== 'object') {
    return false;
  }
  if (!doc.openapi || typeof doc.openapi !== 'string') {
    return false;
  }
  return doc.openapi.startsWith('3.2');
}

/**
 * Record a carried-forward construct, aggregating the occurrence count when the
 * same construct id is seen more than once.
 */
function recordConstruct(
  ctx: ConversionContext,
  construct: Omit<OpenAPI32UnsupportedConstruct, 'count'> & { count?: number }
): void {
  const increment = construct.count ?? 1;
  const existing = ctx.constructs.get(construct.id);
  if (existing) {
    existing.count += increment;
    return;
  }
  ctx.constructs.set(construct.id, {
    id: construct.id,
    label: construct.label,
    description: construct.description,
    ownedBy: construct.ownedBy,
    severity: construct.severity,
    count: increment
  });
}

/**
 * Converts an OpenAPI 3.2.0 specification to OpenAPI 3.1.x format.
 *
 * @param openapi32Doc - the parsed OpenAPI 3.2.0 document.
 * @returns the converted 3.1.x document plus conversion warnings and the list of
 *   3.2-only constructs carried forward for downstream issues.
 */
export function convertOpenAPI32ToOpenAPI31(openapi32Doc: any): OpenAPI32ConversionResult {
  const ctx: ConversionContext = { warnings: [], constructs: new Map() };

  try {
    // Validate input.
    if (!openapi32Doc || typeof openapi32Doc !== 'object') {
      return {
        success: false,
        document: null,
        error: 'Invalid OpenAPI document: expected an object',
        warnings: [],
        unsupportedConstructs: []
      };
    }

    if (!isOpenAPI32(openapi32Doc)) {
      return {
        success: false,
        document: null,
        error: `Invalid OpenAPI version: expected 3.2.x, got ${openapi32Doc.openapi}`,
        warnings: [],
        unsupportedConstructs: []
      };
    }

    // Deep clone so the original document is never mutated.
    const doc = JSON.parse(JSON.stringify(openapi32Doc));

    // Downstream importer treats this as a native 3.1 document.
    doc.openapi = '3.1.0';

    // Tag metadata additions (summary/parent/kind) are owned by OA5.
    if (Array.isArray(doc.tags)) {
      convertTags(doc.tags, ctx);
    }

    // components.* objects.
    if (doc.components?.schemas) {
      doc.components.schemas = convertSchemaMap(doc.components.schemas, ctx, 'components.schemas');
    }
    if (doc.components?.parameters) {
      doc.components.parameters = convertNamedMap(doc.components.parameters, ctx, 'components.parameters', convertParameter);
    }
    if (doc.components?.requestBodies) {
      doc.components.requestBodies = convertNamedMap(doc.components.requestBodies, ctx, 'components.requestBodies', convertRequestBody);
    }
    if (doc.components?.responses) {
      doc.components.responses = convertNamedMap(doc.components.responses, ctx, 'components.responses', convertResponse);
    }
    if (doc.components?.headers) {
      doc.components.headers = convertNamedMap(doc.components.headers, ctx, 'components.headers', convertHeader);
    }

    // Paths.
    if (doc.paths) {
      doc.paths = convertPaths(doc.paths, ctx);
    }

    return {
      success: true,
      document: doc,
      warnings: ctx.warnings,
      unsupportedConstructs: Array.from(ctx.constructs.values())
    };
  } catch (error) {
    return {
      success: false,
      document: null,
      error: `Conversion failed: ${error instanceof Error ? error.message : String(error)}`,
      warnings: ctx.warnings,
      unsupportedConstructs: Array.from(ctx.constructs.values())
    };
  }
}

/**
 * Normalize the `tags` array. The 3.2-only `summary`, `parent`, and `kind` fields
 * are valid extra keys (the 3.1 importer ignores them) so they are preserved in
 * place and reported for OA5 rather than dropped.
 */
function convertTags(tags: any[], ctx: ConversionContext): void {
  let count = 0;
  for (const tag of tags) {
    if (!tag || typeof tag !== 'object') continue;
    if (tag.summary !== undefined || tag.parent !== undefined || tag.kind !== undefined) {
      count++;
    }
  }
  if (count > 0) {
    recordConstruct(ctx, {
      id: 'tag-metadata',
      label: 'Tag metadata (summary/parent/kind)',
      description:
        'OpenAPI 3.2 tag fields summary/parent/kind are preserved on the tag objects and carried forward for hierarchical tag support (OA5).',
      ownedBy: 'OA5',
      count,
      severity: 'info'
    });
  }
}

/**
 * Convert a `{ name: schema }` map of schemas.
 */
function convertSchemaMap(schemas: any, ctx: ConversionContext, path: string): any {
  const result: any = {};
  for (const [name, schema] of Object.entries<any>(schemas)) {
    result[name] = convertSchema(schema, ctx, `${path}.${name}`);
  }
  return result;
}

/**
 * Convert a `{ name: object }` map using the supplied per-entry converter.
 */
function convertNamedMap(
  map: any,
  ctx: ConversionContext,
  path: string,
  convertEntry: (entry: any, ctx: ConversionContext, path: string) => any
): any {
  const result: any = {};
  for (const [name, entry] of Object.entries<any>(map)) {
    result[name] = convertEntry(entry, ctx, `${path}.${name}`);
  }
  return result;
}

/**
 * Convert a single schema. Recurses through nested schemas and maps the XML
 * Object `nodeType` field. `$ref` nodes are passed through (their 3.1-valid
 * summary/description siblings are preserved and recorded for OA6).
 */
function convertSchema(schema: any, ctx: ConversionContext, path: string): any {
  if (!schema || typeof schema !== 'object') {
    return schema;
  }

  // $ref node: preserve as-is. Reference Object summary/description siblings are
  // valid in 3.1; record them so OA6 can attach them to the resolved node.
  if (schema.$ref) {
    if (schema.summary !== undefined || schema.description !== undefined) {
      recordConstruct(ctx, {
        id: 'ref-sibling-metadata',
        label: '$ref sibling metadata (summary/description)',
        description:
          'summary/description siblings on a $ref are preserved and carried forward to be attached to the resolved node (OA6).',
        ownedBy: 'OA6',
        severity: 'info'
      });
    }
    return { ...schema };
  }

  const converted: any = { ...schema };

  // Map XML Object nodeType (3.2) back to the legacy boolean attribute (3.0/3.1).
  if (converted.xml && typeof converted.xml === 'object') {
    converted.xml = convertXmlObject(converted.xml, ctx, `${path}.xml`);
  }

  // Recurse into nested schemas.
  if (converted.properties && typeof converted.properties === 'object') {
    const props: any = {};
    for (const [propName, propSchema] of Object.entries<any>(converted.properties)) {
      props[propName] = convertSchema(propSchema, ctx, `${path}.properties.${propName}`);
    }
    converted.properties = props;
  }

  if (converted.items) {
    converted.items = convertSchema(converted.items, ctx, `${path}.items`);
  }

  if (Array.isArray(converted.prefixItems)) {
    converted.prefixItems = converted.prefixItems.map((s: any, i: number) =>
      convertSchema(s, ctx, `${path}.prefixItems[${i}]`)
    );
  }

  if (converted.additionalProperties && typeof converted.additionalProperties === 'object') {
    converted.additionalProperties = convertSchema(
      converted.additionalProperties,
      ctx,
      `${path}.additionalProperties`
    );
  }

  for (const key of ['allOf', 'oneOf', 'anyOf'] as const) {
    if (Array.isArray(converted[key])) {
      converted[key] = converted[key].map((s: any, i: number) =>
        convertSchema(s, ctx, `${path}.${key}[${i}]`)
      );
    }
  }

  if (converted.not) {
    converted.not = convertSchema(converted.not, ctx, `${path}.not`);
  }

  return converted;
}

/**
 * Map an XML Object's 3.2 `nodeType` back to legacy fields.
 *
 * 3.2 replaces the boolean `attribute` with a `nodeType` enum
 * (`element` | `attribute` | `text` | `cdata` | `none`). `element` and
 * `attribute` have legacy equivalents; the remaining values have none, so they
 * are stashed on `x-apiome-xml-node-type` and reported for OA6.
 */
function convertXmlObject(xml: any, ctx: ConversionContext, path: string): any {
  if (!xml || typeof xml !== 'object' || xml.nodeType === undefined) {
    return xml;
  }

  const converted = { ...xml };
  const nodeType = converted.nodeType;
  delete converted.nodeType;

  if (nodeType === 'attribute') {
    converted.attribute = true;
    ctx.warnings.push(`Mapped XML nodeType "attribute" to the legacy "attribute: true" field at ${path}.`);
  } else if (nodeType === 'element') {
    // `element` is the default; no legacy field needed.
    ctx.warnings.push(`Mapped XML nodeType "element" to the default element representation at ${path}.`);
  } else {
    // text/cdata/none: no legacy equivalent. Stash so OA6 can act on it later.
    converted['x-apiome-xml-node-type'] = nodeType;
    recordConstruct(ctx, {
      id: 'xml-node-type',
      label: 'XML nodeType without a legacy equivalent',
      description:
        'XML Object nodeType values text/cdata/none have no OpenAPI 3.1 equivalent; they are stashed on x-apiome-xml-node-type and carried forward (OA6).',
      ownedBy: 'OA6',
      severity: 'info'
    });
  }

  return converted;
}

/**
 * Convert a Parameter Object: fold a deprecated singular `example` into the
 * `examples` map and normalize its schema/content.
 */
function convertParameter(parameter: any, ctx: ConversionContext, path: string): any {
  if (!parameter || typeof parameter !== 'object') {
    return parameter;
  }

  const converted = { ...parameter };

  foldExampleToExamples(converted, ctx, path);

  if (converted.schema) {
    converted.schema = convertSchema(converted.schema, ctx, `${path}.schema`);
  }
  if (converted.content) {
    converted.content = convertContent(converted.content, ctx, `${path}.content`);
  }

  return converted;
}

/**
 * Convert a Request Body Object.
 */
function convertRequestBody(requestBody: any, ctx: ConversionContext, path: string): any {
  if (!requestBody || typeof requestBody !== 'object') {
    return requestBody;
  }
  const converted = { ...requestBody };
  if (converted.content) {
    converted.content = convertContent(converted.content, ctx, `${path}.content`);
  }
  return converted;
}

/**
 * Convert a Response Object.
 */
function convertResponse(response: any, ctx: ConversionContext, path: string): any {
  if (!response || typeof response !== 'object') {
    return response;
  }
  const converted = { ...response };
  if (converted.content) {
    converted.content = convertContent(converted.content, ctx, `${path}.content`);
  }
  if (converted.headers && typeof converted.headers === 'object') {
    converted.headers = convertNamedMap(converted.headers, ctx, `${path}.headers`, convertHeader);
  }
  return converted;
}

/**
 * Convert a Header Object: fold a deprecated singular `example` and normalize
 * its schema/content.
 */
function convertHeader(header: any, ctx: ConversionContext, path: string): any {
  if (!header || typeof header !== 'object') {
    return header;
  }
  const converted = { ...header };
  foldExampleToExamples(converted, ctx, path);
  if (converted.schema) {
    converted.schema = convertSchema(converted.schema, ctx, `${path}.schema`);
  }
  if (converted.content) {
    converted.content = convertContent(converted.content, ctx, `${path}.content`);
  }
  return converted;
}

/**
 * Convert a Content map (`{ mediaType: mediaTypeObject }`). Each Media Type Object
 * has its deprecated `example` folded into `examples`, its schema normalized, and
 * any `itemSchema` (sequential media types / streaming, OA3) stashed.
 */
function convertContent(content: any, ctx: ConversionContext, path: string): any {
  if (!content || typeof content !== 'object') {
    return content;
  }

  const result: any = {};
  for (const [mediaType, mediaTypeObject] of Object.entries<any>(content)) {
    if (!mediaTypeObject || typeof mediaTypeObject !== 'object') {
      result[mediaType] = mediaTypeObject;
      continue;
    }

    const mtPath = `${path}['${mediaType}']`;
    const converted = { ...mediaTypeObject };

    foldExampleToExamples(converted, ctx, mtPath);

    if (converted.schema) {
      converted.schema = convertSchema(converted.schema, ctx, `${mtPath}.schema`);
    }

    // itemSchema (3.2 sequential/streaming media types) — owned by OA3.
    if (converted.itemSchema !== undefined) {
      converted['x-apiome-item-schema'] = converted.itemSchema;
      delete converted.itemSchema;
      recordConstruct(ctx, {
        id: 'item-schema',
        label: 'Sequential media type itemSchema',
        description:
          'Media Type itemSchema (streaming / sequential media types) is stashed on x-apiome-item-schema and carried forward (OA3).',
        ownedBy: 'OA3',
        severity: 'warning'
      });
    }

    result[mediaType] = converted;
  }

  return result;
}

/**
 * Fold a deprecated singular `example` into the `examples` map on a Media Type,
 * Parameter, or Header Object. A pre-existing `examples` map is left untouched
 * (the singular `example` is simply removed). The deprecation is surfaced as an
 * informational warning.
 *
 * Mutates `obj` in place.
 */
function foldExampleToExamples(obj: any, ctx: ConversionContext, path: string): void {
  if (obj.example === undefined) {
    return;
  }

  const exampleValue = obj.example;
  delete obj.example;

  if (obj.examples && typeof obj.examples === 'object') {
    // Keep the richer examples map; just drop the redundant singular form.
    ctx.warnings.push(
      `The deprecated singular "example" at ${path} was dropped in favor of the existing "examples" map (OpenAPI 3.2).`
    );
    return;
  }

  obj.examples = { default: { value: exampleValue } };
  ctx.warnings.push(
    `Folded the deprecated singular "example" at ${path} into the "examples" map (OpenAPI 3.2).`
  );
}

/**
 * Convert the Paths Object.
 */
function convertPaths(paths: any, ctx: ConversionContext): any {
  const result: any = {};
  for (const [pathName, pathItem] of Object.entries<any>(paths)) {
    result[pathName] = convertPathItem(pathItem, ctx, `paths['${pathName}']`);
  }
  return result;
}

/**
 * Convert a Path Item Object. Standard operations are normalized in place; the
 * 3.2-only `additionalOperations` map and the `QUERY` HTTP method are stashed on
 * `x-apiome-*` extensions and carried forward for OA4.
 */
function convertPathItem(pathItem: any, ctx: ConversionContext, path: string): any {
  if (!pathItem || typeof pathItem !== 'object') {
    return pathItem;
  }

  const converted = { ...pathItem };

  if (Array.isArray(converted.parameters)) {
    converted.parameters = converted.parameters.map((param: any, i: number) =>
      convertParameter(param, ctx, `${path}.parameters[${i}]`)
    );
  }

  for (const op of KNOWN_OPERATIONS) {
    if (converted[op]) {
      converted[op] = convertOperation(converted[op], ctx, `${path}.${op}`);
    }
  }

  // QUERY method (3.2) — not a known 3.1 operation key. Stash for OA4.
  if (converted.query && typeof converted.query === 'object') {
    converted['x-apiome-query-operation'] = convertOperation(converted.query, ctx, `${path}.query`);
    delete converted.query;
    recordConstruct(ctx, {
      id: 'query-method',
      label: 'QUERY HTTP method',
      description:
        'The OpenAPI 3.2 QUERY operation is stashed on x-apiome-query-operation and carried forward (OA4).',
      ownedBy: 'OA4',
      severity: 'warning'
    });
  }

  // additionalOperations (3.2) — custom HTTP methods map. Stash for OA4.
  if (converted.additionalOperations && typeof converted.additionalOperations === 'object') {
    const additional: any = {};
    for (const [method, operation] of Object.entries<any>(converted.additionalOperations)) {
      additional[method] = convertOperation(operation, ctx, `${path}.additionalOperations.${method}`);
    }
    converted['x-apiome-additional-operations'] = additional;
    delete converted.additionalOperations;
    recordConstruct(ctx, {
      id: 'additional-operations',
      label: 'additionalOperations (custom HTTP methods)',
      description:
        'The OpenAPI 3.2 additionalOperations map is stashed on x-apiome-additional-operations and carried forward (OA4).',
      ownedBy: 'OA4',
      count: Object.keys(converted['x-apiome-additional-operations']).length,
      severity: 'warning'
    });
  }

  return converted;
}

/**
 * Convert an Operation Object: parameters, request body, and responses.
 */
function convertOperation(operation: any, ctx: ConversionContext, path: string): any {
  if (!operation || typeof operation !== 'object') {
    return operation;
  }

  const converted = { ...operation };

  if (Array.isArray(converted.parameters)) {
    converted.parameters = converted.parameters.map((param: any, i: number) =>
      convertParameter(param, ctx, `${path}.parameters[${i}]`)
    );
  }

  if (converted.requestBody) {
    converted.requestBody = convertRequestBody(converted.requestBody, ctx, `${path}.requestBody`);
  }

  if (converted.responses && typeof converted.responses === 'object') {
    converted.responses = convertNamedMap(converted.responses, ctx, `${path}.responses`, convertResponse);
  }

  return converted;
}
