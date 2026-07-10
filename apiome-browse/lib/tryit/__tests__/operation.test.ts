import { describe, expect, it } from 'vitest';
import {
  buildMonacoBodySchema,
  buildRequestHeaders,
  buildRequestUrl,
  buildServerOptions,
  extractOperationModel,
  isJsonContentType,
  paramKey,
  resolveRef,
  validateParams,
  validateParamValue,
  type ParamSpec,
} from '../operation';

/** A representative petstore-ish document exercising refs, merging, and body variants. */
const SPEC = {
  openapi: '3.0.3',
  servers: [
    { url: 'https://api.example.com/v1', description: 'Production' },
    {
      url: 'https://{region}.example.com/{basePath}',
      variables: {
        region: { default: 'eu', enum: ['eu', 'us'] },
        basePath: { enum: ['v2', 'v3'] },
      },
    },
  ],
  paths: {
    '/pets/{petId}': {
      parameters: [
        { name: 'petId', in: 'path', required: true, schema: { type: 'integer' } },
        { name: 'X-Trace', in: 'header', schema: { type: 'string' } },
      ],
      get: {
        summary: 'Fetch a pet',
        parameters: [
          { name: 'verbose', in: 'query', schema: { type: 'boolean' } },
          { $ref: '#/components/parameters/Status' },
          // Operation-level override of the path-item header.
          { name: 'X-Trace', in: 'header', required: true, schema: { type: 'string' } },
          // Cookie parameters are skipped.
          { name: 'session', in: 'cookie', schema: { type: 'string' } },
        ],
      },
      post: {
        requestBody: {
          required: true,
          content: {
            'application/json': {
              schema: { $ref: '#/components/schemas/Pet' },
              examples: {
                minimal: { summary: 'Name only', value: { name: 'Rex' } },
              },
              example: { name: 'Fallback' },
            },
            'text/plain': { schema: { type: 'string' }, example: 'plain body' },
          },
        },
      },
    },
    '/health': { get: {} },
  },
  components: {
    parameters: {
      Status: {
        name: 'status',
        in: 'query',
        schema: { type: 'string', enum: ['available', 'sold'], default: 'available' },
      },
    },
    schemas: {
      Pet: {
        type: 'object',
        required: ['name'],
        properties: { name: { type: 'string' } },
      },
    },
  },
};

describe('resolveRef', () => {
  it('returns non-ref objects unchanged', () => {
    expect(resolveRef(SPEC, { type: 'string' })).toEqual({ type: 'string' });
  });

  it('resolves local pointers, including escaped segments', () => {
    const root = { 'a/b': { '~x': { ok: true } } };
    expect(resolveRef(root, { $ref: '#/a~1b/~0x' })).toEqual({ ok: true });
  });

  it('resolves chained refs', () => {
    const root = { a: { $ref: '#/b' }, b: { done: true } };
    expect(resolveRef(root, { $ref: '#/a' })).toEqual({ done: true });
  });

  it('returns null for external refs, broken pointers, cycles, and non-objects', () => {
    expect(resolveRef(SPEC, { $ref: 'other.yaml#/x' })).toBeNull();
    expect(resolveRef(SPEC, { $ref: '#/nope/nothing' })).toBeNull();
    const cyclic: Record<string, unknown> = {};
    cyclic.a = { $ref: '#/a' };
    expect(resolveRef(cyclic, { $ref: '#/a' })).toBeNull();
    expect(resolveRef(SPEC, 'not-an-object')).toBeNull();
    expect(resolveRef(SPEC, undefined)).toBeNull();
  });
});

