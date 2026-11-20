/**
 * COA-2.5 (#7048) — OpenAPI 3.2 constructs in Projects.
 *
 * A 3.2 project holds QUERY and custom-method operations, a tag hierarchy, streaming media types
 * (`itemSchema`) and `in: querystring` parameters. These tests cover:
 *  - the round trip: a 3.2 document imports into the stored shape (as the importer writes it) and
 *    generates back with every construct, natively, and re-imports to the same parsed paths;
 *  - the 3.1 target: no 3.2 field is written (stashes for operations and element schemas,
 *    querystring parameters left out, tags without summary / parent / kind);
 *  - the helpers in `lib/utils/openapi-32-authoring.ts`;
 *  - the spec viewer's summary (`summarizeOpenapi32Constructs`), which is null for 3.1.
 */

/** OpenAPI documents are walked untyped, like the other OpenAPI import utilities. */
/* eslint-disable @typescript-eslint/no-explicit-any */

import fs from 'fs';
import path from 'path';
import YAML from 'yaml';

import { extractPaths, parseOpenAPISpec, type ParsedMediaTypeContent, type ParsedPath } from '../src/app/utils/openapi-import';
import {
  generatePathsForOpenAPI,
  methodTakesRequestBody,
  type ContentTypeInfo,
  type PathInfo,
  type PathParameterLocation,
} from '../lib/utils/openapi-paths-generator';
import {
  applyItemSchemaKeys,
  buildDocumentTags,
  isOpenApi32,
  itemSchemaKey,
  metadataWithoutTags,
  readStoredTags,
} from '../lib/utils/openapi-32-authoring';
import { TAG_TAXONOMY_METADATA_KEY, buildTagTaxonomy, toStoredTagTaxonomy } from '../src/app/utils/openapi-tag-taxonomy';
import { summarizeOpenapi32Constructs, specOpenapiVersion } from '../src/app/components/ade/versions/openapi32Constructs';

jest.mock('../lib/db/db', () => ({}));
import { buildParameterData, buildPathOperationMetadata } from '../lib/db/import-openapi-paths-security';

const FIXTURE = path.join(__dirname, 'fixtures/openapi32-project/constructs.yaml');

/** The fixture as a parsed document. */
function fixtureDoc(): any {
  return YAML.parse(fs.readFileSync(FIXTURE, 'utf-8'));
}

