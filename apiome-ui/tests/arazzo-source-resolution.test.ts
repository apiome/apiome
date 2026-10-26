/**
 * AZ2 (#3505) — Arazzo `sourceDescriptions` resolution and validation on import.
 *
 * Covers in-bundle resolution (operationId in all three spellings, operationPath),
 * cross-source resolution across two OpenAPI sources, the missing-source warning, every
 * structured issue code, and the map exposed on the importer result.
 */

/** Arazzo documents are walked untyped, like the OpenAPI import utilities. */
/* eslint-disable @typescript-eslint/no-explicit-any */

import { arazzoImporter } from '../lib/importers/arazzo';
import { arazzoResolutionWarnings, resolveArazzoSources } from '../lib/importers/arazzo-sources';

/** OpenAPI source: pets (includes a QUERY operation, OA4). */
const PETSTORE = {
  openapi: '3.2.0',
  info: { title: 'Pets', version: '1' },
  paths: {
    '/pets': {
      get: { operationId: 'listPets', responses: {} },
      query: { operationId: 'searchPets', responses: {} },
    },
    '/pets/{petId}': { get: { operationId: 'getPet', responses: {} } },
  },
};

/** OpenAPI source: users (shares `ping` with orders to make a bare id ambiguous). */
const USERS = {
  openapi: '3.1.0',
  info: { title: 'Users', version: '1' },
  paths: {
    '/users/{id}': { get: { operationId: 'getUser', responses: {} } },
    '/ping': { get: { operationId: 'ping', responses: {} } },
  },
};

const ORDERS = {
  openapi: '3.1.0',
  info: { title: 'Orders', version: '1' },
  paths: { '/ping': { get: { operationId: 'ping', responses: {} } } },
};

/** The bundle, keyed by member path; the workflow lives in `flows/`. */
const BUNDLE: Record<string, unknown> = {
  'specs/petstore.yaml': PETSTORE,
  'flows/users.yaml': USERS,
  'orders.json': ORDERS,
  'flows/other.arazzo.yaml': { arazzo: '1.0.1', info: { title: 'Other', version: '1' }, workflows: [] },
};

/** Build an Arazzo document with the given sources and steps (one workflow `adopt`). */
function arazzo(sourceDescriptions: any[], steps: any[]): any {
  return {
    arazzo: '1.0.1',
    info: { title: 'Adoption', version: '1' },
    sourceDescriptions,
    workflows: [{ workflowId: 'adopt', steps }],
  };
}

const SOURCES = [
  { name: 'petstore', type: 'openapi', url: '../specs/petstore.yaml' },
  { name: 'users', type: 'openapi', url: './users.yaml' },
  { name: 'orders', url: '/orders.json' },
];

/** Resolve with the standard bundle. */
function resolve(doc: any) {
  return resolveArazzoSources({ document: doc, sourceDocuments: BUNDLE, documentPath: 'flows/adopt.arazzo.yaml' });
}

