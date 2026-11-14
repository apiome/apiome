"""The fixed TypeScript of the generated MCP server — SDK-4.5 (#4499).

:mod:`app.mcp_server_generator` writes one generated module per contract (``src/contract.ts``: the
server's identity, its tools with their input schemas and HTTP bindings, its security schemes) next
to the files held here, which are the same for every contract:

* ``src/types.ts`` — the schema subset, the binding and the tool/auth table shapes;
* ``src/validate.ts`` — a JSON-Schema validator for the keyword subset the compiler emits
  (:data:`app.mcp_tool_mapping.MCP_SCHEMA_KEYWORDS`), so bad arguments are refused before a request;
* ``src/request.ts`` — arguments → request, a port of ``apiome_mcp.agent_request_builder`` (the
  managed proxy's serializer) over the same :func:`app.mcp_operation_binding.binding_for` table;
* ``src/config.ts`` — base URL, extra headers and credentials, from environment variables only;
* ``src/handlers.ts`` — ``tools/list`` and ``tools/call``;
* ``src/server.ts`` — the only file that imports the MCP SDK: a stdio server over the handlers.

Everything but ``server.ts`` imports nothing outside the project, so this repository's gate can
type-check and *run* the core without installing the SDK.

**Why a call layer of its own.** SDK-4.5 was scoped on the SDK-2.1 TypeScript client, which was
closed not-planned; the request builder here is that client's job, kept small and generic rather
than one method per operation, because an MCP tool call already arrives as name + JSON arguments.
"""

from __future__ import annotations

from typing import Dict

__all__ = [
    "MCP_SDK_VERSION",
    "NODE_ENGINE",
    "RUNTIME_FILES",
    "TYPESCRIPT_VERSION",
    "ZOD_VERSION",
    "NODE_TYPES_VERSION",
]

#: The ``@modelcontextprotocol/sdk`` release the server is written and checked against.
MCP_SDK_VERSION = "1.32.2"

#: ``zod`` — a peer dependency of the MCP SDK, so the generated project declares it.
ZOD_VERSION = "3.25.76"

#: The TypeScript compiler range the project builds with.
TYPESCRIPT_VERSION = "5.9.3"

#: ``@types/node``, for ``process`` and the global ``fetch``.
NODE_TYPES_VERSION = "20.19.0"

#: The Node.js the server runs on: 20 or later (global ``fetch``, ``AbortSignal.timeout``).
NODE_ENGINE = ">=20"

#: ``src/types.ts`` — The shared types: the schema subset, the binding, the tool and auth tables.
TYPES_TS = r'''/** A JSON Schema node, in the portable subset every generated tool input schema uses. */
export interface Schema {
  type?: string | string[];
  enum?: unknown[];
  anyOf?: Schema[];
  properties?: Record<string, Schema>;
  required?: string[];
  additionalProperties?: boolean | Schema;
  minProperties?: number;
  maxProperties?: number;
  items?: Schema;
  minItems?: number;
  maxItems?: number;
  uniqueItems?: boolean;
  minLength?: number;
  maxLength?: number;
  pattern?: string;
  format?: string;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
  multipleOf?: number;
  title?: string;
  description?: string;
  default?: unknown;
  examples?: unknown[];
  [keyword: string]: unknown;
}

/** Where one argument goes and how it is serialized (OpenAPI `style` / `explode`). */
export interface ParameterBinding {
  name: string;
  location: "path" | "query" | "header";
  style: string;
  explode: boolean;
  allowReserved: boolean;
  required: boolean;
}

/** Everything needed to turn one tool's arguments into an HTTP request. */
export interface OperationBinding {
  /** The upper-case HTTP method. */
  method: string;
  /** The operation path, with `{name}` placeholders. */
  path: string;
  /** The non-body arguments, in declaration order. */
  parameters: ParameterBinding[];
  /** `none`, `flat` (body properties are top-level arguments) or `nested` (under `body`). */
  bodyMode: "none" | "flat" | "nested";
  bodyRequired: boolean;
  bodyMediaType: string | null;
  /** The `Accept` header: the success response's media type, when the contract states it. */
  accept: string | null;
}

/** One MCP tool: what an agent sees, and the operation it calls. */
export interface ToolEntry {
  name: string;
  description?: string;
  inputSchema: Schema & { type: "object" };
  /** The contract operation the tool calls (`GET /pets/{petId}`). */
  operation: string;
  binding: OperationBinding;
}

/** One security scheme, configured from environment variables. */
export interface AuthEntry {
  /** The scheme's name in the contract. */
  scheme: string;
  kind: "bearer" | "basic" | "api_key";
  /** Where the credential travels. */
  location: "header" | "query" | "cookie";
  /** The header, query parameter or cookie name. */
  parameter: string;
  /** The environment variables it reads: one, or `[username, password]` for Basic. */
  env: string[];
}

/** One problem with the arguments a caller sent. */
export interface Issue {
  /** Where: an argument name, a path into it (`tags[0]`), or `(arguments)`. */
  argument: string;
  problem: string;
}

/** Arguments that cannot become a request. Nothing is sent. */
export class InvalidArgumentsError extends Error {
  readonly issues: Issue[];

  constructor(issues: Issue[]) {
    super(issues.map((issue) => `${issue.argument}: ${issue.problem}`).join("; "));
    this.name = "InvalidArgumentsError";
    this.issues = issues;
  }
}
'''

