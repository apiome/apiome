/**
 * OA4 (#3501) — Import OpenAPI 3.2.0 `additionalOperations` and the HTTP QUERY method.
 *
 * Covers the shared Path Item walk, path extraction (schemas under QUERY and custom
 * methods, original method tokens), the stored operation metadata, and the export
 * round-trip of non-fixed methods through the OA2 extensions.
 */

/** OpenAPI documents are walked untyped, like the other OpenAPI import utilities. */
/* eslint-disable @typescript-eslint/no-explicit-any */

import fs from 'fs';
import path from 'path';
import YAML from 'yaml';
import { extractPaths, parseOpenAPISpec } from '../src/app/utils/openapi-import';
import { convertOpenAPI32ToOpenAPI31 } from '../src/app/utils/openapi32-converter';
import { analyzeSpecification } from '../src/app/utils/openapi-analyzer';
import { listPathItemOperations } from '../src/app/utils/openapi-path-operations';
import { buildPathItemForOpenAPI, generatePathsForOpenAPI, type PathInfo } from '../lib/utils/openapi-paths-generator';

jest.mock('../lib/db/db', () => ({}));
import { buildPathOperationMetadata } from '../lib/db/import-openapi-paths-security';

const FIXTURE = path.join(__dirname, 'fixtures/openapi32-operations/query-and-additional.yaml');

/** Read the fixture as text. */
function fixture(): string {
  return fs.readFileSync(FIXTURE, 'utf-8');
}

/** Read the fixture as a parsed document. */
function fixtureDoc(): any {
  return YAML.parse(fixture());
}

describe('listPathItemOperations', () => {
  it('walks the fixed verbs, then query, then additionalOperations', () => {
    const { operations, duplicates } = listPathItemOperations(fixtureDoc().paths['/search']);
    expect(operations.map((o) => [o.key, o.method, o.source])).toEqual([
      ['get', 'GET', 'fixed'],
      ['query', 'QUERY', 'query'],
      ['REPORT', 'REPORT', 'additionalOperations'],
      ['Purge', 'Purge', 'additionalOperations'],
    ]);
    expect(operations.map((o) => o.normalizedMethod)).toEqual(['GET', 'QUERY', 'REPORT', 'PURGE']);
    expect(duplicates).toEqual([]);
  });

  it('reads the OA2 stashes', () => {
    const normalized = convertOpenAPI32ToOpenAPI31(fixtureDoc()).document;
    const { operations } = listPathItemOperations(normalized.paths['/search']);
    expect(operations.map((o) => o.method)).toEqual(['GET', 'QUERY', 'REPORT', 'Purge']);
  });

  it('lists a method declared twice once and reports the duplicate', () => {
    const { operations, duplicates } = listPathItemOperations({
      get: { responses: {} },
      query: { responses: {} },
      additionalOperations: { GET: { responses: {} }, query: { responses: {} }, LINK: { responses: {} } },
    });
    expect(operations.map((o) => o.method)).toEqual(['GET', 'QUERY', 'LINK']);
    expect(duplicates).toEqual(['GET', 'query']);
  });

  it('ignores non-object operations and blank method keys', () => {
    const { operations } = listPathItemOperations({
      get: null,
      query: 'nope',
      additionalOperations: { ' ': { responses: {} }, REPORT: [] },
      summary: 'not an operation',
    });
    expect(operations).toEqual([]);
    expect(listPathItemOperations(null).operations).toEqual([]);
  });
});

describe('extractPaths — QUERY and additionalOperations', () => {
  it('walks every operation and keeps the original method token', () => {
    const [search] = extractPaths(fixtureDoc());
    expect(search.operations.map((o) => [o.method, o.httpMethod, o.methodSource])).toEqual([
      ['GET', undefined, undefined],
      ['QUERY', 'QUERY', 'query'],
      ['REPORT', 'REPORT', 'additionalOperations'],
      ['PURGE', 'Purge', 'additionalOperations'],
    ]);
  });

  it('extracts the request and response schemas of a QUERY operation', () => {
    const query = extractPaths(fixtureDoc())[0].operations.find((o) => o.method === 'QUERY');
    expect(query?.operationId).toBe('runSearch');
    expect(query?.requestBody).toEqual({
      required: true,
      description: undefined,
      content: { 'application/json': { $ref: '#/components/schemas/SearchFilter' } },
    });
    expect(query?.responses['200'].content?.['application/json']).toEqual({ $ref: '#/components/schemas/SearchResult' });
  });

  it('extracts the schemas and fields of a custom additionalOperations method', () => {
    const report = extractPaths(fixtureDoc())[0].operations.find((o) => o.method === 'REPORT');
    expect(report).toMatchObject({ operationId: 'reportSearches', summary: 'WebDAV-style report', deprecated: true });
    expect(report?.responses['207'].content?.['application/xml']).toEqual({ $ref: '#/components/schemas/SearchReport' });
  });

  it('gives the same result for a raw 3.2 document and its OA2 normalization', () => {
    const raw = fixtureDoc();
    expect(extractPaths(convertOpenAPI32ToOpenAPI31(raw).document)).toEqual(extractPaths(raw));
  });

  it('records duplicate methods on the parsed path', () => {
    const doc = fixtureDoc();
    doc.paths['/search'].additionalOperations.GET = { responses: { '200': { description: 'dup' } } };
    expect(extractPaths(doc)[0].duplicateMethods).toEqual(['GET']);
    expect(extractPaths(fixtureDoc())[0].duplicateMethods).toBeUndefined();
  });
});