describe('sourceDescriptions — registration and validation', () => {
  it('matches each relative url to a bundle member and records its kind', () => {
    const { sources, issues } = resolve(arazzo(SOURCES, []));
    expect(sources).toEqual([
      { name: 'petstore', type: 'openapi', url: '../specs/petstore.yaml', status: 'resolved', path: 'specs/petstore.yaml', documentKind: 'openapi' },
      { name: 'users', type: 'openapi', url: './users.yaml', status: 'resolved', path: 'flows/users.yaml', documentKind: 'openapi' },
      { name: 'orders', url: '/orders.json', status: 'resolved', path: 'orders.json', documentKind: 'openapi' },
    ]);
    expect(issues).toEqual([]);
  });

  it('warns about a source that is not in the bundle instead of dropping it', () => {
    const { sources, issues } = resolve(arazzo([{ name: 'billing', type: 'openapi', url: 'https://api.example.com/billing.yaml' }], []));
    expect(sources[0]).toMatchObject({ name: 'billing', status: 'not-in-bundle' });
    expect(issues).toEqual([
      {
        code: 'SOURCE_NOT_IN_BUNDLE',
        source: 'billing',
        message: 'Source "billing" (https://api.example.com/billing.yaml) is not in the import bundle; steps that call it keep their raw reference.',
      },
    ]);
  });

  it('warns about an unrecognized type', () => {
    const { sources, issues } = resolve(arazzo([{ name: 'events', type: 'asyncapi', url: 'events.yaml' }], []));
    expect(sources[0].status).toBe('unsupported-type');
    expect(issues.map((i) => i.code)).toEqual(['SOURCE_TYPE_UNSUPPORTED']);
  });

  it('warns when the matched document is not the declared type', () => {
    const { sources, issues } = resolve(arazzo([{ name: 'other', type: 'openapi', url: 'other.arazzo.yaml' }], []));
    expect(sources[0]).toMatchObject({ status: 'type-mismatch' });
    expect(issues[0]).toMatchObject({ code: 'SOURCE_TYPE_MISMATCH', source: 'other' });
    expect(issues[0].message).toContain('flows/other.arazzo.yaml, which is an arazzo document, not openapi');
  });

  it('registers a sibling Arazzo source without indexing operations', () => {
    const { sources } = resolve(arazzo([{ name: 'other', type: 'arazzo', url: 'other.arazzo.yaml' }], []));
    expect(sources[0]).toMatchObject({ status: 'resolved', documentKind: 'arazzo' });
  });

  it('reports entries without a name or url, and duplicate names', () => {
    const { sources, issues } = resolve(
      arazzo([{ url: 'x.yaml' }, { name: 'nourl' }, SOURCES[0], { ...SOURCES[0], url: 'elsewhere.yaml' }, 'junk'], [])
    );
    expect(sources.map((s) => s.name)).toEqual(['petstore']);
    expect(issues.map((i) => [i.code, i.source])).toEqual([
      ['SOURCE_INVALID', undefined],
      ['SOURCE_INVALID', 'nourl'],
      ['SOURCE_DUPLICATE', 'petstore'],
      ['SOURCE_INVALID', undefined],
    ]);
  });

  it('accepts a $ref in place of url', () => {
    const { sources } = resolve(arazzo([{ name: 'petstore', type: 'openapi', $ref: '../specs/petstore.yaml' }], []));
    expect(sources[0].status).toBe('resolved');
  });

  it('never matches the Arazzo document itself', () => {
    const { sources } = resolveArazzoSources({
      document: arazzo([{ name: 'self', url: 'adopt.arazzo.yaml' }], []),
      sourceDocuments: { 'flows/adopt.arazzo.yaml': PETSTORE },
      documentPath: 'flows/adopt.arazzo.yaml',
    });
    expect(sources[0].status).toBe('not-in-bundle');
  });

  it('handles a document without sourceDescriptions or workflows', () => {
    expect(resolveArazzoSources({ document: { arazzo: '1.0.1' } })).toEqual({ sources: [], steps: [], issues: [] });
    expect(resolveArazzoSources({ document: null })).toEqual({ sources: [], steps: [], issues: [] });
  });
});