#: ``src/validate.ts`` — The input-schema validator every call goes through before anything is sent.
VALIDATE_TS = r'''import type { Issue, Schema } from "./types.js";

/** The name the argument object itself is reported under. */
const ROOT = "(arguments)";

/**
 * Check `value` against a tool's input schema.
 *
 * Covers every keyword the generated schemas carry: `type`, `enum`, `anyOf`, the object, array,
 * string and number constraints. `format` is an annotation and is not enforced; a `pattern` this
 * runtime cannot compile is skipped rather than rejecting every value.
 *
 * @param schema The schema to check against.
 * @param value The value a caller sent.
 * @param at Where `value` sits, for the issue text (the root by default).
 * @returns Every problem found; empty when the value conforms.
 */
export function validate(schema: Schema, value: unknown, at: string = ROOT): Issue[] {
  const issues: Issue[] = [];
  check(schema, value, at, issues);
  return issues;
}

function check(schema: Schema, value: unknown, at: string, issues: Issue[]): void {
  if (schema.anyOf && schema.anyOf.length > 0) {
    const matched = schema.anyOf.some((branch) => validate(branch, value, at).length === 0);
    if (!matched) {
      issues.push({ argument: at, problem: "does not match any of the allowed shapes" });
      return;
    }
  }
  if (schema.type !== undefined) {
    const allowed = Array.isArray(schema.type) ? schema.type : [schema.type];
    if (!allowed.some((type) => isType(type, value))) {
      issues.push({ argument: at, problem: `must be ${allowed.map(article).join(" or ")}, not ${describe(value)}` });
      return;
    }
  }
  if (schema.enum && !schema.enum.some((option) => same(option, value))) {
    issues.push({
      argument: at,
      problem: `must be one of ${schema.enum.map((option) => JSON.stringify(option)).join(", ")}`,
    });
    return;
  }
  if (typeof value === "string") {
    checkString(schema, value, at, issues);
  } else if (typeof value === "number") {
    checkNumber(schema, value, at, issues);
  } else if (Array.isArray(value)) {
    checkArray(schema, value, at, issues);
  } else if (isObject(value)) {
    checkObject(schema, value, at, issues);
  }
}

function checkString(schema: Schema, value: string, at: string, issues: Issue[]): void {
  const length = [...value].length;
  if (schema.minLength !== undefined && length < schema.minLength) {
    issues.push({ argument: at, problem: `must be at least ${schema.minLength} characters long` });
  }
  if (schema.maxLength !== undefined && length > schema.maxLength) {
    issues.push({ argument: at, problem: `must be at most ${schema.maxLength} characters long` });
  }
  if (schema.pattern !== undefined) {
    const pattern = compile(schema.pattern);
    if (pattern && !pattern.test(value)) {
      issues.push({ argument: at, problem: `must match the pattern ${schema.pattern}` });
    }
  }
}

function checkNumber(schema: Schema, value: number, at: string, issues: Issue[]): void {
  if (schema.minimum !== undefined && value < schema.minimum) {
    issues.push({ argument: at, problem: `must be at least ${schema.minimum}` });
  }
  if (schema.maximum !== undefined && value > schema.maximum) {
    issues.push({ argument: at, problem: `must be at most ${schema.maximum}` });
  }
  if (typeof schema.exclusiveMinimum === "number" && value <= schema.exclusiveMinimum) {
    issues.push({ argument: at, problem: `must be greater than ${schema.exclusiveMinimum}` });
  }
  if (typeof schema.exclusiveMaximum === "number" && value >= schema.exclusiveMaximum) {
    issues.push({ argument: at, problem: `must be less than ${schema.exclusiveMaximum}` });
  }
  if (schema.multipleOf !== undefined && schema.multipleOf > 0) {
    const quotient = value / schema.multipleOf;
    if (Math.abs(quotient - Math.round(quotient)) > 1e-9) {
      issues.push({ argument: at, problem: `must be a multiple of ${schema.multipleOf}` });
    }
  }
}

function checkArray(schema: Schema, value: unknown[], at: string, issues: Issue[]): void {
  if (schema.minItems !== undefined && value.length < schema.minItems) {
    issues.push({ argument: at, problem: `must have at least ${schema.minItems} items` });
  }
  if (schema.maxItems !== undefined && value.length > schema.maxItems) {
    issues.push({ argument: at, problem: `must have at most ${schema.maxItems} items` });
  }
  if (schema.uniqueItems && new Set(value.map((item) => JSON.stringify(item))).size !== value.length) {
    issues.push({ argument: at, problem: "must not repeat an item" });
  }
  if (schema.items) {
    const items = schema.items;
    value.forEach((item, index) => check(items, item, `${at}[${index}]`, issues));
  }
}

function checkObject(schema: Schema, value: Record<string, unknown>, at: string, issues: Issue[]): void {
  const keys = Object.keys(value);
  const child = (key: string): string => (at === ROOT ? key : `${at}.${key}`);
  for (const name of schema.required ?? []) {
    if (value[name] === undefined) {
      issues.push({ argument: child(name), problem: "is required" });
    }
  }
  if (schema.minProperties !== undefined && keys.length < schema.minProperties) {
    issues.push({ argument: at, problem: `must have at least ${schema.minProperties} members` });
  }
  if (schema.maxProperties !== undefined && keys.length > schema.maxProperties) {
    issues.push({ argument: at, problem: `must have at most ${schema.maxProperties} members` });
  }
  const properties = schema.properties ?? {};
  for (const key of keys) {
    if (value[key] === undefined) {
      continue;
    }
    const declared = properties[key];
    if (declared) {
      check(declared, value[key], child(key), issues);
    } else if (schema.additionalProperties === false) {
      issues.push({ argument: child(key), problem: "is not an argument of this tool" });
    } else if (isObject(schema.additionalProperties)) {
      check(schema.additionalProperties, value[key], child(key), issues);
    }
  }
}

function isType(type: string, value: unknown): boolean {
  switch (type) {
    case "null":
      return value === null;
    case "boolean":
      return typeof value === "boolean";
    case "string":
      return typeof value === "string";
    case "integer":
      return typeof value === "number" && Number.isInteger(value);
    case "number":
      return typeof value === "number" && Number.isFinite(value);
    case "array":
      return Array.isArray(value);
    case "object":
      return isObject(value);
    default:
      return true;
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** A JSON-Schema type name with its article: `an integer`, `a string`, `null`. */
function article(type: string): string {
  if (type === "null") {
    return "null";
  }
  return /^[aeiou]/.test(type) ? `an ${type}` : `a ${type}`;
}

function describe(value: unknown): string {
  if (value === null) {
    return "null";
  }
  if (Array.isArray(value)) {
    return "an array";
  }
  if (typeof value === "number" && Number.isInteger(value)) {
    return "an integer";
  }
  return typeof value === "object" ? "an object" : `a ${typeof value}`;
}

function same(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function compile(pattern: string): RegExp | null {
  try {
    return new RegExp(pattern, "u");
  } catch {
    return null;
  }
}
'''

