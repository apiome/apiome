/**
 * Unit tests for the catalog store-raw format→adapter mapping (MFI-23.7).
 */
import { describe, test, expect } from '@jest/globals';
import {
  catalogAdapterForFormat,
  decideCatalogImportRouting,
  isCatalogStorableFormat,
  CATALOG_STORABLE_SOURCES,
} from '../src/app/utils/catalog-import-formats';

describe('catalog-import-formats', () => {
  test('maps adapter-backed detected formats to their REST source_kind', () => {
    expect(catalogAdapterForFormat('protobuf')?.sourceKind).toBe('grpc');
    expect(catalogAdapterForFormat('grpc')?.sourceKind).toBe('grpc');
    expect(catalogAdapterForFormat('graphql')?.sourceKind).toBe('graphql');
    expect(catalogAdapterForFormat('asyncapi')?.sourceKind).toBe('asyncapi');
  });

  test('is case/space-insensitive', () => {
    expect(catalogAdapterForFormat(' Protobuf ')?.sourceKind).toBe('grpc');
    expect(catalogAdapterForFormat('GraphQL')?.sourceKind).toBe('graphql');
  });

  test('returns null for formats with no catalog importer (Thrift/Avro/RAML/…)', () => {
    for (const f of ['thrift', 'avro', 'raml', 'postman', 'jsonschema', 'arazzo', 'openapi', 'swagger', 'unknown', '', null, undefined]) {
      expect(catalogAdapterForFormat(f)).toBeNull();
      expect(isCatalogStorableFormat(f)).toBe(false);
    }
  });

  test('exposes the distinct storable sources (deduped by source_kind)', () => {
    const kinds = CATALOG_STORABLE_SOURCES.map((s) => s.sourceKind).sort();
    expect(kinds).toEqual(['asyncapi', 'graphql', 'grpc']);
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
});
