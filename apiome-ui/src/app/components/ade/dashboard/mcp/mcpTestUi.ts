/**
 * Pure model for the MCP endpoint **Test** tab (V2-MCP-22.4 / V2-MCP-24.5, #3690 / #3701).
 *
 * The tab invokes one discovered tool against the live server through the test harness
 * (`POST /api/mcp/endpoints/{id}/test` → apiome-rest `POST /v1/mcp/{tenant}/endpoints/{id}/test`,
 * MCAT-8.2). Everything here is React-free so it can be unit-tested on its own:
 *
 * - {@link mcpTestableTools} — the tools a picker offers;
 * - {@link mcpToolArgumentFields} — one form field per `inputSchema` property;
 * - {@link mcpBuildToolArguments} — the typed `arguments` object, or per-field errors;
 * - {@link mcpToolConfirmHints} — the hints that make the server demand `confirm: true`;
 * - {@link mcpTestResultFromPayload} / {@link mcpTestOutcome} — the response, classified.
 */

import type { McpCapabilityItem } from './mcpBrowseUi';

/** How a schema property is edited in the form. */
export type McpArgumentKind = 'string' | 'number' | 'integer' | 'boolean' | 'enum' | 'json';

/** One argument field derived from a tool's `inputSchema`. */
export interface McpArgumentField {
  /** The property name (the key sent in `arguments`). */
  name: string;
  /** What the reader sees: the property `title`, else its name. */
  label: string;
  kind: McpArgumentKind;
  required: boolean;
  description: string | null;
  /** The allowed values of an `enum` property, as strings for the picker. */
  enumValues: string[];
  /** The raw JSON values behind {@link enumValues}, in the same order. */
  enumRaw: unknown[];
}

/** The editable form state: text for every kind except `boolean`. */
export type McpArgumentValues = Record<string, string | boolean>;

/** The result of turning form values into a call's `arguments`. */
export interface McpBuiltArguments {
  arguments: Record<string, unknown>;
  /** Per-field validation messages, keyed by property name. Empty when the form is valid. */
  errors: Record<string, string>;
}

/** The annotation hints that make the server refuse a call without `confirm: true` (MCAT-8.3). */
export const MCP_CONFIRM_HINTS: ReadonlyArray<{ key: string; label: string }> = [
  { key: 'destructiveHint', label: 'destructive' },
  { key: 'openWorldHint', label: 'open-world' },
];

/** The REST status a destructive / open-world tool returns when sent without confirm. */
export const MCP_TEST_CONFIRM_REQUIRED_STATUS = 428;

/** A test-harness response (`McpEndpointTestResponse`). */
export interface McpTestResult {
  itemName: string;
  method: string;
  target: string;
  completed: boolean;
  isError: boolean;
  content: unknown[];
  structuredContent: Record<string, unknown> | null;
  latencyMs: number;
  error: { code: string | null; message: string | null } | null;
  invocationId: string | null;
}

/** The three outcomes a call can end in. */
export type McpTestOutcomeKind = 'ok' | 'tool-error' | 'failed';

