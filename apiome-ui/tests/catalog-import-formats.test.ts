/**
 * Unit tests for the catalog store-raw format→adapter mapping (MFI-23.7).
 */
import { describe, test, expect } from '@jest/globals';
import {
  catalogAdapterForFormat,
  decideCatalogImportRouting,
  paradigmForFormat,
  formatFamily,
  isCatalogStorableFormat,
  CATALOG_STORABLE_SOURCES,
} from '../src/app/utils/catalog-import-formats';

describe('catalog-import-formats', () => {
  test('maps adapter-backed detected formats to their REST source_kind', () => {
    expect(catalogAdapterForFormat('protobuf')?.sourceKind).toBe('grpc');
    expect(catalogAdapterForFormat('grpc')?.sourceKind).toBe('grpc');
    expect(catalogAdapterForFormat('graphql')?.sourceKind).toBe('graphql');
    expect(catalogAdapterForFormat('asyncapi')?.sourceKind).toBe('asyncapi');
    expect(catalogAdapterForFormat('thrift')?.sourceKind).toBe('thrift');
    expect(catalogAdapterForFormat('connectrpc')?.sourceKind).toBe('connectrpc');
    expect(catalogAdapterForFormat('connect')?.sourceKind).toBe('connectrpc');
  });

  test('is case/space-insensitive', () => {
    expect(catalogAdapterForFormat(' Protobuf ')?.sourceKind).toBe('grpc');
    expect(catalogAdapterForFormat('GraphQL')?.sourceKind).toBe('graphql');
  });

  test('returns null for formats with no catalog importer (Avro/RAML/…)', () => {
    for (const f of ['avro', 'raml', 'postman', 'jsonschema', 'arazzo', 'openapi', 'swagger', 'unknown', '', null, undefined]) {
      expect(catalogAdapterForFormat(f)).toBeNull();
      expect(isCatalogStorableFormat(f)).toBe(false);
    }
  });

  test('exposes the distinct storable sources (deduped by source_kind)', () => {
    const kinds = CATALOG_STORABLE_SOURCES.map((s) => s.sourceKind).sort();
    expect(kinds).toEqual(['asyncapi', 'connectrpc', 'graphql', 'grpc', 'thrift']);
  });

  test('routes adapter-backed formats to catalog', () => {
    expect(decideCatalogImportRouting('graphql')).toMatchObject({
      destination: 'catalog',
      label: 'Catalog',
      adapter: { sourceKind: 'graphql' },
    });
    expect(decideCatalogImportRouting('protobuf')).toMatchObject({
      destination: 'catalog',
      adapter: { sourceKind: 'grpc' },
    });
  });

  test('routes OpenAPI, Swagger, and Arazzo to Projects', () => {
    for (const f of ['openapi', 'openapi-3.1', 'swagger', 'swagger-2.0', 'arazzo']) {
      expect(decideCatalogImportRouting(f)).toMatchObject({
        destination: 'project',
        label: 'Projects',
        adapter: null,
      });
    }
  });

  test('routes JSON Schema to the destination choice', () => {
    for (const f of ['jsonschema', 'json-schema', 'json-schema-2020-12', 'JSON Schema']) {
      expect(decideCatalogImportRouting(f)).toMatchObject({
        destination: 'json-schema-choice',
        label: 'Choose destination',
        adapter: null,
      });
    }
  });

  test('routes unsupported formats to not-importable', () => {
    expect(decideCatalogImportRouting('raml')).toMatchObject({
      destination: 'not-importable',
      adapter: null,
    });
  });

  // --- MFI-26.3: versioned detector tokens + paradigm mapping ---

  test('folds versioned detector tokens to their format family', () => {
    expect(formatFamily('asyncapi-2')).toBe('asyncapi');
    expect(formatFamily('asyncapi-3')).toBe('asyncapi');
    expect(formatFamily('openapi-3.1')).toBe('openapi');
    expect(formatFamily('swagger-2.0')).toBe('swagger');
    expect(formatFamily('json-schema-2020-12')).toBe('json-schema');
    // Non-version tails (a hyphenated family name) are preserved.
    expect(formatFamily('api-blueprint')).toBe('api-blueprint');
    expect(formatFamily(' GraphQL ')).toBe('graphql');
    expect(formatFamily(null)).toBe('');
  });

  test('resolves the AsyncAPI adapter from versioned detect tokens (asyncapi-2/3)', () => {
    expect(catalogAdapterForFormat('asyncapi-2')?.sourceKind).toBe('asyncapi');
    expect(catalogAdapterForFormat('asyncapi-3')?.sourceKind).toBe('asyncapi');
    expect(decideCatalogImportRouting('asyncapi-2')).toMatchObject({
      destination: 'catalog',
      adapter: { sourceKind: 'asyncapi' },
    });
  });

  test('maps detected formats to the paradigm the server routing_decision uses', () => {
    expect(paradigmForFormat('protobuf')).toBe('rpc');
    expect(paradigmForFormat('grpc')).toBe('rpc');
    expect(paradigmForFormat('graphql')).toBe('graph');
    expect(paradigmForFormat('asyncapi-2')).toBe('event');
    expect(paradigmForFormat('thrift')).toBe('rpc');
    expect(paradigmForFormat('connectrpc')).toBe('rpc');
    expect(paradigmForFormat('openapi-3.1')).toBe('rest');
    expect(paradigmForFormat('swagger-2.0')).toBe('rest');
    expect(paradigmForFormat('json-schema-2020-12')).toBe('dataschema');
  });

  test('returns null paradigm for unknown / unmapped formats', () => {
    for (const f of ['raml', 'unknown', '', null, undefined]) {
      expect(paradigmForFormat(f)).toBeNull();
    }
  });
});