describe('extractOperationModel', () => {
  it('returns null for missing documents, paths, or operations', () => {
    expect(extractOperationModel(null, 'get', '/pets/{petId}')).toBeNull();
    expect(extractOperationModel(SPEC, 'get', '/missing')).toBeNull();
    expect(extractOperationModel(SPEC, 'delete', '/pets/{petId}')).toBeNull();
  });

  it('merges path-item and operation parameters with operation-level override', () => {
    const model = extractOperationModel(SPEC, 'GET', '/pets/{petId}');
    expect(model).not.toBeNull();
    expect(model!.method).toBe('GET');
    expect(model!.summary).toBe('Fetch a pet');
    const byKey = Object.fromEntries(model!.params.map((p) => [paramKey(p), p]));
    // Path param present and forced required.
    expect(byKey['path:petId']).toMatchObject({ required: true, schema: { type: 'integer' } });
    // Query params: plain and $ref-resolved with enum + default.
    expect(byKey['query:verbose'].schema.type).toBe('boolean');
    expect(byKey['query:status'].schema.enum).toEqual(['available', 'sold']);
    expect(byKey['query:status'].schema.default).toBe('available');
    // Operation-level header overrides the path-item one.
    expect(byKey['header:X-Trace'].required).toBe(true);
    // Cookie param skipped.
    expect(byKey['cookie:session']).toBeUndefined();
    // Sorted path → query → header.
    expect(model!.params.map((p) => p.location)).toEqual(['path', 'query', 'query', 'header']);
  });

  it('extracts request-body variants with resolved schemas and the required flag', () => {
    const model = extractOperationModel(SPEC, 'post', '/pets/{petId}');
    expect(model!.bodyRequired).toBe(true);
    expect(model!.bodyVariants).toHaveLength(2);
    const json = model!.bodyVariants.find((v) => v.contentType === 'application/json');
    expect(json!.schema).toMatchObject({ type: 'object', required: ['name'] });
    expect(json!.examples?.minimal).toEqual({ summary: 'Name only', value: { name: 'Rex' } });
    expect(json!.example).toEqual({ name: 'Fallback' });
    const plain = model!.bodyVariants.find((v) => v.contentType === 'text/plain');
    expect(plain!.example).toBe('plain body');
  });

  it('extracts parameter-level examples for prefill', () => {
    const spec = {
      ...SPEC,
      paths: {
        '/search': {
          get: {
            parameters: [
              {
                name: 'q',
                in: 'query',
                schema: { type: 'string' },
                examples: { demo: { value: 'cats' } },
              },
            ],
          },
        },
      },
    };
    const model = extractOperationModel(spec, 'get', '/search');
    expect(model!.params[0].schema.examples?.demo).toEqual({ value: 'cats' });
  });

  it('yields no body variants for body-less operations', () => {
    const model = extractOperationModel(SPEC, 'get', '/health');
    expect(model!.params).toEqual([]);
    expect(model!.bodyVariants).toEqual([]);
    expect(model!.bodyRequired).toBe(false);
  });
});

describe('buildServerOptions', () => {
  it('puts the mock first, then spec servers with variable defaults substituted', () => {
    const options = buildServerOptions(SPEC, 'https://mock.host/acme/petstore/1.2/');
    expect(options.map((o) => o.kind)).toEqual(['mock', 'spec', 'spec']);
    expect(options[0].url).toBe('https://mock.host/acme/petstore/1.2');
    expect(options[1]).toMatchObject({
      url: 'https://api.example.com/v1',
      description: 'Production',
    });
    // `region` uses its default; `basePath` (no default) falls back to its first enum value.
    expect(options[2].url).toBe('https://eu.example.com/v2');
  });

  it('omits the mock when disabled and tolerates specs without servers', () => {
    expect(buildServerOptions({ paths: {} }, null)).toEqual([]);
    expect(buildServerOptions(null, 'https://mock.host/a/b/1')).toHaveLength(1);
  });
});

describe('validateParamValue / validateParams', () => {
  const param = (over: Partial<ParamSpec>): ParamSpec => ({
    name: 'p',
    location: 'query',
    required: false,
    schema: {},
    ...over,
  });

  it('requires required params and accepts empty optionals', () => {
    expect(validateParamValue(param({ required: true }), '  ')).toBe('Required');
    expect(validateParamValue(param({}), '')).toBeNull();
  });

  it('checks integer, number, boolean, and enum values', () => {
    const int = param({ schema: { type: 'integer' } });
    expect(validateParamValue(int, '42')).toBeNull();
    expect(validateParamValue(int, '-7')).toBeNull();
    expect(validateParamValue(int, '4.2')).toBe('Must be an integer');
    expect(validateParamValue(int, 'abc')).toBe('Must be an integer');

    const num = param({ schema: { type: 'number' } });
    expect(validateParamValue(num, '4.2')).toBeNull();
    expect(validateParamValue(num, 'x')).toBe('Must be a number');

    const bool = param({ schema: { type: 'boolean' } });
    expect(validateParamValue(bool, 'true')).toBeNull();
    expect(validateParamValue(bool, 'yes')).toBe('Must be true or false');

    const en = param({ schema: { type: 'string', enum: ['a', 'b'] } });
    expect(validateParamValue(en, 'a')).toBeNull();
    expect(validateParamValue(en, 'c')).toBe('Must be one of: a, b');
  });

  it('collects errors across all params keyed by paramKey', () => {
    const params = [
      param({ name: 'id', location: 'path', required: true, schema: { type: 'integer' } }),
      param({ name: 'verbose', schema: { type: 'boolean' } }),
    ];
    const errors = validateParams(params, { 'query:verbose': 'nope' });
    expect(errors).toEqual({
      'path:id': 'Required',
      'query:verbose': 'Must be true or false',
    });
    expect(
      validateParams(params, { 'path:id': '3', 'query:verbose': 'true' })
    ).toEqual({});
  });
});

