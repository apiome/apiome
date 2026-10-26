/**
 * OA3 (#3500) — Import OpenAPI 3.2.0 sequential & streaming media types.
 *
 * Covers JSON Lines, JSON text sequence and Server-Sent Events fixtures: the element
 * schema of `itemSchema` imports as a class, element classes carry
 * `x-apiome-stream-kind` provenance, paths link stream content to the element class,
 * and the analyzer lists the stream media types.
 */

/** OpenAPI documents are walked untyped, like the other OpenAPI import utilities. */
/* eslint-disable @typescript-eslint/no-explicit-any */

import fs from 'fs';
import path from 'path';
import YAML from 'yaml';
import { extractPaths, parseOpenAPISpec } from '../src/app/utils/openapi-import';
import { analyzeSpecification } from '../src/app/utils/openapi-analyzer';
import { convertOpenAPI32ToOpenAPI31 } from '../src/app/utils/openapi32-converter';
import { openApiImporter } from '../lib/importers/openapi';
import {
  applyStreamItemSchemas,
  collectStreamMediaTypes,
  getMediaTypeItemSchema,
  getStreamKind,
  STREAM_KIND_EXTENSION,
} from '../src/app/utils/openapi-stream-media-types';

const FIXTURES = path.join(__dirname, 'fixtures/openapi32-streams');

/** Read a stream fixture as text. */
function fixture(name: string): string {
  return fs.readFileSync(path.join(FIXTURES, name), 'utf-8');
}

/** Read a stream fixture as a parsed document. */
function fixtureDoc(name: string): any {
  return YAML.parse(fixture(name));
}

/** Find a parsed class by name. */
function classNamed(result: ReturnType<typeof parseOpenAPISpec>, name: string) {
  return result.classes.find((c) => c.name === name);
}

describe('getStreamKind', () => {
  it('recognizes the stream families, ignoring case and parameters', () => {
    expect(getStreamKind('application/jsonl')).toBe('jsonl');
    expect(getStreamKind('application/vnd.acme+jsonl')).toBe('jsonl');
    expect(getStreamKind('application/json-seq')).toBe('json-seq');
    expect(getStreamKind('application/geo+json-seq')).toBe('json-seq');
    expect(getStreamKind('Text/Event-Stream; charset=utf-8')).toBe('sse');
  });

  it('treats any other media type as a stream only when it has an itemSchema', () => {
    expect(getStreamKind('application/json')).toBeNull();
    expect(getStreamKind('application/problem+json')).toBeNull();
    expect(getStreamKind('application/problem+json', true)).toBe('sequential');
  });
});

describe('getMediaTypeItemSchema', () => {
  it('reads a raw itemSchema or the OA2 stash', () => {
    expect(getMediaTypeItemSchema({ itemSchema: { type: 'string' } })).toEqual({ type: 'string' });
    expect(getMediaTypeItemSchema({ 'x-apiome-item-schema': { type: 'integer' } })).toEqual({ type: 'integer' });
    expect(getMediaTypeItemSchema({ schema: { type: 'string' } })).toBeUndefined();
    expect(getMediaTypeItemSchema(null)).toBeUndefined();
  });
});

