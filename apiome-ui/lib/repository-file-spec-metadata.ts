import YAML from 'yaml';

const HTTP_METHODS = new Set([
  'get',
  'post',
  'put',
  'patch',
  'delete',
  'head',
  'options',
  'trace',
]);

export type RepositorySpecFormat =
  | 'openapi'
  | 'swagger2'
  | 'asyncapi'
  | 'arazzo'
  | 'json_schema'
  | 'graphql'
  | 'unknown';

export type ParsedRepositorySpecMetadata = {
  format: RepositorySpecFormat;
  /** Human-readable spec line, e.g. "OpenAPI 3.1.0" or "AsyncAPI 2.6.0". */
  spec: string | null;
  title: string | null;
  /** Product / API version (e.g. OpenAPI `info.version`). */
  version: string | null;
  /** Path operations (OpenAPI/Swagger), channel ops (AsyncAPI), workflows (Arazzo), root fields (GraphQL), or null. */
  endpoints: number | null;
  /** Named reusable definitions (OpenAPI `components.*`, AsyncAPI `components.*`, JSON Schema `$defs` / `definitions`). */
  components: number | null;
  /** Server entries (OpenAPI `servers`, AsyncAPI `servers`); Swagger uses schemes/host heuristic. */
  servers: number | null;
  parseError: string | null;
};

function str(v: unknown): string | null {
  if (v == null) return null;
  if (typeof v === 'string') return v.trim() || null;
  if (typeof v === 'number' && Number.isFinite(v)) return String(v);
  return null;
}

/** Detect Swagger / OpenAPI 2.x from the `swagger` field (string "2.x" or JSON numeric `2`). */
function swagger2VersionFromRoot(doc: Record<string, unknown>): string | null {
  const v = doc.swagger;
  if (v == null) return null;
  if (typeof v === 'string') {
    const t = v.trim();
    return t.startsWith('2.') ? t : null;
  }
  if (typeof v === 'number' && Number.isFinite(v) && v >= 2 && v < 3) {
    return String(v);
  }
  return null;
}

function parseYamlOrJson(content: string, path: string): { root: unknown } | { error: string } {
  const t = content.trim();
  if (!t) return { error: 'Empty file' };
  const lowerPath = path.toLowerCase();
  const preferJson = lowerPath.endsWith('.json') || lowerPath.endsWith('.avsc');

  if (preferJson && (t.startsWith('{') || t.startsWith('['))) {
    try {
      return { root: JSON.parse(t) as unknown };
    } catch (e) {
      return { error: e instanceof Error ? e.message : 'Invalid JSON' };
    }
  }

  if (t.startsWith('{') || t.startsWith('[')) {
    try {
      return { root: JSON.parse(t) as unknown };
    } catch {
      /* fall through */
    }
  }

  try {
    const root = YAML.parse(t);
    return { root };
  } catch (e) {
    return { error: e instanceof Error ? e.message : 'Invalid YAML' };
  }
}

function countOpenApiStyleOperations(pathsLike: unknown): number {
  if (!pathsLike || typeof pathsLike !== 'object' || Array.isArray(pathsLike)) return 0;
  let n = 0;
  for (const item of Object.values(pathsLike as Record<string, unknown>)) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) continue;
    for (const [k, v] of Object.entries(item as Record<string, unknown>)) {
      if (HTTP_METHODS.has(k.toLowerCase()) && v != null && typeof v === 'object') n++;
    }
  }
  return n;
}

function countOpenApiComponents(components: unknown): number {
  if (!components || typeof components !== 'object' || Array.isArray(components)) return 0;
  let total = 0;
  for (const bucket of Object.values(components as Record<string, unknown>)) {
    if (bucket && typeof bucket === 'object' && !Array.isArray(bucket)) {
      total += Object.keys(bucket as Record<string, unknown>).length;
    }
  }
  return total;
}

function countSwagger2Components(root: Record<string, unknown>): number {
  let n = 0;
  for (const key of ['definitions', 'parameters', 'responses', 'securityDefinitions']) {
    const b = root[key];
    if (b && typeof b === 'object' && !Array.isArray(b)) {
      n += Object.keys(b as Record<string, unknown>).length;
    }
  }
  return n;
}

function countOpenApiServers(root: Record<string, unknown>): number {
  const servers = root.servers;
  if (Array.isArray(servers)) return servers.length;
  if (servers && typeof servers === 'object' && !Array.isArray(servers)) return 1;
  return 0;
}

function countSwagger2Servers(root: Record<string, unknown>): number {
  const schemes = root.schemes;
  if (Array.isArray(schemes) && schemes.length > 0) return schemes.length;
  const host = str(root.host);
  return host ? 1 : 0;
}

function parseOpenApi(root: Record<string, unknown>): ParsedRepositorySpecMetadata {
  const ver = str(root.openapi);
  const spec = ver ? `OpenAPI ${ver}` : 'OpenAPI';
  const info = root.info && typeof root.info === 'object' ? (root.info as Record<string, unknown>) : {};
  let endpoints = countOpenApiStyleOperations(root.paths);
  if (root.webhooks && typeof root.webhooks === 'object' && !Array.isArray(root.webhooks)) {
    endpoints += countOpenApiStyleOperations(root.webhooks);
  }
  const components = countOpenApiComponents(root.components);
  const servers = countOpenApiServers(root);
  return {
    format: 'openapi',
    spec,
    title: str(info.title),
    version: str(info.version),
    endpoints,
    components,
    servers,
    parseError: null,
  };
}

function parseSwagger2(root: Record<string, unknown>): ParsedRepositorySpecMetadata {
  const info = root.info && typeof root.info === 'object' ? (root.info as Record<string, unknown>) : {};
  return {
    format: 'swagger2',
    spec: 'Swagger 2.0',
    title: str(info.title),
    version: str(info.version),
    endpoints: countOpenApiStyleOperations(root.paths),
    components: countSwagger2Components(root),
    servers: countSwagger2Servers(root),
    parseError: null,
  };
}