describe('parseOpenAPISpec — QUERY and additionalOperations', () => {
  it('imports the schemas referenced under QUERY and REPORT as classes', () => {
    const result = parseOpenAPISpec(fixture());
    expect(result.success).toBe(true);
    const names = result.classes.filter((c) => c.isSupported).map((c) => c.name);
    expect(names).toEqual(expect.arrayContaining(['SearchFilter', 'SearchResult', 'SearchReport']));
    expect(result.paths?.[0].operations.map((o) => o.method)).toEqual(['GET', 'QUERY', 'REPORT', 'PURGE']);
  });

  it('warns about a method declared more than once', () => {
    const doc = fixtureDoc();
    doc.paths['/search'].additionalOperations.GET = { responses: { '200': { description: 'dup' } } };
    const result = parseOpenAPISpec(JSON.stringify(doc));
    expect(result.warnings).toContain(
      '/search: method GET declared more than once; only the first declaration was imported.'
    );
  });

  it('reports the 3.2 operations as imported, not as unsupported', async () => {
    const analysis = await analyzeSpecification(fixture(), 'search.yaml');
    const query = analysis.unsupportedFeatures.find((f) => f.id === 'openapi32-query-method');
    const additional = analysis.unsupportedFeatures.find((f) => f.id === 'openapi32-additional-operations');
    expect(query).toMatchObject({ severity: 'info', count: 1 });
    expect(query?.description).toContain('imported as a QUERY path operation');
    expect(additional).toMatchObject({ severity: 'info', count: 2 });
    expect(additional?.description).toContain('keeps its method token');
  });
});

describe('buildPathOperationMetadata', () => {
  it('stores the method token and source for a 3.2 operation', () => {
    expect(buildPathOperationMetadata({ httpMethod: 'Purge', methodSource: 'additionalOperations' })).toEqual({
      httpMethod: 'Purge',
      methodSource: 'additionalOperations',
    });
    expect(buildPathOperationMetadata({ deprecated: true, httpMethod: 'QUERY', methodSource: 'query' })).toEqual({
      deprecated: true,
      httpMethod: 'QUERY',
      methodSource: 'query',
    });
  });

  it('keeps the previous shape for a fixed verb', () => {
    expect(buildPathOperationMetadata({ deprecated: true })).toEqual({ deprecated: true });
    expect(buildPathOperationMetadata({})).toBeNull();
  });
});

describe('export — non-fixed methods on a 3.1 path item', () => {
  const pathInfo: PathInfo = {
    id: 'p1',
    pathname: '/search',
    operations: [
      { id: 'o1', operation: 'GET', parameters: [], responses: [] },
      { id: 'o2', operation: 'QUERY', httpMethod: 'QUERY', parameters: [], responses: [] },
      { id: 'o3', operation: 'REPORT', parameters: [], responses: [] },
      { id: 'o4', operation: 'PURGE', httpMethod: 'Purge', parameters: [], responses: [] },
    ],
  };

  it('writes QUERY and custom methods to the OA2 extensions, never as bare keys', () => {
    const item = buildPathItemForOpenAPI(pathInfo);
    expect(Object.keys(item).sort()).toEqual(['get', 'x-apiome-additional-operations', 'x-apiome-query-operation']);
    expect(Object.keys(item['x-apiome-additional-operations'] as object)).toEqual(['REPORT', 'Purge']);
  });

  it('round-trips through extractPaths with the method tokens intact', () => {
    const [search] = extractPaths({ paths: generatePathsForOpenAPI([pathInfo]) });
    expect(search.operations.map((o) => [o.method, o.httpMethod])).toEqual([
      ['GET', undefined],
      ['QUERY', 'QUERY'],
      ['REPORT', 'REPORT'],
      ['PURGE', 'Purge'],
    ]);
  });
});