describe('applyStreamItemSchemas', () => {
  it('returns the same document when nothing declares an itemSchema', () => {
    const doc = { openapi: '3.1.0', paths: { '/a': { get: { responses: { '200': { content: { 'text/event-stream': { schema: { type: 'string' } } } } } } } } };
    expect(applyStreamItemSchemas(doc)).toBe(doc);
  });

  it('does not mutate its input and is idempotent', () => {
    const doc = fixtureDoc('jsonl.yaml');
    const before = JSON.stringify(doc);
    const once = applyStreamItemSchemas(doc);
    expect(JSON.stringify(doc)).toBe(before);
    expect(applyStreamItemSchemas(once)).toEqual(once);
  });

  it('hoists an object-shaped inline element schema under a generated name', () => {
    const out = applyStreamItemSchemas(fixtureDoc('jsonl.yaml'));
    const hoisted = out.components.schemas.ImportLogsRequestStreamItem;
    expect(hoisted).toMatchObject({ type: 'object', required: ['line'], [STREAM_KIND_EXTENSION]: 'jsonl' });
    expect(out.paths['/logs/import'].post.requestBody.content['application/jsonl'].itemSchema).toEqual({
      $ref: '#/components/schemas/ImportLogsRequestStreamItem',
    });
  });

  it('de-duplicates a generated name that collides with an existing schema', () => {
    const doc = fixtureDoc('jsonl.yaml');
    doc.components.schemas.ImportLogsRequestStreamItem = { type: 'object', properties: { taken: { type: 'string' } } };
    const out = applyStreamItemSchemas(doc);
    expect(out.components.schemas.ImportLogsRequestStreamItem.properties).toHaveProperty('taken');
    expect(out.components.schemas.ImportLogsRequestStreamItem2[STREAM_KIND_EXTENSION]).toBe('jsonl');
  });

  it('leaves a primitive inline element schema inline', () => {
    const doc = {
      openapi: '3.2.0',
      paths: { '/ticks': { get: { operationId: 'ticks', responses: { '200': { content: { 'text/event-stream': { itemSchema: { type: 'string' } } } } } } } },
    };
    const out = applyStreamItemSchemas(doc);
    expect(Object.keys(out.components.schemas)).toEqual([]);
    expect(out.paths['/ticks'].get.responses['200'].content['text/event-stream'].itemSchema).toEqual({ type: 'string' });
  });

  it('tags a class streamed as different families with the generic sequential kind', () => {
    const doc = fixtureDoc('jsonl.yaml');
    doc.paths['/logs'].get.responses['200'].content['text/event-stream'] = {
      itemSchema: { $ref: '#/components/schemas/LogEvent' },
    };
    const out = applyStreamItemSchemas(doc);
    expect(out.components.schemas.LogEvent[STREAM_KIND_EXTENSION]).toBe('sequential');
  });

  it('names an element without an operationId from its method and path', () => {
    const doc = {
      openapi: '3.2.0',
      paths: { '/feeds/{id}': { get: { responses: { '200': { content: { 'application/jsonl': { itemSchema: { type: 'object', properties: { a: { type: 'string' } } } } } } } } } },
    };
    expect(applyStreamItemSchemas(doc).components.schemas).toHaveProperty('GetFeedsIdStreamItem');
  });

  it('walks components.responses and reads the OA2 stash', () => {
    const doc = {
      openapi: '3.1.0',
      components: {
        schemas: { Tick: { type: 'object', properties: { n: { type: 'integer' } } } },
        responses: { TickStream: { description: 'ticks', content: { 'application/jsonl': { 'x-apiome-item-schema': { $ref: '#/components/schemas/Tick' } } } } },
      },
    };
    expect(applyStreamItemSchemas(doc).components.schemas.Tick[STREAM_KIND_EXTENSION]).toBe('jsonl');
  });
});