function countAsyncApiChannelOperations(channels: unknown): number {
  if (!channels || typeof channels !== 'object' || Array.isArray(channels)) return 0;
  let n = 0;
  for (const ch of Object.values(channels as Record<string, unknown>)) {
    if (!ch || typeof ch !== 'object' || Array.isArray(ch)) continue;
    const o = ch as Record<string, unknown>;
    if (o.subscribe != null && typeof o.subscribe === 'object') n++;
    if (o.publish != null && typeof o.publish === 'object') n++;
  }
  return n;
}

function countAsyncApiComponents(components: unknown): number {
  return countOpenApiComponents(components);
}

function countAsyncApiServers(servers: unknown): number {
  if (Array.isArray(servers)) return servers.length;
  if (servers && typeof servers === 'object' && !Array.isArray(servers)) {
    return Object.keys(servers as Record<string, unknown>).length;
  }
  return 0;
}

function parseAsyncApi(root: Record<string, unknown>): ParsedRepositorySpecMetadata {
  const ver = str(root.asyncapi);
  const spec = ver ? `AsyncAPI ${ver}` : 'AsyncAPI';
  const info = root.info && typeof root.info === 'object' ? (root.info as Record<string, unknown>) : {};
  return {
    format: 'asyncapi',
    spec,
    title: str(info.title),
    version: str(info.version),
    endpoints: countAsyncApiChannelOperations(root.channels),
    components: countAsyncApiComponents(root.components),
    servers: countAsyncApiServers(root.servers),
    parseError: null,
  };
}

function parseArazzo(root: Record<string, unknown>): ParsedRepositorySpecMetadata {
  const ver = str(root.arazzo);
  const spec = ver ? `Arazzo ${ver}` : 'Arazzo';
  const info = root.info && typeof root.info === 'object' ? (root.info as Record<string, unknown>) : {};
  const workflows = root.workflows;
  let wfCount = 0;
  if (workflows && typeof workflows === 'object' && !Array.isArray(workflows)) {
    wfCount = Object.keys(workflows as Record<string, unknown>).length;
  }
  return {
    format: 'arazzo',
    spec,
    title: str(info.title) ?? str(info.summary),
    version: str(info.version),
    endpoints: wfCount,
    components: countOpenApiComponents(root.components),
    servers: countAsyncApiServers(root.servers),
    parseError: null,
  };
}

function jsonSchemaTitle(root: Record<string, unknown>): string | null {
  return str(root.title) ?? str(root['x-title']);
}

function countJsonSchemaDefs(root: Record<string, unknown>): number {
  const defs = root.$defs ?? root.definitions;
  if (defs && typeof defs === 'object' && !Array.isArray(defs)) {
    return Object.keys(defs as Record<string, unknown>).length;
  }
  return 0;
}

function parseJsonSchema(root: Record<string, unknown>): ParsedRepositorySpecMetadata {
  const schemaUri = str(root.$schema);
  const id = str(root.$id);
  const spec =
    schemaUri && schemaUri.includes('json-schema')
      ? `JSON Schema (${schemaUri.split('/').pop() ?? schemaUri})`
      : id
        ? `JSON Schema (${id})`
        : 'JSON Schema';
  return {
    format: 'json_schema',
    spec,
    title: jsonSchemaTitle(root),
    version: str(root.version),
    endpoints: null,
    components: countJsonSchemaDefs(root),
    servers: null,
    parseError: null,
  };
}

function extractGraphqlTypeBody(content: string, typeName: string): string | null {
  const re = new RegExp(`\\b(?:extend\\s+)?type\\s+${typeName}\\s*\\{`, 'm');
  const m = content.match(re);
  if (!m || m.index === undefined) return null;
  let i = m.index + m[0].length;
  let depth = 1;
  const start = i;
  while (i < content.length && depth > 0) {
    const c = content[i];
    if (c === '{') depth++;
    else if (c === '}') depth--;
    if (depth === 0) return content.slice(start, i);
    i++;
  }
  return null;
}

