/**
 * The GraphQL test drive's schema reading and mock data — MFX-44.3 (#4369).
 *
 * - `readGraphQLSdl` reads valid SDL (tolerating applied directives the file does not declare), and
 *   says why a file cannot be explored: empty, a syntax error, an unknown type, an invalid schema, no
 *   Query type;
 * - `exampleQuery` picks a query-root field, fills required scalar/enum arguments, skips input-object
 *   arguments, and selects leaf fields (or `__typename`);
 * - the mock answers queries and mutations with values of the right type (custom scalars by name),
 *   the same answer twice, reports parse/validation errors, and refuses subscriptions.
 */

import { buildSchema, type GraphQLSchema } from 'graphql';

import {
  exampleQuery,
  isCustomScalarName,
  MOCK_DATA_COMMENT,
  placeholderLiteral,
  readGraphQLSdl,
  summarizeSchema,
} from '../lib/test-drive/graphql-sdl';
import {
  buildMockSchema,
  customScalarMock,
  executeMock,
  scalarMocks,
  SUBSCRIPTIONS_NOT_MOCKED,
} from '../lib/test-drive/graphql-mock';
import { schemaSummaryText } from '../src/app/components/ade/dashboard/export/graphqlTestDrive';

const SDL = `
"""A pet."""
type Pet {
  id: ID!
  name: String!
  age: Int
  weight: Float
  vaccinated: Boolean!
  status: PetStatus!
  born: DateTime
  tags: [String!]!
  owner: Owner
}

enum PetStatus { AVAILABLE SOLD }

scalar DateTime

type Owner { id: ID! email: Email }

scalar Email

type Query {
  pets(limit: Int = 10): [Pet!]!
  pet(id: ID!): Pet
}

input NewPet { name: String! }

type Mutation { addPet(input: NewPet!): Pet! }

type Subscription { petAdded: Pet! }
`;

/** Read SDL that must be valid. */
function schemaOf(sdl: string): GraphQLSchema {
  const read = readGraphQLSdl(sdl);
  if (!read.ok) throw new Error(read.error);
  return read.schema;
}

describe('readGraphQLSdl', () => {
  it('reads valid SDL and counts what it declares', () => {
    const read = readGraphQLSdl(SDL);
    expect(read.ok).toBe(true);
    expect(read.ok && read.summary).toEqual({ types: 9, queries: 2, mutations: 1, subscriptions: 1 });
  });

  it('tolerates applied directives the file does not declare', () => {
    const read = readGraphQLSdl('type Query { me: User }\ntype User @key(fields: "id") { id: ID! }');
    expect(read.ok).toBe(true);
  });

  it('says why a file cannot be explored', () => {
    expect(readGraphQLSdl('  \n')).toMatchObject({ ok: false, error: expect.stringContaining('empty') });
    expect(readGraphQLSdl('type Query {')).toMatchObject({ ok: false, error: expect.stringContaining('not valid GraphQL SDL') });
    expect(readGraphQLSdl('type Query { a: Missing }')).toMatchObject({ ok: false, error: expect.stringContaining('Missing') });
    expect(readGraphQLSdl('{"openapi":"3.1.0"}')).toMatchObject({ ok: false });
    expect(readGraphQLSdl('interface Node { id: ID! }\ntype Query { a: A }\ntype A implements Node { name: String }')).toMatchObject({
      ok: false,
      error: expect.stringContaining('not valid'),
    });
    expect(readGraphQLSdl('type Mutation { a: Int }')).toMatchObject({ ok: false, error: expect.stringContaining('Query root type must be provided') });
  });
});

describe('summarizeSchema / schemaSummaryText', () => {
  it('leaves out built-in scalars and introspection types, and zero roots in the text', () => {
    const summary = summarizeSchema(buildSchema('type Query { a: Int }'));
    expect(summary).toEqual({ types: 1, queries: 1, mutations: 0, subscriptions: 0 });
    expect(schemaSummaryText(summary)).toBe('1 type · 1 query');
    expect(schemaSummaryText({ types: 7, queries: 2, mutations: 1, subscriptions: 3 })).toBe(
      '7 types · 2 queries · 1 mutation · 3 subscriptions',
    );
  });
});