describe('collectStreamMediaTypes', () => {
  it('lists every stream media type with its kind and location', () => {
    expect(collectStreamMediaTypes(fixtureDoc('sse.yaml'))).toEqual([
      { location: 'paths./builds/{id}/progress.get.responses.200', mediaType: 'text/event-stream', kind: 'sse', hasItemSchema: true },
      { location: 'paths./builds/{id}/progress.get.responses.default', mediaType: 'application/problem+json', kind: 'sequential', hasItemSchema: true },
    ]);
  });

  it('lists a stream-family media type that has only a schema', () => {
    const doc = { openapi: '3.1.0', paths: { '/a': { get: { responses: { '200': { content: { 'application/jsonl': { schema: { type: 'string' } }, 'application/json': { schema: { type: 'string' } } } } } } } } };
    expect(collectStreamMediaTypes(doc)).toEqual([
      { location: 'paths./a.get.responses.200', mediaType: 'application/jsonl', kind: 'jsonl', hasItemSchema: false },
    ]);
  });

  it('includes the 3.2 query method and additionalOperations', () => {
    const content = { content: { 'application/jsonl': { itemSchema: { type: 'string' } } } };
    const doc = { openapi: '3.2.0', paths: { '/a': { query: { responses: { '200': content } }, additionalOperations: { WATCH: { responses: { '200': content } } } } } };
    expect(collectStreamMediaTypes(doc).map((o) => o.location)).toEqual([
      'paths./a.query.responses.200',
      'paths./a.WATCH.responses.200',
    ]);
  });
});

describe('parseOpenAPISpec — stream fixtures', () => {
  it('JSON Lines: imports the $ref and inline element schemas as tagged classes', () => {
    const result = parseOpenAPISpec(fixture('jsonl.yaml'));
    expect(result.success).toBe(true);

    const logEvent = classNamed(result, 'LogEvent');
    expect(logEvent?.isSupported).toBe(true);
    expect(logEvent?.schema[STREAM_KIND_EXTENSION]).toBe('jsonl');
    expect(logEvent?.properties.map((p) => p.name)).toEqual(['level', 'message', 'at']);

    const inline = classNamed(result, 'ImportLogsRequestStreamItem');
    expect(inline?.isSupported).toBe(true);
    expect(inline?.schema[STREAM_KIND_EXTENSION]).toBe('jsonl');
    expect(inline?.properties.map((p) => p.name)).toEqual(['line', 'source']);
  });

  it('JSON Lines: paths link the stream content to the element class', () => {
    const result = parseOpenAPISpec(fixture('jsonl.yaml'));
    const logs = result.paths?.find((p) => p.path === '/logs')?.operations[0];
    expect(logs?.responses['200'].content?.['application/jsonl']).toEqual({
      $ref: '#/components/schemas/LogEvent',
      streamKind: 'jsonl',
    });
    const importOp = result.paths?.find((p) => p.path === '/logs/import')?.operations[0];
    expect(importOp?.requestBody?.content['application/jsonl']).toEqual({
      $ref: '#/components/schemas/ImportLogsRequestStreamItem',
      streamKind: 'jsonl',
    });
  });

  it('json-seq: imports the element class tagged json-seq for both sequence media types', () => {
    const result = parseOpenAPISpec(fixture('json-seq.yaml'));
    expect(result.success).toBe(true);
    expect(classNamed(result, 'Feature')?.schema[STREAM_KIND_EXTENSION]).toBe('json-seq');
    const content = result.paths?.[0].operations[0].responses['200'].content;
    expect(content?.['application/json-seq']?.streamKind).toBe('json-seq');
    expect(content?.['application/geo+json-seq']?.streamKind).toBe('json-seq');
  });

  it('SSE: recognizes text/event-stream and imports the event element class', () => {
    const result = parseOpenAPISpec(fixture('sse.yaml'));
    expect(result.success).toBe(true);
    const progress = classNamed(result, 'ProgressEvent');
    expect(progress?.schema[STREAM_KIND_EXTENSION]).toBe('sse');
    expect(progress?.properties.map((p) => p.name)).toEqual(['event', 'data', 'id', 'retry']);
    expect(classNamed(result, 'Problem')?.schema[STREAM_KIND_EXTENSION]).toBe('sequential');
    const responses = result.paths?.[0].operations[0].responses;
    expect(responses?.['200'].content?.['text/event-stream']?.streamKind).toBe('sse');
  });

  it('a plain body schema is not tagged as a stream element', () => {
    const doc = fixtureDoc('sse.yaml');
    doc.openapi = '3.1.0';
    doc.paths['/builds/{id}/progress'].get.responses['200'].content = {
      'application/json': { schema: { $ref: '#/components/schemas/ProgressEvent' } },
    };
    delete doc.paths['/builds/{id}/progress'].get.responses.default;
    const result = parseOpenAPISpec(JSON.stringify(doc));
    expect(classNamed(result, 'ProgressEvent')?.schema[STREAM_KIND_EXTENSION]).toBeUndefined();
    expect(result.paths?.[0].operations[0].responses['200'].content?.['application/json']?.streamKind).toBeUndefined();
  });
});

