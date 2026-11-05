/**
 * Reading an emitted GraphQL SDL file for the GraphiQL test drive — MFX-44.3 (#4369).
 *
 * Shared by the Studio (which shows a notice instead of GraphiQL when the file cannot be read) and the
 * sandboxed GraphiQL page (which builds its mock from the same schema). It depends on `graphql` alone,
 * so the Studio does not carry GraphiQL or the mock engine.
 *
 * The SDL is read leniently about *applied* directives the file does not declare (federation's `@key`,
 * `@link` imports…), which a schema explorer does not need; anything else that makes the schema
 * invalid — a syntax error, an unknown type, a broken interface — is reported.
 */

import {
  buildASTSchema,
  getNamedType,
  isEnumType,
  isInputObjectType,
  isInterfaceType,
  isLeafType,
  isListType,
  isNonNullType,
  isObjectType,
  isScalarType,
  parse,
  validateSchema,
  type GraphQLArgument,
  type GraphQLField,
  type GraphQLInputType,
  type GraphQLSchema,
} from 'graphql';

/** How many fields the example query selects at most. */
export const EXAMPLE_QUERY_MAX_FIELDS = 6;

/** The first line of every example query: GraphiQL's answers are not real data. */
export const MOCK_DATA_COMMENT = '# Mock data: answered in your browser from this schema.';

/** What the schema declares, for the note above GraphiQL. */
export interface GraphQLSchemaSummary {
  /** Named types the file declares (introspection and built-in scalars excluded). */
  types: number;
  /** Fields on the query root. */
  queries: number;
  /** Fields on the mutation root (0 when there is none). */
  mutations: number;
  /** Fields on the subscription root (0 when there is none). */
  subscriptions: number;
}

/** The outcome of reading an emitted file as GraphQL SDL. */
export type GraphQLSdlResult =
  | { ok: true; schema: GraphQLSchema; summary: GraphQLSchemaSummary }
  | { ok: false; error: string };

/** The built-in scalars, which every schema has and no file declares. */
const BUILT_IN_SCALARS = new Set(['String', 'Int', 'Float', 'Boolean', 'ID']);

/**
 * Read SDL into an executable-shaped schema.
 *
 * @param sdl The emitted file's text.
 * @returns The schema and what it declares, or why it cannot be explored.
 */
export function readGraphQLSdl(sdl: string): GraphQLSdlResult {
  if (!sdl.trim()) return { ok: false, error: 'The file is empty, so there is no GraphQL schema to explore.' };
  let schema: GraphQLSchema;
  try {
    // `assumeValidSDL` skips the SDL-level rules (undeclared applied directives, mostly); a reference to
    // a type the file does not define still throws here, and `validateSchema` catches the rest.
    schema = buildASTSchema(parse(sdl), { assumeValidSDL: true });
  } catch (error) {
    return { ok: false, error: `The file is not valid GraphQL SDL: ${error instanceof Error ? error.message : String(error)}` };
  }
  const errors = validateSchema(schema);
  if (errors.length > 0) {
    // Includes a schema with no Query type ("Query root type must be provided.").
    return { ok: false, error: `The GraphQL schema is not valid: ${errors.map((e) => e.message).join(' ')}` };
  }
  return { ok: true, schema, summary: summarizeSchema(schema) };
}

/**
 * Count what a schema declares.
 *
 * @param schema A valid schema.
 * @returns Its type and root-field counts.
 */
export function summarizeSchema(schema: GraphQLSchema): GraphQLSchemaSummary {
  const types = Object.keys(schema.getTypeMap()).filter((name) => !name.startsWith('__') && !BUILT_IN_SCALARS.has(name));
  const count = (root: { getFields(): Record<string, unknown> } | null | undefined) => (root ? Object.keys(root.getFields()).length : 0);
  return {
    types: types.length,
    queries: count(schema.getQueryType()),
    mutations: count(schema.getMutationType()),
    subscriptions: count(schema.getSubscriptionType()),
  };
}

/**
 * A literal for a required argument of the example query.
 *
 * @param type The argument's input type.
 * @returns A GraphQL literal, or null when the type is an input object (the field is then skipped).
 */
export function placeholderLiteral(type: GraphQLInputType): string | null {
  if (isNonNullType(type)) return placeholderLiteral(type.ofType);
  if (isListType(type)) {
    const item = placeholderLiteral(type.ofType);
    return item === null ? null : `[${item}]`;
  }
  if (isEnumType(type)) return type.getValues()[0]?.name ?? null;
  if (isInputObjectType(type)) return null;
  switch (type.name) {
    case 'Int':
      return '1';
    case 'Float':
      return '1.5';
    case 'Boolean':
      return 'true';
    default:
      return '"example"';
  }
}

/** The required arguments of a field as `(a: 1, b: "example")`, or null when one cannot be written. */
function requiredArguments(args: readonly GraphQLArgument[]): string | null {
  const required = args.filter((arg) => isNonNullType(arg.type) && arg.defaultValue === undefined);
  const written: string[] = [];
  for (const arg of required) {
    const literal = placeholderLiteral(arg.type);
    if (literal === null) return null;
    written.push(`${arg.name}: ${literal}`);
  }
  return written.length ? `(${written.join(', ')})` : '';
}

/** The selection set for a field's return type: its leaf fields, or `__typename`. */
function selectionFor(field: GraphQLField<unknown, unknown>): string {
  const named = getNamedType(field.type);
  if (isLeafType(named)) return '';
  if (!isObjectType(named) && !isInterfaceType(named)) return ' {\n    __typename\n  }';
  const leaves = Object.values(named.getFields())
    .filter((child) => isLeafType(getNamedType(child.type)) && requiredArguments(child.args) === '')
    .slice(0, EXAMPLE_QUERY_MAX_FIELDS)
    .map((child) => child.name);
  const lines = leaves.length ? leaves : ['__typename'];
  return ` {\n${lines.map((name) => `    ${name}`).join('\n')}\n  }`;
}

/**
 * A first query for GraphiQL's editor: one query-root field with its leaf fields.
 *
 * Prefers the first field with no required argument; otherwise the first whose required arguments are
 * scalars or enums, filled with placeholders.
 *
 * @param schema A valid schema.
 * @returns The query, headed by {@link MOCK_DATA_COMMENT}.
 */
export function exampleQuery(schema: GraphQLSchema): string {
  const fields = Object.values(schema.getQueryType()?.getFields() ?? {});
  const candidates = fields
    .map((field) => ({ field, args: requiredArguments(field.args) }))
    .filter((entry): entry is { field: GraphQLField<unknown, unknown>; args: string } => entry.args !== null);
  const chosen = candidates.find((entry) => entry.args === '') ?? candidates[0];
  if (!chosen) return `${MOCK_DATA_COMMENT}\nquery Example {\n  __typename\n}\n`;
  return `${MOCK_DATA_COMMENT}\nquery Example {\n  ${chosen.field.name}${chosen.args}${selectionFor(chosen.field)}\n}\n`;
}

/** Whether a named type is a custom scalar the file declares (and so needs its own mock). */
export function isCustomScalarName(schema: GraphQLSchema, name: string): boolean {
  const type = schema.getType(name);
  return Boolean(type && isScalarType(type) && !BUILT_IN_SCALARS.has(name));
}