describe('exampleQuery', () => {
  it('selects the first argument-free field and its leaf fields, under the mock-data comment', () => {
    const query = exampleQuery(schemaOf(SDL));
    expect(query.startsWith(MOCK_DATA_COMMENT)).toBe(true);
    expect(query).toContain('  pets {\n    id\n    name\n    age\n    weight\n    vaccinated\n    status\n  }');
    expect(query).not.toContain('owner');
  });

  it('fills required scalar and enum arguments, and skips fields that need an input object', () => {
    const schema = schemaOf(`
      enum Kind { A B }
      input Filter { q: String }
      type Item { id: ID! }
      type Query { search(filter: Filter!): [Item] item(id: ID!, kind: Kind!, n: [Int!]!): Item }
    `);
    expect(exampleQuery(schema)).toContain('item(id: "example", kind: A, n: [1]) {\n    id\n  }');
  });

  it('selects __typename for a union, an object without leaf fields, or nothing usable', () => {
    expect(exampleQuery(schemaOf('type A { a: Int }\nunion U = A\ntype Query { u: U }'))).toContain('u {\n    __typename\n  }');
    expect(exampleQuery(schemaOf('type B { b: B }\ntype Query { b: B }'))).toContain('b {\n    __typename\n  }');
    expect(exampleQuery(schemaOf('input I { a: Int }\ntype Query { x(i: I!): Int }'))).toContain('query Example {\n  __typename\n}');
    expect(exampleQuery(schemaOf('type Query { n: Int }'))).toContain('  n\n}');
  });

  it('writes placeholders for each scalar', () => {
    const schema = buildSchema('type Query { a(i: Int, f: Float, b: Boolean, s: String): Int }');
    const args = Object.fromEntries(schema.getQueryType()!.getFields().a.args.map((arg) => [arg.name, placeholderLiteral(arg.type)]));
    expect(args).toEqual({ i: '1', f: '1.5', b: 'true', s: '"example"' });
  });
});

describe('the mock', () => {
  it('recognizes custom scalars by name, and labels the rest', () => {
    expect(customScalarMock('DateTime')).toBe('2026-01-15T09:30:00Z');
    expect(customScalarMock('Date')).toBe('2026-01-15');
    expect(customScalarMock('UUID')).toMatch(/^[0-9a-f-]{36}$/);
    expect(customScalarMock('URL')).toBe('https://example.com/resource');
    expect(customScalarMock('JSON')).toEqual({ example: true });
    expect(customScalarMock('BigInt')).toEqual(expect.any(Number));
    expect(customScalarMock('Decimal')).toBe(12.5);
    expect(customScalarMock('Upload')).toBe('aGVsbG8=');
    expect(customScalarMock('Opaque')).toBe('Opaque mock');
  });

  it('has a mock for every custom scalar the schema declares', () => {
    const schema = schemaOf(SDL);
    const mocks = scalarMocks(schema);
    expect(Object.keys(mocks).sort()).toEqual(['Boolean', 'DateTime', 'Email', 'Float', 'ID', 'Int', 'String']);
    expect(isCustomScalarName(schema, 'DateTime')).toBe(true);
    expect(isCustomScalarName(schema, 'String')).toBe(false);
    expect(isCustomScalarName(schema, 'Pet')).toBe(false);
  });

  it('answers a query with values of the right type', async () => {
    const mocked = buildMockSchema(schemaOf(SDL));
    const result = await executeMock(mocked, {
      query: '{ pets { id name age weight vaccinated status born tags owner { email } } }',
    });
    expect(result.errors).toBeUndefined();
    const pets = (result.data as { pets: Array<Record<string, unknown>> }).pets;
    expect(pets).toHaveLength(2);
    expect(pets[0]).toMatchObject({
      id: expect.stringMatching(/^id-\d+$/),
      name: 'Example text',
      age: expect.any(Number),
      weight: expect.any(Number),
      vaccinated: expect.any(Boolean),
      born: '2026-01-15T09:30:00Z',
      owner: { email: 'user@example.com' },
    });
    expect(['AVAILABLE', 'SOLD']).toContain(pets[0].status);
    expect(pets[0].tags).toEqual(['Example text', 'Example text']);
  });

  it('gives the same answer twice, and answers mutations and variables', async () => {
    const mocked = buildMockSchema(schemaOf(SDL));
    const query = 'query One($id: ID!) { pet(id: $id) { id age } }';
    const first = await executeMock(mocked, { query, variables: { id: '7' } });
    const second = await executeMock(mocked, { query, variables: { id: '7' } });
    expect(second).toEqual(first);
    const added = await executeMock(mocked, { query: 'mutation { addPet(input: { name: "Rex" }) { name } }' });
    expect(added).toEqual({ data: { addPet: { name: 'Example text' } } });
  });

  it('runs the named operation of a document with several', async () => {
    const mocked = buildMockSchema(schemaOf(SDL));
    const result = await executeMock(mocked, { query: 'query A { pets { name } } query B { pet(id: "1") { vaccinated } }', operationName: 'B' });
    expect(Object.keys(result.data ?? {})).toEqual(['pet']);
  });

  it('reports parse and validation errors, and refuses subscriptions', async () => {
    const mocked = buildMockSchema(schemaOf(SDL));
    const parseError = await executeMock(mocked, { query: '{ pets {' });
    expect(parseError.data).toBeUndefined();
    expect(parseError.errors?.[0].message).toMatch(/Syntax Error/);
    const invalid = await executeMock(mocked, { query: '{ pets { nope } }' });
    expect(invalid.errors?.[0].message).toMatch(/Cannot query field "nope"/);
    const subscription = await executeMock(mocked, { query: 'subscription { petAdded { id } }' });
    expect(subscription.errors?.[0].message).toBe(SUBSCRIPTIONS_NOT_MOCKED);
  });

  it('does not change the schema it mocks', () => {
    const schema = schemaOf(SDL);
    buildMockSchema(schema);
    expect(schema.getQueryType()!.getFields().pets.resolve).toBeUndefined();
  });
});