describe('buildRequestUrl', () => {
  const params: ParamSpec[] = [
    { name: 'petId', location: 'path', required: true, schema: { type: 'integer' } },
    { name: 'tag', location: 'query', required: false, schema: {} },
    { name: 'verbose', location: 'query', required: false, schema: { type: 'boolean' } },
    { name: 'X-Trace', location: 'header', required: false, schema: {} },
  ];

  it('substitutes encoded path params and appends non-empty query params', () => {
    const url = buildRequestUrl('https://h.example/base/', '/pets/{petId}', params, {
      'path:petId': '4 2',
      'query:tag': 'a&b',
      'query:verbose': '',
      'header:X-Trace': 'ignored-here',
    });
    expect(url).toBe('https://h.example/base/pets/4%202?tag=a%26b');
  });

  it('handles paths without a leading slash and no query values', () => {
    expect(buildRequestUrl('https://h.example', 'health', [], {})).toBe(
      'https://h.example/health'
    );
  });
});

describe('buildRequestHeaders', () => {
  it('combines spec header params, user headers, and Content-Type', () => {
    const params: ParamSpec[] = [
      { name: 'X-Trace', location: 'header', required: false, schema: {} },
      { name: 'X-Empty', location: 'header', required: false, schema: {} },
      { name: 'petId', location: 'path', required: true, schema: {} },
    ];
    const headers = buildRequestHeaders(
      params,
      { 'header:X-Trace': 'abc', 'header:X-Empty': ' ' },
      [
        { name: ' X-Custom ', value: '1' },
        { name: '', value: 'skipped' },
      ],
      'application/json'
    );
    expect(headers).toEqual({
      'X-Trace': 'abc',
      'X-Custom': '1',
      'Content-Type': 'application/json',
    });
  });

  it('omits Content-Type when no body is sent', () => {
    expect(buildRequestHeaders([], {}, [], null)).toEqual({});
  });
});

describe('isJsonContentType', () => {
  it('recognizes JSON media types including suffixes and parameters', () => {
    expect(isJsonContentType('application/json')).toBe(true);
    expect(isJsonContentType('application/hal+json')).toBe(true);
    expect(isJsonContentType('application/json; charset=utf-8')).toBe(true);
    expect(isJsonContentType('text/plain')).toBe(false);
    expect(isJsonContentType('application/xml')).toBe(false);
  });
});

describe('buildMonacoBodySchema', () => {
  it('returns null without a schema', () => {
    expect(buildMonacoBodySchema(SPEC, null)).toBeNull();
  });

  it('attaches spec components so local refs keep resolving', () => {
    const schema = buildMonacoBodySchema(SPEC, {
      type: 'object',
      properties: { pet: { $ref: '#/components/schemas/Pet' } },
    });
    expect(schema).toMatchObject({ type: 'object' });
    expect((schema!.components as Record<string, unknown>).schemas).toBeDefined();
  });

  it('wraps a root-level $ref in allOf', () => {
    const schema = buildMonacoBodySchema(SPEC, { $ref: '#/components/schemas/Pet' });
    expect(schema!.allOf).toEqual([{ $ref: '#/components/schemas/Pet' }]);
    expect(schema!.components).toBeDefined();
  });

  it('tolerates specs without components', () => {
    const schema = buildMonacoBodySchema({}, { type: 'string' });
    expect(schema).toEqual({ type: 'string' });
  });
});