#: ``src/request.ts`` — Tool arguments → an HTTP request: the TypeScript twin of ``apiome_mcp.agent_request_builder``.
REQUEST_TS = r'''import { InvalidArgumentsError } from "./types.js";
import type { Issue, OperationBinding, ParameterBinding } from "./types.js";

/** A request ready to send, relative to the base URL. */
export interface HttpRequest {
  method: string;
  /** The expanded, percent-encoded path (starts with `/`). */
  path: string;
  /** Encoded `name=value` pairs, in order. */
  query: string[];
  headers: Record<string, string>;
  /** The encoded body: text, form data, or nothing. */
  body: string | FormData | null;
}

/** The argument a nested request body is sent under. */
export const BODY_ARGUMENT = "body";

/**
 * Headers an argument may never set: the HTTP client's framing headers and the credential
 * headers this server's configuration owns.
 */
const PROTECTED_HEADERS = new Set([
  "authorization",
  "connection",
  "content-length",
  "content-type",
  "cookie",
  "expect",
  "host",
  "keep-alive",
  "proxy-authorization",
  "proxy-connection",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

/** Characters `allowReserved` leaves unencoded in a query value (never `&`, `#` or `=`). */
const RESERVED_QUERY_SAFE = ":/?[]@!$'()*+,;";

/** Characters a URL never needs encoded. */
const UNRESERVED = /^[A-Za-z0-9\-._~]$/;

const TEMPLATE_VAR = /\{([^{}]+)\}/g;

/**
 * Build the HTTP request for one call, the way the contract describes it.
 *
 * Path parameters follow the OpenAPI `simple`, `label` and `matrix` styles; query parameters
 * `form`, `spaceDelimited`, `pipeDelimited` and `deepObject`; headers `simple`. Every value is
 * percent-encoded, so an argument can never add a path segment, a query parameter or a header.
 *
 * @param binding Where the tool's arguments go.
 * @param args The arguments, already checked against the tool's input schema.
 * @returns The request.
 * @throws InvalidArgumentsError A path parameter is missing, empty or a `.`/`..` segment; a
 *   header value has a line break; or a form body is not an object.
 */
export function buildRequest(binding: OperationBinding, args: Record<string, unknown>): HttpRequest {
  const issues: Issue[] = [];
  const byName = new Map(binding.parameters.map((parameter) => [parameter.name, parameter]));
  const consumed = new Set<string>();

  let path = binding.path.replace(TEMPLATE_VAR, (whole: string, name: string) => {
    consumed.add(name);
    const value = args[name];
    if (value === undefined || value === null) {
      issues.push({ argument: name, problem: "is a required path parameter" });
      return whole;
    }
    const parameter = byName.get(name) ?? {
      name,
      location: "path",
      style: "simple",
      explode: false,
      allowReserved: false,
      required: true,
    };
    const serialized = serializePath(parameter, value);
    if (serialized === "" || value === "") {
      issues.push({ argument: name, problem: "must not be empty: it is a path segment" });
    } else if (hasDotSegment(serialized)) {
      issues.push({ argument: name, problem: "must not be '.' or '..': it is a path segment" });
    }
    return serialized;
  });
  if (!path.startsWith("/")) {
    path = `/${path}`;
  }

  const query: string[] = [];
  const headers: Record<string, string> = {};
  for (const parameter of binding.parameters) {
    if (parameter.location === "path") {
      continue;
    }
    consumed.add(parameter.name);
    const value = args[parameter.name];
    if (value === undefined || value === null) {
      continue;
    }
    if (parameter.location === "query") {
      query.push(...serializeQuery(parameter, value));
      continue;
    }
    if (PROTECTED_HEADERS.has(parameter.name.toLowerCase())) {
      continue;
    }
    const text = serializeHeader(parameter, value);
    if (/[\r\n\0]/.test(text)) {
      issues.push({ argument: parameter.name, problem: "must not contain line breaks: it is an HTTP header value" });
      continue;
    }
    headers[parameter.name] = text;
  }

  let body: string | FormData | null = null;
  if (binding.bodyMode !== "none" && binding.bodyMediaType) {
    let value: unknown;
    if (binding.bodyMode === "nested") {
      value = args[BODY_ARGUMENT];
    } else {
      const fields = Object.fromEntries(Object.entries(args).filter(([key]) => !consumed.has(key)));
      value = Object.keys(fields).length > 0 || binding.bodyRequired ? fields : undefined;
    }
    if (value !== undefined && value !== null) {
      try {
        const encoded = encodeBody(binding.bodyMediaType, value);
        body = encoded.body;
        if (encoded.contentType) {
          headers["Content-Type"] = encoded.contentType;
        }
      } catch (error) {
        if (error instanceof InvalidArgumentsError) {
          issues.push(...error.issues);
        } else {
          throw error;
        }
      }
    }
  }

  if (issues.length > 0) {
    throw new InvalidArgumentsError(issues);
  }
  if (binding.accept && headers["Accept"] === undefined) {
    headers["Accept"] = binding.accept;
  }
  return { method: binding.method, path, query, headers, body };
}

/** Whether a media type is JSON (`application/json`, `…+json`, `…/json; charset=…`). */
export function isJsonMediaType(mediaType: string): boolean {
  const essence = mediaType.split(";", 1)[0]!.trim().toLowerCase();
  return essence.endsWith("/json") || essence.endsWith("+json");
}

/** Percent-encode `text` as UTF-8, leaving only unreserved characters and `safe`. */
export function encode(text: string, safe: string = ""): string {
  let out = "";
  for (const char of text) {
    if (UNRESERVED.test(char) || safe.includes(char)) {
      out += char;
      continue;
    }
    for (const byte of new TextEncoder().encode(char)) {
      out += `%${byte.toString(16).toUpperCase().padStart(2, "0")}`;
    }
  }
  return out;
}

/** One value as text: `true`/`false` for booleans, compact JSON for nested values. */
function text(value: unknown): string {
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  return JSON.stringify(value);
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function pairs(value: Record<string, unknown>): Array<[string, string]> {
  return Object.entries(value).map(([key, item]) => [key, text(item)]);
}

function serializePath(parameter: ParameterBinding, value: unknown): string {
  const { name, explode, style } = parameter;
  if (Array.isArray(value)) {
    const items = value.map((item) => encode(text(item)));
    if (style === "label") {
      return "." + items.join(explode ? "." : ",");
    }
    if (style === "matrix") {
      return explode
        ? items.map((item) => `;${encode(name)}=${item}`).join("")
        : `;${encode(name)}=` + items.join(",");
    }
    return items.join(",");
  }
  if (isObject(value)) {
    const encoded = pairs(value).map(([key, item]) => [encode(key), encode(item)] as const);
    if (style === "matrix") {
      return explode
        ? encoded.map(([key, item]) => `;${key}=${item}`).join("")
        : `;${encode(name)}=` + encoded.map(([key, item]) => `${key},${item}`).join(",");
    }
    const joined = encoded
      .map(([key, item]) => (explode ? `${key}=${item}` : `${key},${item}`))
      .join(style === "label" && explode ? "." : ",");
    return style === "label" ? `.${joined}` : joined;
  }
  const single = encode(text(value));
  if (style === "label") {
    return `.${single}`;
  }
  if (style === "matrix") {
    return `;${encode(name)}=${single}`;
  }
  return single;
}

function serializeQuery(parameter: ParameterBinding, value: unknown): string[] {
  const safe = parameter.allowReserved ? RESERVED_QUERY_SAFE : "";
  const name = encode(parameter.name);
  const enc = (raw: string): string => encode(raw, safe);
  if (Array.isArray(value)) {
    const items = value.map((item) => enc(text(item)));
    if (parameter.style === "form" && parameter.explode) {
      return items.map((item) => `${name}=${item}`);
    }
    const separators: Record<string, string> = { spaceDelimited: "%20", pipeDelimited: "|", tabDelimited: "%09" };
    return [`${name}=` + items.join(separators[parameter.style] ?? ",")];
  }
  if (isObject(value)) {
    const entries = pairs(value);
    if (parameter.style === "deepObject") {
      return entries.map(([key, item]) => `${name}%5B${encode(key)}%5D=${enc(item)}`);
    }
    if (parameter.style === "form" && parameter.explode) {
      return entries.map(([key, item]) => `${encode(key)}=${enc(item)}`);
    }
    return [`${name}=` + entries.map(([key, item]) => `${enc(key)},${enc(item)}`).join(",")];
  }
  return [`${name}=${enc(text(value))}`];
}

function serializeHeader(parameter: ParameterBinding, value: unknown): string {
  if (Array.isArray(value)) {
    return value.map((item) => text(item)).join(",");
  }
  if (isObject(value)) {
    return pairs(value)
      .map(([key, item]) => (parameter.explode ? `${key}=${item}` : `${key},${item}`))
      .join(",");
  }
  return text(value);
}

function hasDotSegment(serialized: string): boolean {
  const isDot = (part: string): boolean => part === "." || part === "..";
  return isDot(serialized) || serialized.split(/[;,=]/).some(isDot);
}

function encodeBody(mediaType: string, value: unknown): { body: string | FormData; contentType: string | null } {
  const essence = mediaType.split(";", 1)[0]!.trim().toLowerCase();
  if (isJsonMediaType(mediaType)) {
    return { body: JSON.stringify(value), contentType: mediaType };
  }
  if (essence === "application/x-www-form-urlencoded" || essence === "multipart/form-data") {
    if (!isObject(value)) {
      const problem = `must be an object of form fields for ${essence}`;
      throw new InvalidArgumentsError([{ argument: BODY_ARGUMENT, problem }]);
    }
    if (essence === "multipart/form-data") {
      const form = new FormData();
      for (const [key, item] of Object.entries(value)) {
        for (const element of Array.isArray(item) ? item : [item]) {
          form.append(key, text(element));
        }
      }
      // fetch writes the multipart Content-Type itself, boundary included.
      return { body: form, contentType: null };
    }
    const fields: string[] = [];
    for (const [key, item] of Object.entries(value)) {
      for (const element of Array.isArray(item) ? item : [item]) {
        fields.push(`${encode(key)}=${encode(text(element))}`);
      }
    }
    return { body: fields.join("&"), contentType: mediaType };
  }
  return { body: typeof value === "string" ? value : JSON.stringify(value), contentType: mediaType };
}
'''