describe('extractPaths — raw 3.2 and normalized documents agree', () => {
  it('produces the same content entries for a raw document and its OA2 normalization', () => {
    const raw = fixtureDoc('jsonl.yaml');
    const normalized = convertOpenAPI32ToOpenAPI31(raw).document;
    expect(extractPaths(normalized)).toEqual(extractPaths(raw));
  });
});

describe('openApiImporter.normalize — stream fixtures', () => {
  it('imports the hoisted inline element and carries the stream-kind tag on the class schema', () => {
    const { classes } = openApiImporter.normalize({ document: fixtureDoc('jsonl.yaml'), options: {} as any });
    const byKey = new Map(classes.map((c) => [c.originalSchemaKey, c]));
    expect(byKey.get('LogEvent')?.schema[STREAM_KIND_EXTENSION]).toBe('jsonl');
    expect(byKey.get('ImportLogsRequestStreamItem')?.properties?.map((p) => p.name)).toEqual(['line', 'source']);
  });

  it('honours a selection that names a hoisted element class', () => {
    const { classes } = openApiImporter.normalize({
      document: fixtureDoc('jsonl.yaml'),
      options: { selectedSchemas: ['ImportLogsRequestStreamItem'] } as any,
    });
    expect(classes.map((c) => c.originalSchemaKey)).toEqual(['ImportLogsRequestStreamItem']);
  });
});

describe('analyzeSpecification — stream feature report', () => {
  it.each([
    ['jsonl.yaml', 'application/jsonl (JSON Lines)', 2],
    ['json-seq.yaml', 'application/json-seq (JSON text sequence)', 2],
    ['sse.yaml', 'text/event-stream (Server-Sent Events)', 2],
  ])('%s lists its streaming media types', async (file, expected, count) => {
    const analysis = await analyzeSpecification(fixture(file), file);
    const feature = analysis.unsupportedFeatures.find((f) => f.id === 'sequential-media-types');
    expect(feature).toBeDefined();
    expect(feature?.description).toContain(expected);
    expect(feature?.count).toBe(count);
    expect(feature?.severity).toBe('info');
    // Superseded by the stream feature: not listed twice.
    expect(analysis.unsupportedFeatures.some((f) => f.id === 'openapi32-item-schema')).toBe(false);
  });

  it('notes stream media types that have no itemSchema', async () => {
    const doc = { openapi: '3.1.0', info: { title: 'T', version: '1' }, paths: { '/a': { get: { responses: { '200': { description: 'ok', content: { 'text/event-stream': { schema: { type: 'string' } } } } } } } } };
    const analysis = await analyzeSpecification(JSON.stringify(doc), 'a.json');
    const feature = analysis.unsupportedFeatures.find((f) => f.id === 'sequential-media-types');
    expect(feature?.description).toContain('1 without an itemSchema imports as a regular body schema.');
  });

  it('omits the feature when the document has no streams', async () => {
    const doc = { openapi: '3.1.0', info: { title: 'T', version: '1' }, paths: { '/a': { get: { responses: { '200': { description: 'ok', content: { 'application/json': { schema: { type: 'string' } } } } } } } } };
    const analysis = await analyzeSpecification(JSON.stringify(doc), 'a.json');
    expect(analysis.unsupportedFeatures.some((f) => f.id === 'sequential-media-types')).toBe(false);
  });
});
