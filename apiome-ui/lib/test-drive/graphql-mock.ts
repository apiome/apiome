/**
 * The GraphiQL test drive's mock data — MFX-44.3 (#4369).
 *
 * GraphiQL runs against the emitted schema with **mock resolvers** (`@graphql-tools/mock`), entirely in
 * the browser: no server, no network. Every type gets a value of the right shape — built-in scalars
 * from small deterministic sequences, enums from their values, interfaces and unions from a possible
 * type, lists of two — and each custom scalar the file declares gets a value its name suggests
 * (`DateTime` → an ISO timestamp, `UUID` → a UUID, `JSON` → an object), or a labelled string.
 *
 * The store remembers what it generated, so asking the same question twice gives the same answer.
 * Subscriptions are not mocked: the fetcher says so instead of hanging.
 */

import { addMocksToSchema, type IMocks } from '@graphql-tools/mock';
import {
  execute,
  getOperationAST,
  parse,
  validate,
  type DocumentNode,
  type ExecutionResult,
  type GraphQLSchema,
} from 'graphql';

import { isCustomScalarName } from './graphql-sdl';

/** What GraphiQL sends the fetcher. */
export interface MockGraphQLParams {
  /** The document text. */
  query: string;
  /** The operation to run, when the document holds several. */
  operationName?: string | null;
  /** The variables, as GraphiQL parsed them. */
  variables?: Record<string, unknown> | null;
}

/** The answer the fetcher gives for a subscription. */
export const SUBSCRIPTIONS_NOT_MOCKED = 'Subscriptions are not mocked in the test drive. Try a query or a mutation.';

/**
 * Custom scalars recognized by name, first match wins. Each pattern is tried against the scalar's
 * name; the value is what the mock returns for it.
 */
export const CUSTOM_SCALAR_MOCKS: ReadonlyArray<{ pattern: RegExp; value: () => unknown }> = [
  { pattern: /date.?time|timestamp|instant/i, value: () => '2026-01-15T09:30:00Z' },
  { pattern: /date/i, value: () => '2026-01-15' },
  { pattern: /time/i, value: () => '09:30:00' },
  { pattern: /uuid|guid/i, value: () => '6f1c2a4e-8b3d-4f5a-9c7e-2d1b0a3f4e5c' },
  { pattern: /url|uri|link/i, value: () => 'https://example.com/resource' },
  { pattern: /e.?mail/i, value: () => 'user@example.com' },
  { pattern: /phone/i, value: () => '+1-555-0100' },
  { pattern: /json|object|map|any|struct/i, value: () => ({ example: true }) },
  { pattern: /big.?int|long|int64|uint/i, value: () => 9_007_199_254 },
  { pattern: /decimal|double|float|money|amount|price/i, value: () => 12.5 },
  { pattern: /int/i, value: () => 42 },
  { pattern: /byte|base64|binary|upload|file|blob/i, value: () => 'aGVsbG8=' },
  { pattern: /bool/i, value: () => true },
];

/**
 * The mock for one custom scalar.
 *
 * @param name The scalar's name.
 * @returns A value its name suggests, or `"<Name> mock"`.
 */
export function customScalarMock(name: string): unknown {
  const match = CUSTOM_SCALAR_MOCKS.find((entry) => entry.pattern.test(name));
  return match ? match.value() : `${name} mock`;
}

/**
 * Mocks for every scalar the schema has: deterministic sequences for the built-ins, and a value per
 * custom scalar (the mock engine refuses a custom scalar it has no mock for).
 *
 * @param schema The schema to mock.
 * @returns The mock map for `addMocksToSchema`.
 */
export function scalarMocks(schema: GraphQLSchema): IMocks {
  let int = 0;
  let float = 0;
  let id = 0;
  let bool = false;
  const mocks: IMocks = {
    Int: () => (int += 1),
    Float: () => Math.round((float += 1.25) * 100) / 100,
    String: () => 'Example text',
    Boolean: () => (bool = !bool),
    ID: () => `id-${(id += 1)}`,
  };
  for (const name of Object.keys(schema.getTypeMap())) {
    if (isCustomScalarName(schema, name)) mocks[name] = () => customScalarMock(name);
  }
  return mocks;
}

/**
 * The schema with mock resolvers on every field.
 *
 * @param schema A valid schema (from `readGraphQLSdl`).
 * @returns A new, executable schema; the input is not changed.
 */
export function buildMockSchema(schema: GraphQLSchema): GraphQLSchema {
  return addMocksToSchema({ schema, mocks: scalarMocks(schema) });
}

/** A GraphQL error result with one message. */
function failure(message: string): ExecutionResult {
  return { errors: [{ message }] } as unknown as ExecutionResult;
}

/**
 * Run one GraphiQL request against the mock schema.
 *
 * @param mocked The schema from {@link buildMockSchema}.
 * @param params The query, operation name and variables.
 * @returns The execution result: mock data, or the parse / validation errors.
 */
export async function executeMock(mocked: GraphQLSchema, params: MockGraphQLParams): Promise<ExecutionResult> {
  let document: DocumentNode;
  try {
    document = parse(params.query);
  } catch (error) {
    return failure(error instanceof Error ? error.message : String(error));
  }
  const errors = validate(mocked, document);
  if (errors.length > 0) return { errors } as ExecutionResult;
  const operationName = params.operationName || undefined;
  if (getOperationAST(document, operationName)?.operation === 'subscription') return failure(SUBSCRIPTIONS_NOT_MOCKED);
  return execute({ schema: mocked, document, operationName, variableValues: params.variables ?? undefined });
}