function countGraphqlFieldsInBlock(block: string): number {
  let n = 0;
  const lines = block.split('\n');
  const skip = new Set([
    'implements',
    'repeatable',
    'extend',
    'scalar',
    'type',
    'enum',
    'input',
    'interface',
    'union',
    'directive',
    'schema',
  ]);
  for (const raw of lines) {
    const line = raw.replace(/#[^\n]*$/, '').trim();
    if (!line || line.startsWith('@') || line.startsWith('"') || line.startsWith("'")) continue;
    const mm = /^([A-Za-z_][\w]*)\s*[:(]/.exec(line);
    if (mm && !skip.has(mm[1].toLowerCase())) n++;
  }
  return n;
}

function parseGraphqlSdl(content: string): ParsedRepositorySpecMetadata {
  let endpoints = 0;
  for (const t of ['Query', 'Mutation', 'Subscription']) {
    const body = extractGraphqlTypeBody(content, t);
    if (body) endpoints += countGraphqlFieldsInBlock(body);
  }
  return {
    format: 'graphql',
    spec: 'GraphQL SDL',
    title: null,
    version: null,
    endpoints: endpoints > 0 ? endpoints : null,
    components: null,
    servers: null,
    parseError: null,
  };
}

function isLikelyJsonSchema(root: Record<string, unknown>): boolean {
  if (root.$schema != null && typeof root.$schema === 'string' && root.$schema.includes('json-schema')) return true;
  if (root.$defs != null && typeof root.$defs === 'object') return true;
  if (
    root.definitions != null &&
    typeof root.definitions === 'object' &&
    root.$schema != null &&
    typeof root.$schema === 'string'
  ) {
    return true;
  }
  return false;
}

function isLikelyGraphQl(content: string, root: unknown): boolean {
  if (root && typeof root === 'object') return false;
  const t = content.trim();
  if (!t) return false;
  if (/\b(type|extend)\s+(Query|Mutation|Subscription)\s*\{/m.test(t)) return true;
  if (/^\s*"""[\s\S]*"""\s*\n\s*type\s+\w+/m.test(t)) return true;
  return false;
}

function unknownMeta(error: string | null): ParsedRepositorySpecMetadata {
  return {
    format: 'unknown',
    spec: null,
    title: null,
    version: null,
    endpoints: null,
    components: null,
    servers: null,
    parseError: error,
  };
}

const IMPORTABLE_SPEC_FORMATS: ReadonlySet<RepositorySpecFormat> = new Set([
  'openapi',
  'swagger2',
  'asyncapi',
  'arazzo',
  'json_schema',
  'graphql',
]);

/** When the `openapi` field is present but not a 3.x semver we can read from metadata. */
export const REPOSITORY_OPENAPI_VERSION_UNCLEAR_MESSAGE =
  'Could not confirm an OpenAPI 3.x version in this document. Map & import requires OpenAPI 3.0 or 3.1.';

function openApiMajorFromParsedMetadata(meta: ParsedRepositorySpecMetadata): number | null {
  if (meta.format !== 'openapi') return null;
  const spec = meta.spec?.trim() ?? '';
  const m = /^OpenAPI\s+([\d.]+)/i.exec(spec);
  if (!m?.[1]) return null;
  const first = m[1].split('.')[0] ?? '';
  const major = parseInt(first, 10);
  return Number.isFinite(major) ? major : null;
}

export type RepositoryImportableVerdictStatus =
  | 'content_unavailable'
  | 'parse_failed'
  | 'not_importable'
  | 'importable';

/**
 * Normalised verdict once repository file content is loaded in the detail UI.
 * Safe to JSON.stringify for tooling, tests, or data attributes.
 */
export type RepositoryImportableVerdict = {
  status: RepositoryImportableVerdictStatus;
  /** Stable token for automation (matches `status` unless truncated importable). */
  summary: string;
  format: RepositorySpecFormat | null;
  loadError?: string;
  parseError?: string;
  truncated?: boolean;
  /** Set when `status === 'importable'`. */
  spec?: string | null;
  /** Set when `status === 'not_importable'` and a concrete reason exists (e.g. unsupported OpenAPI version). */
  notImportableMessage?: string;
};

export function getRepositoryFileImportableVerdict(
  meta: ParsedRepositorySpecMetadata,
  ctx: { loadError: string | null; truncated?: boolean }
): RepositoryImportableVerdict {
  if (ctx.loadError) {
    return {
      status: 'content_unavailable',
      summary: 'content_unavailable',
      format: null,
      loadError: ctx.loadError,
    };
  }

  if (meta.parseError) {
    return {
      status: 'parse_failed',
      summary: 'parse_failed',
      format: meta.format === 'unknown' ? null : meta.format,
      parseError: meta.parseError,
    };
  }

  if (meta.format === 'unknown' || !IMPORTABLE_SPEC_FORMATS.has(meta.format)) {
    return {
      status: 'not_importable',
      summary: 'not_importable',
      format: 'unknown',
    };
  }

  if (meta.format === 'openapi') {
    const major = openApiMajorFromParsedMetadata(meta);
    if (major == null || major < 3) {
      const notImportableMessage =
        major != null && major < 3
          ? `This file declares OpenAPI ${major}.x. Only OpenAPI 3.0 and 3.1 are supported for repository map and import.`
          : REPOSITORY_OPENAPI_VERSION_UNCLEAR_MESSAGE;
      return {
        status: 'not_importable',
        summary: 'unsupported_openapi_version',
        format: 'openapi',
        notImportableMessage,
      };
    }
  }

  const truncated = ctx.truncated === true;
  return {
    status: 'importable',
    summary: truncated ? 'importable_truncated_body' : 'importable',
    format: meta.format,
    spec: meta.spec,
    truncated: truncated || undefined,
  };
}

export function formatMetadataCell(n: number | null): string {
  if (n == null) return '—';
  return n.toLocaleString();
}

/** Max rows per section before truncation (large specs). */
const DETAIL_TABLE_ROW_CAP = 400;

export type RepositoryFileDetailClassRow = {
  name: string;
  kind: string;
  description?: string;
  /** Primary JSON Schema / OpenAPI schema.type (when known). */
  typeSummary?: string;
  /** Number of object properties when `properties` is present. */
  propertiesCount?: number;
};

export type RepositoryFileDetailPropertyRow = {
  name: string;
  context: string;
  typeOrConstraint?: string;
  required?: boolean;
  description?: string;
  format?: string;
  defaultValue?: string;
};

export type RepositoryFileDetailPathRow = {
  template: string;
  /** HTTP verb, subscribe/publish, workflow, GraphQL root type, etc. */
  method?: string;
  operationId?: string;
  summary?: string;
  description?: string;
  tags?: string;
};

export type RepositoryFileDetailTables = {
  format: RepositorySpecFormat;
  parseError: string | null;
  classes: RepositoryFileDetailClassRow[];
  properties: RepositoryFileDetailPropertyRow[];
  paths: RepositoryFileDetailPathRow[];
  truncated: { classes: boolean; properties: boolean; paths: boolean };
};

export type ParsedRepositoryFileSpecFull = {
  meta: ParsedRepositorySpecMetadata;
  /** YAML/JSON document root when parse succeeded as an object mapping. */
  doc: Record<string, unknown> | null;
  /** Raw SDL text when the file is treated as GraphQL. */
  graphqlSdl: string | null;
};

function parseRepositoryFileSpecFullInternal(content: string, path: string): ParsedRepositoryFileSpecFull {
  if (!content.trim()) {
    return { meta: unknownMeta(null), doc: null, graphqlSdl: null };
  }

  const parsed = parseYamlOrJson(content, path);
  if ('error' in parsed) {
    if (isLikelyGraphQl(content, null)) {
      try {
        return { meta: parseGraphqlSdl(content), doc: null, graphqlSdl: content };
      } catch {
        return { meta: unknownMeta(parsed.error), doc: null, graphqlSdl: null };
      }
    }
    return { meta: unknownMeta(parsed.error), doc: null, graphqlSdl: null };
  }

  const root = parsed.root;
  if (root == null || typeof root !== 'object' || Array.isArray(root)) {
    if (typeof root === 'string' && isLikelyGraphQl(root, null)) {
      return { meta: parseGraphqlSdl(root), doc: null, graphqlSdl: root };
    }
    if (isLikelyGraphQl(content, null)) {
      return { meta: parseGraphqlSdl(content), doc: null, graphqlSdl: content };
    }
    return { meta: unknownMeta('Document is not a mapping object'), doc: null, graphqlSdl: null };
  }

  const doc = root as Record<string, unknown>;

  if (doc.openapi != null && (typeof doc.openapi === 'string' || typeof doc.openapi === 'number')) {
    return { meta: parseOpenApi(doc), doc, graphqlSdl: null };
  }
  if (swagger2VersionFromRoot(doc) != null) {
    return { meta: parseSwagger2(doc), doc, graphqlSdl: null };
  }
  if (doc.asyncapi != null) {
    return { meta: parseAsyncApi(doc), doc, graphqlSdl: null };
  }
  if (doc.arazzo != null) {
    return { meta: parseArazzo(doc), doc, graphqlSdl: null };
  }
  if (isLikelyJsonSchema(doc)) {
    return { meta: parseJsonSchema(doc), doc, graphqlSdl: null };
  }
  if (isLikelyGraphQl(content, root)) {
    return { meta: parseGraphqlSdl(content), doc: null, graphqlSdl: content };
  }

  return { meta: unknownMeta(null), doc: null, graphqlSdl: null };
}

/**
 * Full parse: metadata plus document root (when YAML/JSON) or GraphQL SDL text for detail extraction.
 */
export function parseRepositoryFileSpecFull(content: string, path: string): ParsedRepositoryFileSpecFull {
  return parseRepositoryFileSpecFullInternal(content, path);
}

/** Best-effort client-side parse of API specification metadata for the repository file detail panel. */
export function parseRepositoryFileSpecMetadata(content: string, path: string): ParsedRepositorySpecMetadata {
  return parseRepositoryFileSpecFullInternal(content, path).meta;
}

/** Longer blurbs for detail tables (classes / components). */
function mediumDescription(node: unknown): string | undefined {
  if (!node || typeof node !== 'object' || Array.isArray(node)) return undefined;
  const d = str((node as Record<string, unknown>).description) ?? str((node as Record<string, unknown>).title);
  if (!d) return undefined;
  return d.length > 320 ? `${d.slice(0, 317)}…` : d;
}

function tableCellText(s: string | null | undefined, max: number): string | undefined {
  if (s == null) return undefined;
  const t = s.trim();
  if (!t) return undefined;
  return t.length > max ? `${t.slice(0, max - 1)}…` : t;
}

function formatOpenApiTags(tags: unknown): string | undefined {
  if (!Array.isArray(tags) || tags.length === 0) return undefined;
  const parts: string[] = [];
  for (const t of tags) {
    if (typeof t === 'string') parts.push(t);
    else if (t && typeof t === 'object' && typeof (t as Record<string, unknown>).name === 'string') {
      parts.push((t as Record<string, unknown>).name as string);
    }
  }
  return parts.length ? parts.join(', ') : undefined;
}

function defaultPreview(node: unknown): string | undefined {
  if (!node || typeof node !== 'object' || Array.isArray(node)) return undefined;
  const dv = (node as Record<string, unknown>).default;
  if (dv === undefined) return undefined;
  try {
    const s = JSON.stringify(dv);
    return s.length > 120 ? `${s.slice(0, 117)}…` : s;
  } catch {
    return String(dv);
  }
}

function schemaShapeSummary(node: unknown): { typeSummary?: string; propertiesCount?: number } {
  if (!node || typeof node !== 'object' || Array.isArray(node)) return {};
  const o = node as Record<string, unknown>;
  const t = o.type;
  let typeSummary: string | undefined;
  if (typeof t === 'string') typeSummary = t;
  else if (Array.isArray(t)) typeSummary = t.map(String).join(' | ');
  const props = o.properties;
  let propertiesCount: number | undefined;
  if (props && typeof props === 'object' && !Array.isArray(props)) {
    propertiesCount = Object.keys(props).length;
  }
  return { typeSummary, propertiesCount };
}

function summarizeJsonSchemaShorthand(node: unknown): string {
  if (node == null) return '—';
  if (typeof node !== 'object' || Array.isArray(node)) return typeof node;
  const o = node as Record<string, unknown>;
  const ref = str(o.$ref);
  if (ref) {
    const seg = ref.split('/').pop() ?? ref;
    return seg;
  }
  const t = o.type;
  if (typeof t === 'string') return t;
  if (Array.isArray(t)) return t.map(String).join(' | ');
  if (o.enum != null && Array.isArray(o.enum)) return `enum(${o.enum.length})`;
  if (o.oneOf != null) return 'oneOf';
  if (o.anyOf != null) return 'anyOf';
  if (o.allOf != null) return 'allOf';
  if (o.properties != null && typeof o.properties === 'object') return 'object';
  return 'object';
}

function takeCap<T>(rows: T[], cap: number): { rows: T[]; truncated: boolean } {
  if (rows.length <= cap) return { rows, truncated: false };
  return { rows: rows.slice(0, cap), truncated: true };
}

function openApiStylePathRows(pathsLike: unknown, prefix: string): RepositoryFileDetailPathRow[] {
  if (!pathsLike || typeof pathsLike !== 'object' || Array.isArray(pathsLike)) return [];
  const out: RepositoryFileDetailPathRow[] = [];
  for (const [pathKey, item] of Object.entries(pathsLike as Record<string, unknown>)) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) continue;
    const template = prefix ? `${prefix}${pathKey}` : pathKey;
    for (const [k, v] of Object.entries(item as Record<string, unknown>)) {
      if (!HTTP_METHODS.has(k.toLowerCase()) || v == null || typeof v !== 'object' || Array.isArray(v)) continue;
      const op = v as Record<string, unknown>;
      out.push({
        template,
        method: k.toUpperCase(),
        operationId: str(op.operationId) ?? undefined,
        summary: str(op.summary) ?? undefined,
        description: tableCellText(str(op.description), 800),
        tags: formatOpenApiTags(op.tags),
      });
    }
  }
  return out.sort((a, b) => {
    const p = a.template.localeCompare(b.template);
    if (p !== 0) return p;
    return (a.method ?? '').localeCompare(b.method ?? '');
  });
}

function componentsSchemas(doc: Record<string, unknown>): Record<string, unknown> | null {
  const c = doc.components;
  if (!c || typeof c !== 'object' || Array.isArray(c)) return null;
  const schemas = (c as Record<string, unknown>).schemas;
  if (!schemas || typeof schemas !== 'object' || Array.isArray(schemas)) return null;
  return schemas as Record<string, unknown>;
}

function swaggerDefinitions(doc: Record<string, unknown>): Record<string, unknown> | null {
  const d = doc.definitions;
  if (!d || typeof d !== 'object' || Array.isArray(d)) return null;
  return d as Record<string, unknown>;
}

function collectSchemaPropertyRows(
  schemas: Record<string, unknown>,
  budget: { left: number }
): { rows: RepositoryFileDetailPropertyRow[]; truncated: boolean } {
  const rows: RepositoryFileDetailPropertyRow[] = [];
  let truncated = false;
  const names = Object.keys(schemas).sort();
  outer: for (const schemaName of names) {
    const schema = schemas[schemaName];
    if (!schema || typeof schema !== 'object' || Array.isArray(schema)) continue;
    const schemaObj = schema as Record<string, unknown>;
    const props = schemaObj.properties;
    if (!props || typeof props !== 'object' || Array.isArray(props)) continue;
    const requiredSet = new Set<string>();
    const req = schemaObj.required;
    if (Array.isArray(req)) {
      for (const r of req) {
        if (typeof r === 'string') requiredSet.add(r);
      }
    }
    for (const propName of Object.keys(props as Record<string, unknown>).sort()) {
      if (budget.left <= 0) {
        truncated = true;
        break outer;
      }
      const propNode = (props as Record<string, unknown>)[propName];
      const po = propNode && typeof propNode === 'object' && !Array.isArray(propNode) ? (propNode as Record<string, unknown>) : null;
      rows.push({
        name: propName,
        context: schemaName,
        typeOrConstraint: summarizeJsonSchemaShorthand(propNode),
        required: requiredSet.has(propName),
        description: tableCellText(po ? str(po.description) : undefined, 600),
        format: po ? str(po.format) ?? undefined : undefined,
        defaultValue: defaultPreview(propNode),
      });
      budget.left--;
    }
  }
  return { rows, truncated };
}

function openApiComponentsClasses(components: unknown): RepositoryFileDetailClassRow[] {
  if (!components || typeof components !== 'object' || Array.isArray(components)) return [];
  const buckets = components as Record<string, unknown>;
  const rows: RepositoryFileDetailClassRow[] = [];
  for (const bucketName of Object.keys(buckets).sort()) {
    const bucket = buckets[bucketName];
    if (!bucket || typeof bucket !== 'object' || Array.isArray(bucket)) continue;
    for (const name of Object.keys(bucket as Record<string, unknown>).sort()) {
      const node = (bucket as Record<string, unknown>)[name];
      const shape = schemaShapeSummary(node);
      rows.push({
        name,
        kind: bucketName,
        description: mediumDescription(node),
        typeSummary: shape.typeSummary,
        propertiesCount: shape.propertiesCount,
      });
    }
  }
  return rows;
}

function jsonSchemaDetail(doc: Record<string, unknown>): Omit<RepositoryFileDetailTables, 'format' | 'parseError'> {
  const defs = doc.$defs ?? doc.definitions;
  const classes: RepositoryFileDetailClassRow[] = [];
  const properties: RepositoryFileDetailPropertyRow[] = [];

  if (defs && typeof defs === 'object' && !Array.isArray(defs)) {
    const schemas = defs as Record<string, unknown>;
    for (const name of Object.keys(schemas).sort()) {
      const node = schemas[name];
      const shape = schemaShapeSummary(node);
      classes.push({
        name,
        kind: 'definition',
        description: mediumDescription(node),
        typeSummary: shape.typeSummary,
        propertiesCount: shape.propertiesCount,
      });
    }
    const budget = { left: DETAIL_TABLE_ROW_CAP };
    const { rows: propRows, truncated: prTrunc } = collectSchemaPropertyRows(schemas, budget);
    properties.push(...propRows);
    const { rows: clsRows, truncated: clsTrunc } = takeCap(classes, DETAIL_TABLE_ROW_CAP);
    const { rows: cappedProps, truncated: capTrunc } = takeCap(properties, DETAIL_TABLE_ROW_CAP);
    return {
      classes: clsRows,
      properties: cappedProps,
      paths: [],
      truncated: { classes: clsTrunc, properties: prTrunc || capTrunc, paths: false },
    };
  }

  const rootProps = doc.properties;
  let propertiesTruncated = false;
  if (rootProps && typeof rootProps === 'object' && !Array.isArray(rootProps)) {
    const title = str(doc.title) ?? '(root)';
    const shape = schemaShapeSummary(doc);
    classes.push({
      name: title,
      kind: 'schema',
      description: mediumDescription(doc),
      typeSummary: shape.typeSummary,
      propertiesCount: shape.propertiesCount,
    });
    const requiredSet = new Set<string>();
    const reqRoot = doc.required;
    if (Array.isArray(reqRoot)) {
      for (const r of reqRoot) {
        if (typeof r === 'string') requiredSet.add(r);
      }
    }
    const keys = Object.keys(rootProps as Record<string, unknown>).sort();
    for (const propName of keys) {
      if (properties.length >= DETAIL_TABLE_ROW_CAP) {
        propertiesTruncated = true;
        break;
      }
      const propNode = (rootProps as Record<string, unknown>)[propName];
      const po =
        propNode && typeof propNode === 'object' && !Array.isArray(propNode)
          ? (propNode as Record<string, unknown>)
          : null;
      properties.push({
        name: propName,
        context: title,
        typeOrConstraint: summarizeJsonSchemaShorthand(propNode),
        required: requiredSet.has(propName),
        description: tableCellText(po ? str(po.description) : undefined, 600),
        format: po ? str(po.format) ?? undefined : undefined,
        defaultValue: defaultPreview(propNode),
      });
    }
  }

  return {
    classes,
    properties,
    paths: [],
    truncated: {
      classes: false,
      properties: propertiesTruncated,
      paths: false,
    },
  };
}

function asyncApiChannelPathRows(channels: unknown): RepositoryFileDetailPathRow[] {
  const paths: RepositoryFileDetailPathRow[] = [];
  if (!channels || typeof channels !== 'object' || Array.isArray(channels)) return paths;

  const extractMessageHints = (block: Record<string, unknown>): { name?: string; detail?: string } => {
    const msg = block.message;
    if (!msg || typeof msg !== 'object' || Array.isArray(msg)) return {};
    const m = msg as Record<string, unknown>;
    const ref = str(m['$ref']);
    const name = (str(m.name) ?? str(m.title) ?? (ref ? ref.split('/').pop() ?? null : null)) ?? undefined;
    const detail = (str(m.summary) ?? str(m.description) ?? ref) ?? undefined;
    return { name, detail };
  };

  for (const channel of Object.keys(channels as Record<string, unknown>).sort()) {
    const node = (channels as Record<string, unknown>)[channel];
    if (!node || typeof node !== 'object' || Array.isArray(node)) continue;
    const o = node as Record<string, unknown>;
    const channelSummary = tableCellText(str(o.summary) ?? str(o.description), 400);

    const addSide = (method: 'subscribe' | 'publish', sideBlock: unknown) => {
      if (!sideBlock || typeof sideBlock !== 'object' || Array.isArray(sideBlock)) return;
      const b = sideBlock as Record<string, unknown>;
      const hints = extractMessageHints(b);
      const sideSummary = str(b.summary);
      paths.push({
        template: channel,
        method,
        operationId: hints.name,
        summary: sideSummary ?? hints.detail ?? channelSummary ?? undefined,
        description: tableCellText([channelSummary, hints.detail].filter(Boolean).join(' — '), 800),
        tags: undefined,
      });
    };

    addSide('subscribe', o.subscribe);
    addSide('publish', o.publish);
  }

  return paths.sort((a, b) => {
    const c = a.template.localeCompare(b.template);
    if (c !== 0) return c;
    return (a.method ?? '').localeCompare(b.method ?? '');
  });
}

function asyncApiDetail(doc: Record<string, unknown>): Omit<RepositoryFileDetailTables, 'format' | 'parseError'> {
  const paths = asyncApiChannelPathRows(doc.channels);

  const classes = openApiComponentsClasses(doc.components);
  const schemas = componentsSchemas(doc);
  const budget = { left: DETAIL_TABLE_ROW_CAP };
  const propCollect = schemas ? collectSchemaPropertyRows(schemas, budget) : { rows: [], truncated: false };

  const { rows: pRows, truncated: pTrunc } = takeCap(paths, DETAIL_TABLE_ROW_CAP);
  const { rows: cRows, truncated: cTrunc } = takeCap(classes, DETAIL_TABLE_ROW_CAP);
  const { rows: prRows, truncated: prCapTrunc } = takeCap(propCollect.rows, DETAIL_TABLE_ROW_CAP);

  return {
    paths: pRows,
    classes: cRows,
    properties: prRows,
    truncated: {
      paths: pTrunc,
      classes: cTrunc,
      properties: propCollect.truncated || prCapTrunc,
    },
  };
}

function arazzoDetail(doc: Record<string, unknown>): Omit<RepositoryFileDetailTables, 'format' | 'parseError'> {
  const paths: RepositoryFileDetailPathRow[] = [];
  const wf = doc.workflows;
  if (wf && typeof wf === 'object' && !Array.isArray(wf)) {
    for (const id of Object.keys(wf as Record<string, unknown>).sort()) {
      const node = (wf as Record<string, unknown>)[id];
      let summary = '';
      let descText = '';
      let steps = '';
      if (node && typeof node === 'object' && !Array.isArray(node)) {
        const o = node as Record<string, unknown>;
        summary = str(o.summary) ?? '';
        descText = str(o.description) ?? '';
        const st = o.steps;
        if (Array.isArray(st)) steps = `${st.length} step(s)`;
      }
      paths.push({
        template: id,
        method: 'workflow',
        summary: summary ? (steps ? `${summary} (${steps})` : summary) : steps || descText || undefined,
        description: tableCellText(descText, 800),
      });
    }
  }
  const classes = openApiComponentsClasses(doc.components);
  const { rows: pRows, truncated: pTrunc } = takeCap(paths, DETAIL_TABLE_ROW_CAP);
  const { rows: cRows, truncated: cTrunc } = takeCap(classes, DETAIL_TABLE_ROW_CAP);
  return {
    paths: pRows,
    classes: cRows,
    properties: [],
    truncated: { paths: pTrunc, classes: cTrunc, properties: false },
  };
}

function graphqlTypeDeclarations(sdl: string): Array<{ kind: string; name: string; body: string }> {
  const out: Array<{ kind: string; name: string; body: string }> = [];
  const re = /\b(?:extend\s+)?(type|input|interface|enum)\s+(\w+)\s*(?:implements\s+[\w\s&]+)?\s*\{/gi;
  let m: RegExpExecArray | null;
  while ((m = re.exec(sdl)) !== null) {
    const kind = m[1].toLowerCase();
    const name = m[2];
    const openBrace = m.index + m[0].length - 1;
    let i = openBrace + 1;
    let depth = 1;
    const start = i;
    while (i < sdl.length && depth > 0) {
      const c = sdl[i];
      if (c === '{') depth++;
      else if (c === '}') depth--;
      if (depth === 0) break;
      i++;
    }
    const body = depth === 0 ? sdl.slice(start, i) : '';
    out.push({ kind, name, body });
  }
  return out;
}

function parseGraphqlFieldLines(body: string): Array<{ name: string; signature: string }> {
  const fields: Array<{ name: string; signature: string }> = [];
  const lines = body.split('\n');
  for (const raw of lines) {
    const line = raw.replace(/#[^\n]*$/, '').trim();
    if (!line || line.startsWith('@')) continue;
    const mm = /^\s*([A-Za-z_][\w]*)\s*(.*)$/.exec(line);
    if (!mm) continue;
    const fname = mm[1];
    const reserved = new Set([
      'implements',
      'repeatable',
      'extend',
      'scalar',
      'type',
      'enum',
      'input',
      'interface',
      'union',
      'directive',
      'schema',
    ]);
    if (reserved.has(fname.toLowerCase())) continue;
    const rest = mm[2].trim();
    fields.push({ name: fname, signature: rest });
  }
  return fields;
}

function graphqlDetail(sdl: string): Omit<RepositoryFileDetailTables, 'format' | 'parseError'> {
  const classes: RepositoryFileDetailClassRow[] = [];
  const properties: RepositoryFileDetailPropertyRow[] = [];
  const paths: RepositoryFileDetailPathRow[] = [];

  const decls = graphqlTypeDeclarations(sdl);
  const rootOps = new Set(['query', 'mutation', 'subscription']);

  for (const d of decls) {
    if (rootOps.has(d.name.toLowerCase())) {
      for (const f of parseGraphqlFieldLines(d.body)) {
        if (paths.length >= DETAIL_TABLE_ROW_CAP) break;
        paths.push({
          template: f.name,
          method: d.name,
          summary: undefined,
          description: tableCellText(f.signature, 1200),
        });
      }
      continue;
    }

    if (classes.length < DETAIL_TABLE_ROW_CAP) {
      classes.push({
        name: d.name,
        kind: d.kind,
        description: undefined,
      });
    }

    if (d.kind === 'enum') {
      const values = d.body
        .split(/[\s,]+/)
        .map((s) => s.trim())
        .filter(Boolean);
      for (const v of values) {
        if (properties.length >= DETAIL_TABLE_ROW_CAP) break;
        if (/^[_A-Za-z][_\w]*$/.test(v)) {
          properties.push({ name: v, context: d.name, typeOrConstraint: 'enum value' });
        }
      }
      continue;
    }

    for (const f of parseGraphqlFieldLines(d.body)) {
      if (properties.length >= DETAIL_TABLE_ROW_CAP) break;
      properties.push({
        name: f.name,
        context: d.name,
        typeOrConstraint: f.signature || undefined,
      });
    }
  }

  const { rows: cRows, truncated: cTrunc } = takeCap(classes, DETAIL_TABLE_ROW_CAP);
  const { rows: prRows, truncated: prTrunc } = takeCap(properties, DETAIL_TABLE_ROW_CAP);
  const { rows: pRows, truncated: pTrunc } = takeCap(paths, DETAIL_TABLE_ROW_CAP);

  return {
    classes: cRows,
    properties: prRows,
    paths: pRows,
    truncated: { classes: cTrunc, properties: prTrunc, paths: pTrunc },
  };
}

function openApiFamilyDetail(doc: Record<string, unknown>): Omit<RepositoryFileDetailTables, 'format' | 'parseError'> {
  const paths = [
    ...openApiStylePathRows(doc.paths, ''),
    ...openApiStylePathRows(doc.webhooks, 'webhook:'),
  ].sort((a, b) => a.template.localeCompare(b.template));

  const schemas = componentsSchemas(doc);
  const classesFromSchemas: RepositoryFileDetailClassRow[] = schemas
    ? Object.keys(schemas)
        .sort()
        .map((name) => {
          const node = schemas[name];
          const shape = schemaShapeSummary(node);
          return {
            name,
            kind: 'schemas',
            description: mediumDescription(node),
            typeSummary: shape.typeSummary,
            propertiesCount: shape.propertiesCount,
          };
        })
    : [];

  const otherComponents = doc.components;
  const restClasses: RepositoryFileDetailClassRow[] = [];
  if (otherComponents && typeof otherComponents === 'object' && !Array.isArray(otherComponents)) {
    for (const bucketName of Object.keys(otherComponents as Record<string, unknown>).sort()) {
      if (bucketName === 'schemas') continue;
      const bucket = (otherComponents as Record<string, unknown>)[bucketName];
      if (!bucket || typeof bucket !== 'object' || Array.isArray(bucket)) continue;
      for (const name of Object.keys(bucket as Record<string, unknown>).sort()) {
        const node = (bucket as Record<string, unknown>)[name];
        const shape = schemaShapeSummary(node);
        restClasses.push({
          name,
          kind: bucketName,
          description: mediumDescription(node),
          typeSummary: shape.typeSummary,
          propertiesCount: shape.propertiesCount,
        });
      }
    }
  }

  const classes = [...classesFromSchemas, ...restClasses].sort((a, b) =>
    `${a.kind}:${a.name}`.localeCompare(`${b.kind}:${b.name}`)
  );

  const budget = { left: DETAIL_TABLE_ROW_CAP };
  const propCollect = schemas ? collectSchemaPropertyRows(schemas, budget) : { rows: [], truncated: false };

  const { rows: pRows, truncated: pTrunc } = takeCap(paths, DETAIL_TABLE_ROW_CAP);
  const { rows: cRows, truncated: cTrunc } = takeCap(classes, DETAIL_TABLE_ROW_CAP);
  const { rows: prRows, truncated: prCapTrunc } = takeCap(propCollect.rows, DETAIL_TABLE_ROW_CAP);

  return {
    paths: pRows,
    classes: cRows,
    properties: prRows,
    truncated: {
      paths: pTrunc,
      classes: cTrunc,
      properties: propCollect.truncated || prCapTrunc,
    },
  };
}

function swagger2Detail(doc: Record<string, unknown>): Omit<RepositoryFileDetailTables, 'format' | 'parseError'> {
  const paths = openApiStylePathRows(doc.paths, '');
  const defs = swaggerDefinitions(doc);
  const classesFromDefs: RepositoryFileDetailClassRow[] = defs
    ? Object.keys(defs)
        .sort()
        .map((name) => {
          const node = defs[name];
          const shape = schemaShapeSummary(node);
          return {
            name,
            kind: 'definitions',
            description: mediumDescription(node),
            typeSummary: shape.typeSummary,
            propertiesCount: shape.propertiesCount,
          };
        })
    : [];

  const extraBuckets = ['parameters', 'responses', 'securityDefinitions'] as const;
  const restClasses: RepositoryFileDetailClassRow[] = [];
  for (const key of extraBuckets) {
    const bucket = doc[key];
    if (!bucket || typeof bucket !== 'object' || Array.isArray(bucket)) continue;
    for (const name of Object.keys(bucket as Record<string, unknown>).sort()) {
      const node = (bucket as Record<string, unknown>)[name];
      const shape = schemaShapeSummary(node);
      restClasses.push({
        name,
        kind: key,
        description: mediumDescription(node),
        typeSummary: shape.typeSummary,
        propertiesCount: shape.propertiesCount,
      });
    }
  }

  const classes = [...classesFromDefs, ...restClasses];
  const budget = { left: DETAIL_TABLE_ROW_CAP };
  const propCollect = defs ? collectSchemaPropertyRows(defs, budget) : { rows: [], truncated: false };

  const { rows: pRows, truncated: pTrunc } = takeCap(paths, DETAIL_TABLE_ROW_CAP);
  const { rows: cRows, truncated: cTrunc } = takeCap(classes, DETAIL_TABLE_ROW_CAP);
  const { rows: prRows, truncated: prCapTrunc } = takeCap(propCollect.rows, DETAIL_TABLE_ROW_CAP);

  return {
    paths: pRows,
    classes: cRows,
    properties: prRows,
    truncated: {
      paths: pTrunc,
      classes: cTrunc,
      properties: propCollect.truncated || prCapTrunc,
    },
  };
}

/**
 * Structured class / property / path lists for the repository file Details tab.
 */
export function extractRepositoryFileDetailTables(content: string, path: string): RepositoryFileDetailTables {
  const full = parseRepositoryFileSpecFullInternal(content, path);
  const { meta, doc, graphqlSdl } = full;

  if (meta.parseError) {
    return {
      format: meta.format,
      parseError: meta.parseError,
      classes: [],
      properties: [],
      paths: [],
      truncated: { classes: false, properties: false, paths: false },
    };
  }

  if (meta.format === 'unknown') {
    return {
      format: 'unknown',
      parseError: null,
      classes: [],
      properties: [],
      paths: [],
      truncated: { classes: false, properties: false, paths: false },
    };
  }

  let body: Omit<RepositoryFileDetailTables, 'format' | 'parseError'>;
  if (meta.format === 'graphql' && graphqlSdl) {
    body = graphqlDetail(graphqlSdl);
  } else if (doc) {
    switch (meta.format) {
      case 'openapi':
        body = openApiFamilyDetail(doc);
        break;
      case 'swagger2':
        body = swagger2Detail(doc);
        break;
      case 'asyncapi':
        body = asyncApiDetail(doc);
        break;
      case 'arazzo':
        body = arazzoDetail(doc);
        break;
      case 'json_schema':
        body = jsonSchemaDetail(doc);
        break;
      default:
        body = {
          classes: [],
          properties: [],
          paths: [],
          truncated: { classes: false, properties: false, paths: false },
        };
    }
  } else {
    body = {
      classes: [],
      properties: [],
      paths: [],
      truncated: { classes: false, properties: false, paths: false },
    };
  }

  return {
    format: meta.format,
    parseError: null,
    ...body,
  };
}
