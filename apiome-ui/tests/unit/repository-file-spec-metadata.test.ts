import {
  extractRepositoryFileDetailTables,
  getRepositoryFileImportableVerdict,
  parseRepositoryFileSpecMetadata,
  REPOSITORY_OPENAPI_VERSION_UNCLEAR_MESSAGE,
} from '@lib/repository-file-spec-metadata';

describe('parseRepositoryFileSpecMetadata', () => {
  it('parses OpenAPI 3 YAML with paths, components, servers', () => {
    const yaml = `
openapi: 3.0.1
info:
  title: Storefront
  version: 3.4.0
paths:
  /a:
    get:
      summary: A
  /b:
    post: {}
    put: {}
servers:
  - url: https://a.example
  - url: https://b.example
components:
  schemas:
    X: {}
    Y: {}
  parameters:
    P: {}
`;
    const m = parseRepositoryFileSpecMetadata(yaml, 'openapi.yaml');
    expect(m.format).toBe('openapi');
    expect(m.spec).toBe('OpenAPI 3.0.1');
    expect(m.title).toBe('Storefront');
    expect(m.version).toBe('3.4.0');
    expect(m.endpoints).toBe(3);
    expect(m.components).toBe(3);
    expect(m.servers).toBe(2);
    expect(m.parseError).toBeNull();
  });

  it('parses OpenAPI 3 JSON including webhooks', () => {
    const doc = {
      openapi: '3.1.0',
      info: { title: 'T', version: '1' },
      paths: { '/x': { delete: {} } },
      webhooks: { newPet: { post: {} } },
      components: { schemas: { A: {} } },
    };
    const m = parseRepositoryFileSpecMetadata(JSON.stringify(doc), 'spec.json');
    expect(m.endpoints).toBe(2);
    expect(m.components).toBe(1);
    expect(m.servers).toBe(0);
  });

  it('parses Swagger 2.0', () => {
    const doc = {
      swagger: '2.0',
      info: { title: 'Legacy', version: 'v2' },
      paths: { '/': { get: {} } },
      definitions: { A: {}, B: {} },
      schemes: ['https', 'http'],
    };
    const m = parseRepositoryFileSpecMetadata(JSON.stringify(doc), 'swagger.json');
    expect(m.format).toBe('swagger2');
    expect(m.spec).toBe('Swagger 2.0');
    expect(m.endpoints).toBe(1);
    expect(m.components).toBe(2);
    expect(m.servers).toBe(2);
  });

  it('parses AsyncAPI 2 channels', () => {
    const yaml = `
asyncapi: '2.6.0'
info:
  title: Events
  version: '1.0'
channels:
  user/signedup:
    subscribe:
      message:
        payload:
          type: object
  orders/created:
    publish:
      message:
        payload:
          type: object
servers:
  prod:
    url: kafka:9092
components:
  messages:
    UserSignedUp: {}
`;
    const m = parseRepositoryFileSpecMetadata(yaml, 'async.yaml');
    expect(m.format).toBe('asyncapi');
    expect(m.spec).toBe('AsyncAPI 2.6.0');
    expect(m.endpoints).toBe(2);
    expect(m.components).toBe(1);
    expect(m.servers).toBe(1);
  });

  it('parses GraphQL SDL', () => {
    const sdl = `
type Query {
  a: Int
  b: String
}
type Mutation {
  create: Boolean
}
`;
    const m = parseRepositoryFileSpecMetadata(sdl, 'schema.graphql');
    expect(m.format).toBe('graphql');
    expect(m.spec).toBe('GraphQL SDL');
    expect(m.endpoints).toBe(3);
  });

  it('parses Arazzo', () => {
    const yaml = `
arazzo: '1.0.0'
info:
  title: My Flows
  version: '0.1.0'
workflows:
  login:
    summary: Login
  checkout:
    summary: Buy
components:
  inputs:
    I: {}
servers:
  - url: https://api.example
`;
    const m = parseRepositoryFileSpecMetadata(yaml, 'flows.arazzo.yaml');
    expect(m.format).toBe('arazzo');
    expect(m.spec).toBe('Arazzo 1.0.0');
    expect(m.title).toBe('My Flows');
    expect(m.version).toBe('0.1.0');
    expect(m.endpoints).toBe(2);
    expect(m.components).toBe(1);
    expect(m.servers).toBe(1);
  });

  it('parses JSON Schema', () => {
    const doc = {
      $schema: 'https://json-schema.org/draft/2020-12/schema',
      title: 'Person',
      $defs: { A: {}, B: {}, C: {} },
    };
    const m = parseRepositoryFileSpecMetadata(JSON.stringify(doc), 'person.schema.json');
    expect(m.format).toBe('json_schema');
    expect(m.title).toBe('Person');
    expect(m.components).toBe(3);
    expect(m.endpoints).toBeNull();
    expect(m.servers).toBeNull();
  });
});

