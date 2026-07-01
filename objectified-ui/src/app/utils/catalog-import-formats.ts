/**
 * Catalog store-raw import: detected format → REST adapter `source_kind` (MFI-23.7).
 *
 * The catalog importer stores a non-OpenAPI source **verbatim** (no conversion) by running it
 * through the REST spec-import adapter pipeline, which persists a catalog item and keeps the raw
 * bytes for later conversion. That pipeline resolves the request's `source_kind` against the
 * server-side import-source registry, so a source is storable only when a **registered adapter**
 * can parse it. Today those adapters are gRPC/Protobuf, GraphQL and AsyncAPI (OpenAPI/Swagger are
 * native and go to Projects, not the catalog).
 *
 * This maps the client analyzer's detected `format` token (see `openapi-analyzer.ts`) to the
 * adapter registry key the REST job needs, or `null` when no adapter can store the format yet —
 * so the UI can clearly say "recognized, but not importable to the catalog yet" instead of failing
 * an import mid-flight.
 */

/** An adapter-backed catalog source: the detected format, the REST `source_kind`, and a label. */
export interface CatalogAdapterSource {
  /** REST import-source registry key the spec-import job runs under. */
  sourceKind: string;
  /** Human label for the source. */
  label: string;
}

export type CatalogImportDestination =
  | 'catalog'
  | 'project'
  | 'json-schema-choice'
  | 'not-importable';

export interface CatalogImportRoutingDecision {
  destination: CatalogImportDestination;
  label: string;
  description: string;
  adapter: CatalogAdapterSource | null;
}

const PROJECT_FORMATS = new Set([
  'openapi',
  'openapi-3.0',
  'openapi-3.1',
  'swagger',
  'swagger-2.0',
  'arazzo',
]);

const JSON_SCHEMA_FORMATS = new Set([
  'jsonschema',
  'json-schema',
  'json-schema-2020-12',
  'json schema',
]);

/**
 * Detected-format token → adapter source. Keys are the `AnalysisResult.format` values the client
 * analyzer emits; a Protobuf document (`.proto`) routes to the gRPC adapter (its registry key is
 * `grpc`, and it emits the `protobuf` format).
 */
const FORMAT_TO_ADAPTER: Readonly<Record<string, CatalogAdapterSource>> = {
  protobuf: { sourceKind: 'grpc', label: 'gRPC / Protobuf' },
  grpc: { sourceKind: 'grpc', label: 'gRPC / Protobuf' },
  graphql: { sourceKind: 'graphql', label: 'GraphQL' },
  asyncapi: { sourceKind: 'asyncapi', label: 'AsyncAPI' },
};

/**
 * Resolve the adapter source for a detected format, or `null` when no registered adapter can store
 * it in the catalog yet.
 *
 * @param format The `AnalysisResult.format` token (e.g. `protobuf`, `graphql`, `asyncapi`).
 * @returns The adapter source, or `null` for unknown / native / not-yet-adapter-backed formats.
 */
export function catalogAdapterForFormat(
  format: string | null | undefined,
): CatalogAdapterSource | null {
  if (!format) return null;
  return FORMAT_TO_ADAPTER[format.trim().toLowerCase()] ?? null;
}

export function decideCatalogImportRouting(
  format: string | null | undefined,
): CatalogImportRoutingDecision {
  const key = (format ?? '').trim().toLowerCase();
  const adapter = catalogAdapterForFormat(key);

  if (adapter) {
    return {
      destination: 'catalog',
      label: 'Catalog',
      description: `${adapter.label} imports are stored in the catalog and converted only when explicitly requested.`,
      adapter,
    };
  }

  if (PROJECT_FORMATS.has(key)) {
    return {
      destination: 'project',
      label: 'Projects',
      description: 'OpenAPI, Swagger, and Arazzo create publishable Project versions instead of catalog items.',
      adapter: null,
    };
  }

  if (JSON_SCHEMA_FORMATS.has(key)) {
    return {
      destination: 'json-schema-choice',
      label: 'Choose destination',
      description: 'JSON Schema can be stored in the catalog for later conversion or imported as current Types/Projects schema.',
      adapter: null,
    };
  }

  return {
    destination: 'not-importable',
    label: 'Not importable yet',
    description: 'This format is recognized but does not have a catalog importer yet.',
    adapter: null,
  };
}

/** Whether a detected format can be stored (unconverted) in the catalog today. */
export function isCatalogStorableFormat(format: string | null | undefined): boolean {
  return catalogAdapterForFormat(format) !== null;
}

/** The distinct adapter-backed catalog sources, for messaging ("Supported: gRPC, GraphQL, AsyncAPI"). */
export const CATALOG_STORABLE_SOURCES: readonly CatalogAdapterSource[] = Array.from(
  new Map(Object.values(FORMAT_TO_ADAPTER).map((s) => [s.sourceKind, s])).values(),
);