/** The class a parsed media type refers to. */
function className(content: ParsedMediaTypeContent): string | null {
  const match = content.$ref?.match(/#\/components\/schemas\/(.+)/);
  return match ? match[1] : null;
}

/** A parsed content map as the stored content rows (class references only, as in the fixture). */
function toContentTypes(content: Record<string, ParsedMediaTypeContent> | undefined): ContentTypeInfo[] {
  return Object.entries(content ?? {}).map(([mediaType, entry], index) => ({
    id: `ct-${index}`,
    media_type: mediaType,
    class_id: className(entry) ? `class-${className(entry)}` : null,
    class_name: className(entry),
    item_schema: Boolean(entry.streamKind),
  }));
}

/**
 * The parsed paths as the importer stores them (`importOpenAPIPathsAndSecurity`) and the export
 * loader reads them back (`loadPathsForOpenAPIExport`).
 */
function toStoredPaths(paths: ParsedPath[]): PathInfo[] {
  return paths.map((p, pathIndex) => ({
    id: `path-${pathIndex}`,
    pathname: p.path,
    operations: p.operations.map((op, opIndex) => {
      const metadata = buildPathOperationMetadata(op);
      return {
        id: `op-${pathIndex}-${opIndex}`,
        operation: op.method,
        ...(typeof metadata?.httpMethod === 'string' ? { httpMethod: metadata.httpMethod } : {}),
        description: { id: `d-${opIndex}`, operationId: op.operationId, tags: op.tags },
        parameters: op.parameters.map((param, i) => ({
          id: `param-${i}`,
          name: param.name,
          in_location: param.in as PathParameterLocation,
          description: param.description,
          data: buildParameterData(param),
        })),
        requestBody: op.requestBody
          ? {
              id: `rb-${opIndex}`,
              name: op.operationId ?? 'body',
              required: op.requestBody.required === true,
              content_types: toContentTypes(op.requestBody.content),
            }
          : null,
        responses: Object.entries(op.responses).map(([status, res], i) => ({
          id: `res-${i}`,
          status_code: status,
          description: res.description,
          content_types: toContentTypes(res.content),
        })),
      };
    }),
  }));
}

/** Generate the fixture's paths for a target version, through the stored shape. */
function generate(openapiVersion?: string): Record<string, any> {
  return generatePathsForOpenAPI(toStoredPaths(extractPaths(fixtureDoc())), { openapiVersion }) as Record<string, any>;
}

describe('a 3.2 project round-trips with each construct', () => {
  const item = generate('3.2.0')['/orders'];

  it('writes QUERY as `query` and the custom method under `additionalOperations`', () => {
    expect(Object.keys(item).sort()).toEqual(['additionalOperations', 'get', 'query']);
    expect(item.query.operationId).toBe('searchOrders');
    expect(Object.keys(item.additionalOperations)).toEqual(['REPORT']);
    expect(item['x-apiome-query-operation']).toBeUndefined();
  });

  it('keeps the request bodies of QUERY and the custom method', () => {
    expect(item.query.requestBody.content['application/json'].schema).toEqual({ $ref: '#/components/schemas/OrderQuery' });
    expect(item.additionalOperations.REPORT.requestBody.content['application/jsonl']).toEqual({
      itemSchema: { $ref: '#/components/schemas/OrderQuery' },
    });
  });

  it('writes streaming media types with `itemSchema`', () => {
    expect(item.get.responses['200'].content['application/jsonl']).toEqual({ itemSchema: { $ref: '#/components/schemas/Order' } });
    expect(item.additionalOperations.REPORT.responses['200'].content['text/event-stream']).toEqual({
      itemSchema: { $ref: '#/components/schemas/Order' },
    });
    expect(item.query.responses['200'].content['application/json']).toEqual({ schema: { $ref: '#/components/schemas/Order' } });
  });

  it('writes the querystring parameter with its content', () => {
    expect(item.get.parameters).toEqual([
      {
        name: 'filter',
        in: 'querystring',
        description: 'The whole query string, as one form-encoded object',
        content: {
          'application/x-www-form-urlencoded': {
            schema: { type: 'object', properties: { status: { type: 'string' } } },
          },
        },
      },
    ]);
  });

  it('imports the generated document back to the same paths', () => {
    const doc = { ...fixtureDoc(), paths: generate('3.2.0') };
    expect(extractPaths(doc)).toEqual(extractPaths(fixtureDoc()));
  });

  it('writes the tag hierarchy', () => {
    const stored = toStoredTagTaxonomy(buildTagTaxonomy(fixtureDoc()));
    const tags = buildDocumentTags(readStoredTags({ [TAG_TAXONOMY_METADATA_KEY]: stored }), true);
    expect(tags).toEqual(fixtureDoc().tags);
  });
});

describe('a 3.1 target has none of the 3.2 fields', () => {
  it.each([undefined, '3.1.0'])('stashes operations and element schemas, and leaves out querystring (%s)', (version) => {
    const item = generate(version)['/orders'];
    expect(Object.keys(item).sort()).toEqual(['get', 'x-apiome-additional-operations', 'x-apiome-query-operation']);
    expect(item.get.parameters).toBeUndefined();
    expect(item.get.responses['200'].content['application/jsonl']).toEqual({
      'x-apiome-item-schema': { $ref: '#/components/schemas/Order' },
    });
    expect(JSON.stringify(item)).not.toMatch(/"itemSchema"|"querystring"|"additionalOperations"/);
  });

  it('imports the stashes back to the same paths, without the querystring parameter', () => {
    const roundTripped = extractPaths({ ...fixtureDoc(), openapi: '3.1.0', paths: generate('3.1.0') });
    const original = extractPaths(fixtureDoc());
    expect(roundTripped[0].operations.map((op) => [op.method, op.httpMethod])).toEqual(
      original[0].operations.map((op) => [op.method, op.httpMethod])
    );
    expect(roundTripped[0].operations[0].parameters).toEqual([]);
  });

  it('writes tags without summary, parent or kind', () => {
    const stored = toStoredTagTaxonomy(buildTagTaxonomy(fixtureDoc()));
    expect(buildDocumentTags(readStoredTags({ [TAG_TAXONOMY_METADATA_KEY]: stored }), false)).toEqual([
      { name: 'orders', description: 'Everything about orders' },
      { name: 'order-search' },
      { name: 'beta' },
    ]);
  });
});

describe('importing 3.2 parameters and streams', () => {
  it('keeps a querystring parameter’s media type and schema', () => {
    const [op] = extractPaths(fixtureDoc())[0].operations;
    expect(op.parameters[0]).toMatchObject({
      name: 'filter',
      in: 'querystring',
      contentMediaType: 'application/x-www-form-urlencoded',
      schema: { type: 'object' },
    });
    expect(buildParameterData(op.parameters[0])).toEqual({
      type: 'object',
      properties: { status: { type: 'string' } },
      contentMediaType: 'application/x-www-form-urlencoded',
    });
  });

  it('does not take content from a parameter that has a schema', () => {
    const [p] = extractPaths({
      openapi: '3.2.0',
      paths: { '/a': { get: { parameters: [{ name: 'x', in: 'query', schema: { type: 'integer' }, content: { 'text/plain': {} } }], responses: {} } } },
    })[0].operations[0].parameters;
    expect(p.contentMediaType).toBeUndefined();
    expect(p.schema).toEqual({ type: 'integer' });
  });

  it('parses the whole fixture', () => {
    const result = parseOpenAPISpec(fs.readFileSync(FIXTURE, 'utf-8'));
    expect(result.success).toBe(true);
    expect(result.tags?.map((t) => t.name)).toEqual(['orders', 'order-search', 'beta']);
  });
});

describe('openapi-32-authoring helpers', () => {
  it.each([
    ['3.2.0', true],
    ['3.2', true],
    [' 3.2.1 ', true],
    ['3.1.0', false],
    ['3.20.0', false],
    [undefined, false],
    [null, false],
  ])('isOpenApi32(%p) is %p', (version, expected) => {
    expect(isOpenApi32(version as string | undefined)).toBe(expected);
  });

  it('names the element-schema key for each target', () => {
    expect(itemSchemaKey(true)).toBe('itemSchema');
    expect(itemSchemaKey(false)).toBe('x-apiome-item-schema');
  });

  it('moves only flagged, built schemas', () => {
    const content: Record<string, any> = {
      'application/jsonl': { schema: { type: 'string' }, example: 'a' },
      'application/json': { schema: { type: 'object' } },
      'text/event-stream': { example: 'no schema' },
    };
    applyItemSchemaKeys(
      content,
      [
        { media_type: 'application/jsonl', item_schema: true },
        { media_type: 'application/json', item_schema: false },
        { media_type: 'text/event-stream', item_schema: true },
        { media_type: 'missing/type', item_schema: true },
      ],
      true
    );
    expect(content).toEqual({
      'application/jsonl': { itemSchema: { type: 'string' }, example: 'a' },
      'application/json': { schema: { type: 'object' } },
      'text/event-stream': { example: 'no schema' },
    });
  });

  it('never writes a parent that names a missing tag or the tag itself', () => {
    expect(buildDocumentTags([{ name: 'a', parent: 'ghost' }, { name: 'b', parent: 'b' }], true)).toEqual([{ name: 'a' }, { name: 'b' }]);
  });

  it('reads only well-formed stored tags', () => {
    expect(readStoredTags(undefined)).toEqual([]);
    expect(readStoredTags({ [TAG_TAXONOMY_METADATA_KEY]: 'x' })).toEqual([]);
    expect(readStoredTags({ [TAG_TAXONOMY_METADATA_KEY]: { tags: [{ name: 'a' }, { name: ' ' }, null, { summary: 'x' }] } })).toEqual([{ name: 'a' }]);
  });

  it('keeps the tag list out of x-metadata', () => {
    expect(metadataWithoutTags({ summary: 'S', [TAG_TAXONOMY_METADATA_KEY]: {} })).toEqual({ summary: 'S' });
    expect(metadataWithoutTags({ [TAG_TAXONOMY_METADATA_KEY]: {} })).toBeUndefined();
    const plain = { summary: 'S' };
    expect(metadataWithoutTags(plain)).toBe(plain);
    expect(metadataWithoutTags(undefined)).toBeUndefined();
  });

  it.each([
    ['POST', true],
    ['patch', true],
    ['QUERY', true],
    ['REPORT', true],
    ['GET', false],
    ['DELETE', false],
    ['options', false],
  ])('methodTakesRequestBody(%s) is %p', (method, expected) => {
    expect(methodTakesRequestBody(method)).toBe(expected);
  });
});

describe('summarizeOpenapi32Constructs', () => {
  /** The fixture as the spec viewer receives it: generated JSON text. */
  function spec32(): string {
    const stored = toStoredTagTaxonomy(buildTagTaxonomy(fixtureDoc()));
    return JSON.stringify({
      openapi: '3.2.0',
      info: { title: 'Orders', version: '1' },
      tags: buildDocumentTags(readStoredTags({ [TAG_TAXONOMY_METADATA_KEY]: stored }), true),
      paths: generate('3.2.0'),
    });
  }

  it('lists every construct of a 3.2 document', () => {
    const summary = summarizeOpenapi32Constructs(spec32())!;
    expect(summary.openapi).toBe('3.2.0');
    expect(summary.operations).toEqual([
      { path: '/orders', method: 'QUERY', source: 'query', operationId: 'searchOrders' },
      { path: '/orders', method: 'REPORT', source: 'additionalOperations', operationId: 'reportOrders' },
    ]);
    expect(summary.tags.map((t) => [t.name, t.parent ?? null, t.kind ?? null])).toEqual([
      ['orders', null, 'nav'],
      ['order-search', 'orders', 'nav'],
      ['beta', null, 'badge'],
    ]);
    expect(summary.streams.map((s) => [s.mediaType, s.kindLabel, s.hasItemSchema])).toEqual([
      ['application/jsonl', 'JSON Lines', true],
      ['application/jsonl', 'JSON Lines', true],
      ['text/event-stream', 'Server-Sent Events', true],
    ]);
    expect(summary.querystring).toEqual([
      { path: '/orders', method: 'GET', name: 'filter', mediaType: 'application/x-www-form-urlencoded' },
    ]);
  });

  it('is null for a 3.1 document, even one carrying the stashes', () => {
    const spec31 = JSON.stringify({ openapi: '3.1.0', info: {}, paths: generate('3.1.0') });
    expect(summarizeOpenapi32Constructs(spec31)).toBeNull();
  });

  it('is null for a 3.2 document that uses none of them, and for unreadable text', () => {
    expect(summarizeOpenapi32Constructs(JSON.stringify({ openapi: '3.2.0', paths: { '/a': { get: { responses: {} } } } }))).toBeNull();
    expect(summarizeOpenapi32Constructs('')).toBeNull();
    expect(summarizeOpenapi32Constructs('{not json')).toBeNull();
    expect(summarizeOpenapi32Constructs('[]')).toBeNull();
  });

  it('reads the declared version', () => {
    expect(specOpenapiVersion(spec32())).toBe('3.2.0');
    expect(specOpenapiVersion('{}')).toBeNull();
    expect(specOpenapiVersion('nope')).toBeNull();
  });
});
