/**
 * GraphQL SDL import — types as classes, directives as `x-graphql-directive` (REPO-3.6, #2775).
 *
 * The project import path converts SDL to OpenAPI (`graphql-converter.ts`) and the OpenAPI importer turns each
 * schema into an Apiome class. These tests pin the three acceptance criteria end to end:
 *
 * 1. every `type` / `input` / `enum` / `interface` / `union` becomes a class, with the metadata of its kind;
 * 2. every applied directive — on a type, a field or an enum value — is kept: `x-graphql-directive`
 *    (`[{ name, arguments? }]`) on the class schema and on the property, and
 *    `x-graphql-enum-value-directives` on an enum schema;
 * 3. a semantic round trip on a subset of GitHub's public schema
 *    (`fixtures/graphql/github-schema-subset.graphql`): what the classes carry equals the schema's types,
 *    fields and directives, argument by argument.
 */

import { describe, expect, it } from '@jest/globals';
import * as fs from 'fs';
import * as path from 'path';
import {
  GRAPHQL_DIRECTIVE_EXTENSION,
  GRAPHQL_ENUM_VALUE_DIRECTIVES_EXTENSION,
  convertGraphQLToOpenAPI,
} from '../src/app/utils/graphql-converter';
import { openApiImporter } from '../lib/importers/openapi';

const SUBSET = fs.readFileSync(path.join(__dirname, 'fixtures/graphql/github-schema-subset.graphql'), 'utf-8');
const GITHUB_STYLE = path.join(__dirname, '../examples/graphql/11-github-style-api.graphql');

type Directive = { name: string; arguments?: Record<string, unknown> };

function convert(sdl: string) {
  const result = convertGraphQLToOpenAPI(sdl);
  expect(result.success).toBe(true);
  return result.document;
}

/** The OpenAPI document as Apiome classes, every schema selected — the import's own step. */
function importClasses(sdl: string) {
  const document = convert(sdl);
  const schemas = Object.keys(document.components.schemas);
  const result = openApiImporter.normalize({ document, options: { selectedSchemas: schemas } });
  return Object.fromEntries(result.classes.map((cls) => [cls.originalSchemaKey ?? cls.name, cls]));
}

function propertyOf(cls: { properties?: Array<{ name: string; data?: Record<string, unknown> }> }, name: string) {
  const prop = (cls.properties ?? []).find((p) => p.name === name);
  expect(prop).toBeDefined();
  return prop!.data ?? {};
}

describe('every type kind becomes a class (#2775 AC 1)', () => {
  it('imports each type, input, enum, interface and union of the subset as a class', () => {
    const classes = importClasses(SUBSET);
    expect(Object.keys(classes).sort()).toEqual(
      ['CreateIssueInput', 'DateTime', 'Issue', 'IssueState', 'Node', 'Repository', 'SearchResultItem'].sort(),
    );
  });

  it('carries the metadata of each kind', () => {
    const classes = importClasses(SUBSET);
    expect(classes.Node.schema['x-graphql-interface']).toBe(true);
    expect(classes.IssueState.schema.enum).toEqual(['OPEN', 'CLOSED', 'ARCHIVED']);
    expect(classes.SearchResultItem.schema.oneOf).toEqual([
      { $ref: '#/components/schemas/Issue' },
      { $ref: '#/components/schemas/Repository' },
    ]);
    expect(classes.Issue.schema.allOf[0]).toEqual({ $ref: '#/components/schemas/Node' });
    expect(classes.CreateIssueInput.properties.map((p) => p.name)).toEqual(['repositoryId', 'title']);
    // A well-known scalar maps to its OpenAPI type (custom scalars are tagged `x-graphql-scalar`).
    expect(classes.DateTime.schema.format).toBe('date-time');
  });

  it('imports every type of the GitHub-style corpus schema as a class', () => {
    const sdl = fs.readFileSync(GITHUB_STYLE, 'utf-8');
    // The root operation types are operations, not data: the converter leaves them out by design.
    const declared = Array.from(sdl.matchAll(/^\s*(?:type|input|enum|interface|union|scalar)\s+(\w+)/gm), (m) => m[1])
      .filter((name) => !['Query', 'Mutation', 'Subscription'].includes(name));
    expect(declared.length).toBeGreaterThan(5);
    const classes = importClasses(sdl);
    for (const name of new Set(declared)) {
      expect(classes[name]).toBeDefined();
    }
  });
});