describe('step references — in-bundle resolution', () => {
  it('resolves operationId in the bare, <source>.<id> and $sourceDescriptions spellings', () => {
    const { steps, issues } = resolve(
      arazzo(SOURCES, [
        { stepId: 'bare', operationId: 'getPet' },
        { stepId: 'dotted', operationId: 'petstore.listPets' },
        { stepId: 'expression', operationId: '$sourceDescriptions.petstore.searchPets' },
      ])
    );
    expect(steps.map((s) => [s.stepId, s.kind, s.status, s.sourceName, s.operation])).toEqual([
      ['bare', 'operationId', 'resolved', 'petstore', { operationId: 'getPet', path: '/pets/{petId}', method: 'GET' }],
      ['dotted', 'operationId', 'resolved', 'petstore', { operationId: 'listPets', path: '/pets', method: 'GET' }],
      ['expression', 'operationId', 'resolved', 'petstore', { operationId: 'searchPets', path: '/pets', method: 'QUERY' }],
    ]);
    expect(issues).toEqual([]);
  });

  it('resolves operationPath JSON pointers', () => {
    const { steps } = resolve(
      arazzo(SOURCES, [{ stepId: 'byPath', operationPath: '{$sourceDescriptions.petstore.url}#/paths/~1pets~1{petId}/get' }])
    );
    expect(steps[0]).toMatchObject({
      kind: 'operationPath',
      status: 'resolved',
      sourceName: 'petstore',
      reference: '{$sourceDescriptions.petstore.url}#/paths/~1pets~1{petId}/get',
      operation: { operationId: 'getPet', path: '/pets/{petId}', method: 'GET' },
    });
  });

  it('treats a dotted id whose prefix is not a source as a bare id', () => {
    const doc = arazzo(SOURCES, [{ stepId: 's', operationId: 'pets.list' }]);
    const { steps } = resolveArazzoSources({
      document: doc,
      sourceDocuments: { ...BUNDLE, 'specs/petstore.yaml': { ...PETSTORE, paths: { '/p': { get: { operationId: 'pets.list' } } } } },
      documentPath: 'flows/adopt.arazzo.yaml',
    });
    expect(steps[0]).toMatchObject({ status: 'resolved', sourceName: 'petstore', operation: { path: '/p' } });
  });

  it('marks workflow calls and target-less steps as not applicable', () => {
    const { steps, issues } = resolve(arazzo(SOURCES, [{ stepId: 'sub', workflowId: 'other' }, {}]));
    expect(steps.map((s) => [s.stepId, s.kind, s.status])).toEqual([
      ['sub', 'workflowId', 'not-applicable'],
      ['step1', 'none', 'not-applicable'],
    ]);
    expect(issues).toEqual([]);
  });
});

describe('step references — cross-source resolution', () => {
  it('resolves each step against the source that holds its operation', () => {
    const { steps } = resolve(
      arazzo(SOURCES, [
        { stepId: 'pet', operationId: 'getPet' },
        { stepId: 'user', operationId: 'getUser' },
        { stepId: 'userPath', operationPath: '{$sourceDescriptions.users.url}#/paths/~1users~1{id}/get' },
        { stepId: 'orderPing', operationId: 'orders.ping' },
      ])
    );
    expect(steps.map((s) => [s.stepId, s.sourceName, s.operation?.path])).toEqual([
      ['pet', 'petstore', '/pets/{petId}'],
      ['user', 'users', '/users/{id}'],
      ['userPath', 'users', '/users/{id}'],
      ['orderPing', 'orders', '/ping'],
    ]);
  });

  it('refuses a bare id found in several sources and asks for the source', () => {
    const { steps, issues } = resolve(arazzo(SOURCES, [{ stepId: 'ping', operationId: 'ping' }]));
    expect(steps[0]).toMatchObject({ status: 'unresolved', reference: 'ping' });
    expect(steps[0].reason).toBe('"ping" is in several sources (users, orders); name the source');
    expect(issues[0]).toMatchObject({ code: 'STEP_REFERENCE_UNRESOLVED', workflowId: 'adopt', stepId: 'ping' });
  });
});