/** An outcome plus the badge status and label it renders with. */
export interface McpTestOutcome {
  kind: McpTestOutcomeKind;
  label: string;
  status: 'ok' | 'degraded' | 'failed';
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

/**
 * The tools a test can target, in their discovered order. Resources, templates and prompts are
 * left out: the Test tab invokes tools (`tools/call`).
 *
 * @param items The version snapshot's capability items, or `null` before load.
 * @returns The tool items, sorted by `ordinal`.
 */
export function mcpTestableTools(
  items: readonly McpCapabilityItem[] | null | undefined,
): McpCapabilityItem[] {
  return (items ?? [])
    .filter((item) => item.item_type === 'tool')
    .sort((a, b) => a.ordinal - b.ordinal);
}

/** Pick the form kind for one schema property. */
function argumentKind(schema: Record<string, unknown>): McpArgumentKind {
  if (Array.isArray(schema.enum) && schema.enum.length > 0) return 'enum';
  // A union type (`["string", "null"]`) edits as its first non-null member.
  const declared = Array.isArray(schema.type)
    ? schema.type.find((t) => t !== 'null')
    : schema.type;
  if (declared === 'string' || declared === 'number' || declared === 'integer' || declared === 'boolean') {
    return declared;
  }
  // Objects, arrays, and schemas without a simple type are edited as raw JSON.
  return 'json';
}

/**
 * Derive one form field per top-level property of a tool's `inputSchema`, in declaration order.
 * Strings, numbers, integers and booleans get typed inputs; `enum`s a picker; anything else
 * (objects, arrays, untyped) a JSON text box.
 *
 * @param inputSchema The tool's JSON Schema, or `null` when it declares none.
 * @returns The fields; empty for a tool that takes no arguments.
 */
export function mcpToolArgumentFields(
  inputSchema: Record<string, unknown> | null | undefined,
): McpArgumentField[] {
  if (!isRecord(inputSchema) || !isRecord(inputSchema.properties)) return [];
  const required = new Set(
    Array.isArray(inputSchema.required)
      ? inputSchema.required.filter((name): name is string => typeof name === 'string')
      : [],
  );
  return Object.entries(inputSchema.properties).map(([name, raw]) => {
    const schema = isRecord(raw) ? raw : {};
    const kind = argumentKind(schema);
    const enumRaw = kind === 'enum' ? (schema.enum as unknown[]) : [];
    return {
      name,
      label: typeof schema.title === 'string' && schema.title.trim() ? schema.title : name,
      kind,
      required: required.has(name),
      description: typeof schema.description === 'string' ? schema.description : null,
      enumValues: enumRaw.map((value) => (typeof value === 'string' ? value : JSON.stringify(value))),
      enumRaw,
    };
  });
}

/**
 * The starting form values: each property's schema `default` when it has one, else blank
 * (`false` for a boolean).
 *
 * @param fields The fields from {@link mcpToolArgumentFields}.
 * @param inputSchema The same schema, read for `default`s.
 * @returns One value per field.
 */
export function mcpInitialArgumentValues(
  fields: readonly McpArgumentField[],
  inputSchema: Record<string, unknown> | null | undefined,
): McpArgumentValues {
  const properties =
    isRecord(inputSchema) && isRecord(inputSchema.properties) ? inputSchema.properties : {};
  const values: McpArgumentValues = {};
  for (const field of fields) {
    const schema = isRecord(properties[field.name]) ? (properties[field.name] as Record<string, unknown>) : {};
    const fallback = schema.default;
    if (field.kind === 'boolean') {
      values[field.name] = fallback === true;
    } else if (fallback === undefined) {
      values[field.name] = '';
    } else if (field.kind === 'json') {
      values[field.name] = JSON.stringify(fallback, null, 2);
    } else if (field.kind === 'enum') {
      const index = field.enumRaw.findIndex((value) => JSON.stringify(value) === JSON.stringify(fallback));
      values[field.name] = index >= 0 ? field.enumValues[index] : '';
    } else {
      values[field.name] = String(fallback);
    }
  }
  return values;
}

/**
 * Turn the form values into the call's `arguments`, typed per field. A blank optional field is
 * left out; a blank required field, a non-numeric number, a non-whole integer and invalid JSON
 * are reported per field. A boolean is always sent. The server still validates the result against
 * the full `inputSchema` (422 on mismatch), so this only catches what the form can see.
 *
 * @param fields The fields from {@link mcpToolArgumentFields}.
 * @param values The current form values.
 * @returns The `arguments` object and any per-field errors.
 */
export function mcpBuildToolArguments(
  fields: readonly McpArgumentField[],
  values: McpArgumentValues,
): McpBuiltArguments {
  const args: Record<string, unknown> = {};
  const errors: Record<string, string> = {};
  for (const field of fields) {
    const value = values[field.name];
    if (field.kind === 'boolean') {
      args[field.name] = value === true;
      continue;
    }
    const text = typeof value === 'string' ? value.trim() : '';
    if (text === '') {
      if (field.required) errors[field.name] = `${field.label} is required.`;
      continue;
    }
    if (field.kind === 'number' || field.kind === 'integer') {
      const parsed = Number(text);
      if (!Number.isFinite(parsed)) {
        errors[field.name] = `${field.label} must be a number.`;
      } else if (field.kind === 'integer' && !Number.isInteger(parsed)) {
        errors[field.name] = `${field.label} must be a whole number.`;
      } else {
        args[field.name] = parsed;
      }
    } else if (field.kind === 'enum') {
      const index = field.enumValues.indexOf(text);
      args[field.name] = index >= 0 ? field.enumRaw[index] : text;
    } else if (field.kind === 'json') {
      try {
        args[field.name] = JSON.parse(text);
      } catch {
        errors[field.name] = `${field.label} must be valid JSON.`;
      }
    } else {
      // Strings are sent as typed (untrimmed): leading/trailing spaces may be meaningful.
      args[field.name] = value;
    }
  }
  return { arguments: args, errors };
}

/**
 * The confirm-gate hints a tool asserts (`destructiveHint` / `openWorldHint` set to `true`). A
 * non-empty result means the server refuses the call unless the request sets `confirm: true`; a
 * hint that is absent or not a clean boolean is not a gate (mirrors the REST check).
 *
 * @param item The tool, or `null`.
 * @returns The labels of the asserted hints (e.g. `["destructive"]`).
 */
export function mcpToolConfirmHints(item: McpCapabilityItem | null | undefined): string[] {
  const annotations = item?.annotations;
  if (!isRecord(annotations)) return [];
  return MCP_CONFIRM_HINTS.filter(({ key }) => annotations[key] === true).map(({ label }) => label);
}

/**
 * Read a test-harness response, tolerating missing fields.
 *
 * @param data The parsed JSON body.
 * @returns The typed result, or `null` when the body is not an object.
 */
export function mcpTestResultFromPayload(data: unknown): McpTestResult | null {
  if (!isRecord(data)) return null;
  const error = isRecord(data.error)
    ? {
        code: typeof data.error.code === 'string' ? data.error.code : null,
        message: typeof data.error.message === 'string' ? data.error.message : null,
      }
    : null;
  return {
    itemName: typeof data.itemName === 'string' ? data.itemName : '',
    method: typeof data.method === 'string' ? data.method : '',
    target: typeof data.target === 'string' ? data.target : '',
    completed: data.completed === true,
    isError: data.isError === true,
    content: Array.isArray(data.content) ? data.content : [],
    structuredContent: isRecord(data.structuredContent) ? data.structuredContent : null,
    latencyMs: typeof data.latencyMs === 'number' ? data.latencyMs : 0,
    error,
    invocationId: typeof data.invocationId === 'string' ? data.invocationId : null,
  };
}

/**
 * Classify a result: the tool ran and succeeded, ran and reported `isError`, or the call failed
 * before a result came back (transport / JSON-RPC error).
 *
 * @param result The test result.
 * @returns The outcome with its badge status and label.
 */
export function mcpTestOutcome(result: McpTestResult): McpTestOutcome {
  if (!result.completed) return { kind: 'failed', label: 'Call failed', status: 'failed' };
  if (result.isError) return { kind: 'tool-error', label: 'Tool error', status: 'degraded' };
  return { kind: 'ok', label: 'Succeeded', status: 'ok' };
}

/**
 * The one-line result summary the mockup draws: `142 ms · isError: false`.
 *
 * @param result The test result.
 * @returns The summary text.
 */
export function mcpTestSummaryLine(result: McpTestResult): string {
  return `${Math.round(result.latencyMs)} ms · isError: ${result.isError}`;
}

/**
 * Whether a content item is plain text (`{type: 'text', text}`), shown verbatim rather than as JSON.
 *
 * @param item One returned content item.
 * @returns `true` for a text item.
 */
export function mcpTestIsTextContent(item: unknown): boolean {
  return isRecord(item) && item.type === 'text' && typeof item.text === 'string';
}

/**
 * The text a content item shows: a `text` item's text, anything else as pretty JSON.
 *
 * @param item One returned content item.
 * @returns What to render.
 */
export function mcpTestContentText(item: unknown): string {
  if (mcpTestIsTextContent(item)) return (item as { text: string }).text;
  return JSON.stringify(item, null, 2);
}

/**
 * Whether the endpoint has no stored credential (its credential status is `none`), so a test
 * runs anonymously. An unknown status (`null`, not loaded) is not reported as missing.
 *
 * @param authType The `auth_type` from the redacted credential status, or `null` when unknown.
 * @returns `true` only for an explicit `none`.
 */
export function mcpTestCredentialMissing(authType: string | null | undefined): boolean {
  return (authType ?? '').trim().toLowerCase() === 'none';
}