describe('extractRepositoryFileDetailTables', () => {
  it('lists OpenAPI paths, schema classes, and properties', () => {
    const yaml = `
openapi: 3.0.1
info:
  title: Storefront
  version: 3.4.0
paths:
  /a:
    get:
      summary: List A
  /b:
    post: {}
components:
  schemas:
    Order:
      type: object
      properties:
        id:
          type: string
        total:
          type: number
`;
    const t = extractRepositoryFileDetailTables(yaml, 'openapi.yaml');
    expect(t.format).toBe('openapi');
    expect(t.parseError).toBeNull();
    expect(t.paths.map((p) => p.template).sort()).toEqual(['/a', '/b']);
    expect(t.paths.some((p) => p.template === '/a' && p.method === 'GET')).toBe(true);
    expect(t.paths.find((p) => p.template === '/a' && p.method === 'GET')?.summary).toBe('List A');
    expect(t.classes.some((c) => c.name === 'Order' && c.kind === 'schemas')).toBe(true);
    expect(t.properties.map((p) => p.name).sort()).toEqual(['id', 'total']);
    expect(t.properties.every((p) => p.context === 'Order')).toBe(true);
  });

  it('maps GraphQL operations to paths and types to classes', () => {
    const sdl = `
type Query {
  item: String
}
type Product {
  sku: ID!
  name: String
}
`;
    const t = extractRepositoryFileDetailTables(sdl, 'schema.graphql');
    expect(t.format).toBe('graphql');
    expect(t.paths.some((p) => p.template === 'item' && p.method === 'Query')).toBe(true);
    expect(t.classes.some((c) => c.name === 'Product' && c.kind === 'type')).toBe(true);
    expect(t.properties.some((p) => p.context === 'Product' && p.name === 'sku')).toBe(true);
  });

  it('returns empty tables for unknown payloads without parse errors', () => {
    const t = extractRepositoryFileDetailTables('hello: world\nfoo', 'notes.txt');
    expect(t.format).toBe('unknown');
    expect(t.paths).toHaveLength(0);
    expect(t.classes).toHaveLength(0);
    expect(t.properties).toHaveLength(0);
  });
});