#: ``src/config.ts`` — Base URL, extra headers and credentials, read from environment variables.
CONFIG_TS = r'''import { AUTH, DEFAULT_BASE_URL, ENV, USER_AGENT } from "./contract.js";
import { encode } from "./request.js";
import type { AuthEntry } from "./types.js";

/** What every request carries, read once from the environment at start-up. */
export interface Config {
  /** The API's base URL, without a trailing slash. */
  baseUrl: string;
  /** Headers sent on every request: the user agent, extra headers and header credentials. */
  headers: Record<string, string>;
  /** Encoded `name=value` pairs added to every request (query-parameter API keys). */
  query: string[];
  /** `name=value` cookies sent on every request (cookie API keys). */
  cookies: string[];
  /** The security schemes whose credentials were found in the environment. */
  schemes: string[];
}

/** The environment cannot be turned into a configuration; the server does not start. */
export class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConfigError";
  }
}

/**
 * Read the configuration from environment variables. Credentials are never part of the
 * generated code: each security scheme reads its own variables (see `.env.example`), and a scheme
 * whose variables are unset is simply not sent — the API answers the call as unauthenticated.
 *
 * @param env The environment (`process.env`).
 * @returns The configuration.
 * @throws ConfigError There is no base URL, it is not an http(s) URL, or the extra-headers
 *   variable is not a JSON object of strings.
 */
export function loadConfig(env: Record<string, string | undefined>): Config {
  const baseUrl = (env[ENV.baseUrl] || DEFAULT_BASE_URL || "").trim().replace(/\/+$/, "");
  if (!baseUrl) {
    throw new ConfigError(`Set ${ENV.baseUrl} to the API's base URL.`);
  }
  if (!/^https?:\/\//i.test(baseUrl)) {
    throw new ConfigError(`${ENV.baseUrl} must be an http:// or https:// URL.`);
  }

  const config: Config = { baseUrl, headers: { "User-Agent": USER_AGENT }, query: [], cookies: [], schemes: [] };
  Object.assign(config.headers, extraHeaders(env[ENV.headers]));
  for (const entry of AUTH) {
    const values = entry.env.map((name) => env[name]);
    if (values.some((value) => !value)) {
      continue;
    }
    apply(config, entry, credential(entry, values as string[]));
    config.schemes.push(entry.scheme);
  }
  return config;
}

/** Parse the extra-headers variable: a JSON object such as `{"X-Mock-Session": "demo"}`. */
function extraHeaders(raw: string | undefined): Record<string, string> {
  if (!raw || !raw.trim()) {
    return {};
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new ConfigError(`${ENV.headers} must be a JSON object, such as {"X-Request-Source": "mcp"}.`);
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new ConfigError(`${ENV.headers} must be a JSON object of header names to values.`);
  }
  const headers: Record<string, string> = {};
  for (const [name, value] of Object.entries(parsed)) {
    if (typeof value !== "string" || /[\r\n\0]/.test(value)) {
      throw new ConfigError(`${ENV.headers}: the value of ${name} must be a single-line string.`);
    }
    headers[name] = value;
  }
  return headers;
}

/** The credential value a scheme sends, from its environment variables. */
function credential(entry: AuthEntry, values: string[]): string {
  if (entry.kind === "bearer") {
    return `Bearer ${values[0]}`;
  }
  if (entry.kind === "basic") {
    const bytes = new TextEncoder().encode(`${values[0]}:${values[1]}`);
    return `Basic ${btoa(String.fromCharCode(...bytes))}`;
  }
  return values[0]!;
}

/** Put one credential where its scheme says it travels. */
function apply(config: Config, entry: AuthEntry, value: string): void {
  if (entry.location === "query") {
    config.query.push(`${encode(entry.parameter)}=${encode(value)}`);
  } else if (entry.location === "cookie") {
    config.cookies.push(`${entry.parameter}=${encodeURIComponent(value)}`);
  } else {
    config.headers[entry.parameter] = value;
  }
}
'''