describe('step references — unresolved keep the raw string', () => {
  it('names a missing source and keeps the reference', () => {
    const doc = arazzo([...SOURCES, { name: 'billing', type: 'openapi', url: 'billing.yaml' }], [
      { stepId: 'charge', operationId: '$sourceDescriptions.billing.createCharge' },
    ]);
    const { steps, issues } = resolve(doc);
    expect(steps[0]).toEqual({
      workflowId: 'adopt',
      stepId: 'charge',
      kind: 'operationId',
      reference: '$sourceDescriptions.billing.createCharge',
      status: 'unresolved',
      sourceName: 'billing',
      reason: 'source "billing" is not in bundle',
    });
    expect(issues.map((i) => i.code)).toEqual(['SOURCE_NOT_IN_BUNDLE', 'STEP_REFERENCE_UNRESOLVED']);
    expect(issues[1].message).toBe(
      'Step "adopt.charge" reference "$sourceDescriptions.billing.createCharge" did not resolve (source "billing" is not in bundle); the raw reference is kept.'
    );
  });

  it.each([
    ['an undeclared source', { operationId: '$sourceDescriptions.nope.getPet' }, 'source "nope" is not declared'],
    ['an unknown operation', { operationId: 'petstore.deletePet' }, 'no operation "deletePet" in source "petstore"'],
    ['an unknown bare id', { operationId: 'doesNotExist' }, 'no source has operation "doesNotExist"'],
    ['a path not in the source', { operationPath: '{$sourceDescriptions.petstore.url}#/paths/~1cats/get' }, 'no GET /cats in source "petstore"'],
    ['a malformed operationPath', { operationPath: 'petstore#/paths/~1pets/get' }, 'not a {$sourceDescriptions.<name>.url}#/paths/... expression'],
    ['a pointer outside #/paths', { operationPath: '{$sourceDescriptions.petstore.url}#/components/schemas/Pet' }, 'the pointer does not name #/paths/<path>/<method>'],
    ['an Arazzo source', { operationId: 'other.run' }, 'source "other" is not an OpenAPI document'],
  ])('reports %s', (_label, target, reason) => {
    const doc = arazzo([...SOURCES, { name: 'other', type: 'arazzo', url: 'other.arazzo.yaml' }], [{ stepId: 's', ...target }]);
    const { steps } = resolve(doc);
    expect(steps[0]).toMatchObject({ status: 'unresolved', reason });
    expect(steps[0].reference).toBe((target as any).operationId ?? (target as any).operationPath);
  });

  it('explains that nothing can resolve when no source is supplied (today\'s callers)', () => {
    const { sources, steps } = resolveArazzoSources({ document: arazzo(SOURCES, [{ stepId: 'pet', operationId: 'getPet' }]) });
    expect(sources.every((s) => s.status === 'not-in-bundle')).toBe(true);
    expect(steps[0]).toMatchObject({ status: 'unresolved', reason: 'no OpenAPI source is in the import bundle' });
  });
});

describe('arazzoImporter.normalize — resolution on the import result', () => {
  const doc = {
    ...arazzo([...SOURCES, { name: 'billing', type: 'openapi', url: 'billing.yaml' }], [
      { stepId: 'pet', operationId: 'getPet', requestBody: { payload: { name: 'Rex' } } },
      { stepId: 'charge', operationId: 'billing.createCharge' },
    ]),
  };

  it('exposes the map and adds its issues to the warnings', () => {
    const result = arazzoImporter.normalize({
      document: doc,
      options: { selectedSchemas: [], sourceDocuments: BUNDLE, documentPath: 'flows/adopt.arazzo.yaml' },
    });
    expect(result.arazzoResolution?.steps.map((s) => [s.stepId, s.status])).toEqual([
      ['pet', 'resolved'],
      ['charge', 'unresolved'],
    ]);
    expect(result.warnings).toEqual(expect.arrayContaining(arazzoResolutionWarnings(result.arazzoResolution!)));
    expect(result.classes.map((c) => c.originalSchemaKey)).toEqual(['adoptpet']);
  });

  it('still exposes the map when there are no classes to import', () => {
    const result = arazzoImporter.normalize({
      document: arazzo(SOURCES, [{ stepId: 'pet', operationId: 'getPet' }]),
      options: { selectedSchemas: [], sourceDocuments: BUNDLE, documentPath: 'flows/adopt.arazzo.yaml' },
    });
    expect(result.classes).toEqual([]);
    expect(result.arazzoResolution?.steps[0].status).toBe('resolved');
    expect(result.warnings).toContain('No components.schemas and no workflow steps with request bodies to import.');
  });
});