describe('getRepositoryFileImportableVerdict', () => {
  it('returns importable for recognised OpenAPI with stable serialisable shape', () => {
    const yaml = `
openapi: 3.0.1
info:
  title: T
  version: '1'
paths: {}
`;
    const meta = parseRepositoryFileSpecMetadata(yaml, 'openapi.yaml');
    const v = getRepositoryFileImportableVerdict(meta, { loadError: null });
    expect(v.status).toBe('importable');
    expect(v.summary).toBe('importable');
    expect(v.format).toBe('openapi');
    expect(v.spec).toBe('OpenAPI 3.0.1');
    expect(JSON.parse(JSON.stringify(v))).toEqual(v);
  });

  it('marks importable_truncated_body when truncated flag is set', () => {
    const yaml = `
openapi: 3.0.1
info:
  title: T
  version: '1'
paths: {}
`;
    const meta = parseRepositoryFileSpecMetadata(yaml, 'openapi.yaml');
    const v = getRepositoryFileImportableVerdict(meta, { loadError: null, truncated: true });
    expect(v.summary).toBe('importable_truncated_body');
    expect(v.truncated).toBe(true);
  });

  it('returns not_importable for unknown structure', () => {
    const meta = parseRepositoryFileSpecMetadata('hello: world\n', 'notes.txt');
    const v = getRepositoryFileImportableVerdict(meta, { loadError: null });
    expect(v.status).toBe('not_importable');
    expect(v.summary).toBe('not_importable');
    expect(v.format).toBe('unknown');
  });

  it('returns parse_failed when YAML is invalid', () => {
    const meta = parseRepositoryFileSpecMetadata('foo: [', 'bad.yaml');
    expect(meta.parseError).toBeTruthy();
    const v = getRepositoryFileImportableVerdict(meta, { loadError: null });
    expect(v.status).toBe('parse_failed');
    expect(v.summary).toBe('parse_failed');
    expect(v.parseError).toBe(meta.parseError);
  });

  it('returns content_unavailable when load failed', () => {
    const meta = parseRepositoryFileSpecMetadata('', 'x.yaml');
    const v = getRepositoryFileImportableVerdict(meta, { loadError: 'Gateway timeout' });
    expect(v.status).toBe('content_unavailable');
    expect(v.summary).toBe('content_unavailable');
    expect(v.loadError).toBe('Gateway timeout');
  });

  it('returns importable for Swagger / OpenAPI 2.0 (normalized to OpenAPI 3.1 during project import)', () => {
    const doc = {
      swagger: '2.0',
      info: { title: 'Legacy', version: '1' },
      paths: {},
    };
    const meta = parseRepositoryFileSpecMetadata(JSON.stringify(doc), 'swagger.json');
    expect(meta.format).toBe('swagger2');
    const v = getRepositoryFileImportableVerdict(meta, { loadError: null });
    expect(v.status).toBe('importable');
    expect(v.summary).toBe('importable');
    expect(v.format).toBe('swagger2');
    expect(v.spec).toBe('Swagger 2.0');
  });

  it('detects Swagger 2 when swagger is a JSON number (e.g. 2.0)', () => {
    const doc = {
      swagger: 2,
      info: { title: 'Legacy', version: '1' },
      paths: {},
    };
    const meta = parseRepositoryFileSpecMetadata(JSON.stringify(doc), 'swagger.json');
    expect(meta.format).toBe('swagger2');
    const v = getRepositoryFileImportableVerdict(meta, { loadError: null });
    expect(v.status).toBe('importable');
  });

  it('returns not_importable with unsupported_openapi_version when openapi field is below 3.0', () => {
    const doc = {
      openapi: '2.0',
      info: { title: 'Odd', version: '1' },
      paths: {},
    };
    const meta = parseRepositoryFileSpecMetadata(JSON.stringify(doc), 'odd.yaml');
    expect(meta.format).toBe('openapi');
    const v = getRepositoryFileImportableVerdict(meta, { loadError: null });
    expect(v.status).toBe('not_importable');
    expect(v.summary).toBe('unsupported_openapi_version');
    expect(v.format).toBe('openapi');
    expect(v.notImportableMessage).toContain('OpenAPI 2.x');
  });

  it('returns not_importable with unsupported_openapi_version when OpenAPI semver cannot be read', () => {
    const yaml = `
openapi: "x"
info:
  title: T
  version: '1'
paths: {}
`;
    const meta = parseRepositoryFileSpecMetadata(yaml, 'bad-openapi.yaml');
    expect(meta.format).toBe('openapi');
    const v = getRepositoryFileImportableVerdict(meta, { loadError: null });
    expect(v.status).toBe('not_importable');
    expect(v.summary).toBe('unsupported_openapi_version');
    expect(v.notImportableMessage).toBe(REPOSITORY_OPENAPI_VERSION_UNCLEAR_MESSAGE);
  });
});