#: ``src/handlers.ts`` — ``tools/list`` and ``tools/call``, dependency-free.
HANDLERS_TS = r'''import type { Config } from "./config.js";
import { TOOLS } from "./contract.js";
import { buildRequest, isJsonMediaType } from "./request.js";
import { InvalidArgumentsError } from "./types.js";
import type { Issue, ToolEntry } from "./types.js";
import { validate } from "./validate.js";

/** How long one API call may take, in milliseconds. */
export const REQUEST_TIMEOUT_MS = 30_000;

/** How much of a response body a tool result carries, in characters. */
export const MAX_RESULT_CHARS = 100_000;

/** What `tools/list` answers with, per tool. */
export interface ToolListing {
  name: string;
  description?: string;
  inputSchema: { type: "object"; [keyword: string]: unknown };
}

/** What `tools/call` answers with. */
export interface CallResult {
  [key: string]: unknown;
  content: Array<{ type: "text"; text: string }>;
  isError?: boolean;
}

/** The slice of `fetch` a call needs, so a test can pass its own. */
export type Fetch = (url: string, init: FetchInit) => Promise<FetchResponse>;

/** What a call hands `fetch`. */
export interface FetchInit {
  method: string;
  headers: Record<string, string>;
  body?: string | FormData;
  signal?: AbortSignal;
}

/** What a call reads back from `fetch`. */
export interface FetchResponse {
  status: number;
  statusText: string;
  headers: { get(name: string): string | null };
  text(): Promise<string>;
}

const BY_NAME = new Map<string, ToolEntry>(TOOLS.map((tool) => [tool.name, tool]));

/**
 * The tools this server offers: one per contract operation.
 *
 * @returns The listings, in contract order.
 */
export function listTools(): ToolListing[] {
  return TOOLS.map((tool) => {
    const listing: ToolListing = { name: tool.name, inputSchema: tool.inputSchema };
    if (tool.description) {
      listing.description = tool.description;
    }
    return listing;
  });
}

/**
 * Call one tool: check the arguments against its input schema, send the request, and answer with
 * the response body. Arguments that do not fit the schema are refused **before** anything is sent.
 *
 * @param name The tool name.
 * @param args The arguments the caller sent.
 * @param config The configuration (base URL, credentials).
 * @param fetchImpl The HTTP client (the global `fetch` by default).
 * @returns The result. `isError` is set for a refused call, a failed request or an HTTP error status.
 */
export async function callTool(
  name: string,
  args: unknown,
  config: Config,
  fetchImpl: Fetch = fetch,
): Promise<CallResult> {
  const tool = BY_NAME.get(name);
  if (!tool) {
    return failure(`Unknown tool: ${name}.`);
  }
  const input = args ?? {};
  const issues = validate(tool.inputSchema, input);
  if (issues.length > 0) {
    return refused(issues);
  }

  let request;
  try {
    request = buildRequest(tool.binding, input as Record<string, unknown>);
  } catch (error) {
    if (error instanceof InvalidArgumentsError) {
      return refused(error.issues);
    }
    throw error;
  }

  const query = [...request.query, ...config.query];
  const url = config.baseUrl + request.path + (query.length > 0 ? `?${query.join("&")}` : "");
  const headers: Record<string, string> = { ...request.headers, ...config.headers };
  if (config.cookies.length > 0) {
    headers["Cookie"] = config.cookies.join("; ");
  }
  const init: FetchInit = { method: request.method, headers, signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) };
  if (request.body !== null) {
    init.body = request.body;
  }

  let response;
  let body;
  try {
    response = await fetchImpl(url, init);
    body = await response.text();
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    return failure(`${tool.binding.method} ${tool.binding.path} failed: ${reason}`);
  }

  const text = present(body, response.headers.get("content-type"));
  if (response.status >= 400) {
    return failure(`HTTP ${response.status} ${response.statusText}`.trim() + (text ? `\n${text}` : ""));
  }
  return { content: [{ type: "text", text: text || `HTTP ${response.status} ${response.statusText}`.trim() }] };
}

/** A response body as tool text: pretty-printed when it is JSON, cut at `MAX_RESULT_CHARS`. */
function present(body: string, contentType: string | null): string {
  let text = body;
  if (contentType && isJsonMediaType(contentType) && body.trim()) {
    try {
      text = JSON.stringify(JSON.parse(body), null, 2);
    } catch {
      text = body;
    }
  }
  if (text.length > MAX_RESULT_CHARS) {
    return `${text.slice(0, MAX_RESULT_CHARS)}\n… (truncated: the response was ${text.length} characters)`;
  }
  return text;
}

function refused(issues: Issue[]): CallResult {
  const lines = issues.map((issue) => `- ${issue.argument}: ${issue.problem}`);
  return failure(`Invalid arguments — nothing was sent:\n${lines.join("\n")}`);
}

function failure(text: string): CallResult {
  return { content: [{ type: "text", text }], isError: true };
}
'''