describe('applied directives are kept as x-graphql-directive (#2775 AC 2)', () => {
  it('keeps a type directive on the class schema, arguments typed', () => {
    const classes = importClasses(SUBSET);
    expect(classes.Issue.schema[GRAPHQL_DIRECTIVE_EXTENSION]).toEqual([
      { name: 'key', arguments: { fields: 'id, number' } },
    ]);
    expect(classes.CreateIssueInput.schema[GRAPHQL_DIRECTIVE_EXTENSION]).toEqual([
      { name: 'oneField', arguments: { required: false } },
    ]);
  });

  it('keeps an interface, union and scalar directive, with list arguments as written', () => {
    const classes = importClasses(SUBSET);
    expect(classes.Node.schema[GRAPHQL_DIRECTIVE_EXTENSION]).toEqual([
      { name: 'possibleTypes', arguments: { concreteTypes: '["Issue", "Repository"]', abstractType: 'Node' } },
    ]);
    expect(classes.SearchResultItem.schema[GRAPHQL_DIRECTIVE_EXTENSION]).toEqual([
      { name: 'possibleTypes', arguments: { concreteTypes: '["Issue", "Repository"]' } },
    ]);
    expect(classes.DateTime.schema[GRAPHQL_DIRECTIVE_EXTENSION]).toEqual([
      { name: 'specifiedBy', arguments: { url: 'https://tools.ietf.org/html/rfc3339' } },
    ]);
  });

  it('keeps field directives on the property, several in order, with @ and ) inside a string', () => {
    const classes = importClasses(SUBSET);
    expect(propertyOf(classes.Issue, 'lastEditedAt')[GRAPHQL_DIRECTIVE_EXTENSION]).toEqual([
      { name: 'deprecated', arguments: { reason: 'Use `updatedAt` (it covers @mentions, too).' } },
    ]);
    expect(propertyOf(classes.Issue, 'isPinned')[GRAPHQL_DIRECTIVE_EXTENSION]).toEqual([
      { name: 'preview', arguments: { toggledBy: 'elektra-preview' } },
      { name: 'cost', arguments: { complexity: 2, multipliers: '["first", "last"]', enabled: true } },
    ]);
    expect(propertyOf(classes.CreateIssueInput, 'title')[GRAPHQL_DIRECTIVE_EXTENSION]).toEqual([
      { name: 'length', arguments: { max: 256 } },
    ]);
  });

  it('keeps the field type when a directive follows it', () => {
    const classes = importClasses(SUBSET);
    expect(propertyOf(classes.Issue, 'isPinned').type).toBe('boolean');
    expect(propertyOf(classes.CreateIssueInput, 'title').type).toBe('string');
    expect(classes.CreateIssueInput.schema.required).toEqual(['repositoryId', 'title']);
  });

  it('maps enum value directives under x-graphql-enum-value-directives', () => {
    const classes = importClasses(SUBSET);
    expect(classes.IssueState.schema[GRAPHQL_ENUM_VALUE_DIRECTIVES_EXTENSION]).toEqual({
      ARCHIVED: [{ name: 'deprecated', arguments: { reason: 'Use CLOSED with a stateReason instead.' } }],
    });
  });

  it('writes no extension for a construct without directives', () => {
    const classes = importClasses(SUBSET);
    expect(classes.Repository.schema[GRAPHQL_DIRECTIVE_EXTENSION]).toBeUndefined();
    expect(propertyOf(classes.Issue, 'title')[GRAPHQL_DIRECTIVE_EXTENSION]).toBeUndefined();
    expect(convert('enum Plain { A B }').components.schemas.Plain[GRAPHQL_ENUM_VALUE_DIRECTIVES_EXTENSION])
      .toBeUndefined();
  });

  it('keeps a directive with no arguments without an arguments key', () => {
    const doc = convert('type Thing @shareable {\n  id: ID! @external\n}\n');
    expect(doc.components.schemas.Thing[GRAPHQL_DIRECTIVE_EXTENSION]).toEqual([{ name: 'shareable' }]);
    expect(doc.components.schemas.Thing.properties.id[GRAPHQL_DIRECTIVE_EXTENSION]).toEqual([{ name: 'external' }]);
  });
});

describe('semantic round trip on a GitHub schema subset (#2775 AC 3)', () => {
  /** What the subset declares: each construct and its applied directives, as the schema author wrote them. */
  const EXPECTED: Record<string, { directives: Directive[]; fields?: Record<string, Directive[]> }> = {
    Node: {
      directives: [{ name: 'possibleTypes', arguments: { concreteTypes: '["Issue", "Repository"]', abstractType: 'Node' } }],
      fields: { id: [] },
    },
    Issue: {
      directives: [{ name: 'key', arguments: { fields: 'id, number' } }],
      fields: {
        id: [], number: [], title: [], state: [],
        lastEditedAt: [{ name: 'deprecated', arguments: { reason: 'Use `updatedAt` (it covers @mentions, too).' } }],
        isPinned: [
          { name: 'preview', arguments: { toggledBy: 'elektra-preview' } },
          { name: 'cost', arguments: { complexity: 2, multipliers: '["first", "last"]', enabled: true } },
        ],
      },
    },
    Repository: { directives: [], fields: { id: [], name: [], issueCount: [] } },
    SearchResultItem: { directives: [{ name: 'possibleTypes', arguments: { concreteTypes: '["Issue", "Repository"]' } }] },
    CreateIssueInput: {
      directives: [{ name: 'oneField', arguments: { required: false } }],
      fields: { repositoryId: [], title: [{ name: 'length', arguments: { max: 256 } }] },
    },
    IssueState: { directives: [] },
    DateTime: { directives: [{ name: 'specifiedBy', arguments: { url: 'https://tools.ietf.org/html/rfc3339' } }] },
  };

  it('reads back, from the imported classes, every construct, field and directive the schema declares', () => {
    const classes = importClasses(SUBSET);
    const readBack = Object.fromEntries(
      Object.entries(classes).map(([name, cls]) => {
        const fields = (cls.properties ?? []).length
          ? Object.fromEntries(cls.properties.map((p) => [p.name, (p.data?.[GRAPHQL_DIRECTIVE_EXTENSION] as Directive[]) ?? []]))
          : undefined;
        // An interface-implementing type keeps its own fields in the last `allOf` member.
        return [name, { directives: cls.schema[GRAPHQL_DIRECTIVE_EXTENSION] ?? [], ...(fields ? { fields } : {}) }];
      }),
    );
    expect(readBack).toEqual(EXPECTED);
  });
});