#: ``src/server.ts`` — The MCP SDK wiring: a stdio ``Server`` that delegates to the handlers.
SERVER_TS = r'''#!/usr/bin/env node
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";

import { ConfigError, loadConfig } from "./config.js";
import { SERVER } from "./contract.js";
import { callTool, listTools } from "./handlers.js";

/** Start the server on stdio: an MCP client launches this process and talks to it over stdin/stdout. */
async function main(): Promise<void> {
  const config = loadConfig(process.env);
  const server = new Server(
    { name: SERVER.name, title: SERVER.title, version: SERVER.version },
    { capabilities: { tools: {} } },
  );
  server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: listTools() }));
  server.setRequestHandler(CallToolRequestSchema, async (request) =>
    callTool(request.params.name, request.params.arguments, config),
  );
  await server.connect(new StdioServerTransport());
  // stdout is the protocol channel; anything for a person goes to stderr.
  console.error(`${SERVER.name} ${SERVER.version}: ${listTools().length} tools, calling ${config.baseUrl}`);
}

main().catch((error: unknown) => {
  console.error(error instanceof ConfigError ? error.message : error);
  process.exit(1);
});
'''

#: Every fixed file, by its path in the project.
RUNTIME_FILES: Dict[str, str] = {
    "src/types.ts": TYPES_TS,
    "src/validate.ts": VALIDATE_TS,
    "src/request.ts": REQUEST_TS,
    "src/config.ts": CONFIG_TS,
    "src/handlers.ts": HANDLERS_TS,
    "src/server.ts": SERVER_TS,
}
