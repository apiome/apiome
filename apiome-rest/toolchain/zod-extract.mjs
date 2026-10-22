#!/usr/bin/env node
/**
 * Zod schema and tRPC router extractor (FMT-8.2, #5463; FMT-8.3, #5464).
 *
 * Reads a JSON request from STDIN — one TypeScript module, or a set of modules that import one
 * another — **evaluates** it, and writes the module's exported Zod schemas to STDOUT as one JSON
 * Schema (draft 2020-12) document. With `"routers": true` it also walks every exported tRPC
 * router and reports each procedure's path, kind, input and output (FMT-8.3):
 *
 *   request:  { "files": { "<name>.ts": "<source>", ... }, "root": "<name>.ts", "budgetMs": 5000,
 *               "routers": false }
 *
 *   response: {
 *     "ok":                boolean,
 *     "zodVersion":        string,
 *     "typescriptVersion": string,
 *     "root":              string,
 *     "files":             [string],
 *     "exports":           [string],          // the root's exported Zod schemas, in export order
 *     "schema":            { "$schema", "$defs": { "<name>": <JSON Schema> } } | null,
 *     "routers":           [ { "name", "procedures": [ { "path", "type", "inputs", "output",
 *                                                     "meta" } ], "lazy": [path] } ],
 *     "diagnostics":       [ { "file", "code", "message", "line", "column", "atEnd" } ],
 *     "error":             { "code", "message", "module"? } | null
 *   }
 *
 * A procedure's `inputs` holds one JSON Schema node per `.input()` call (tRPC merges chained
 * inputs); `output` is the `.output()` schema, or `null`. A validator that is not a Zod schema —
 * a hand-written function — has no schema to extract and is reported as
 * `{ "x-trpc-unsupported": "trpc.non_schema_input" }` (or `…_output`). Resolvers are never
 * called, so a procedure's body, its `TRPCError`s and the context its middleware derives are not
 * read at all.
 *
 * Each schema is serialized from Zod's introspectable `_def` tree (Zod 3), not from a type
 * checker: a Zod schema is a *value*, and only running the module produces it. A reference to
 * another exported schema — the root's, or one a sibling module exports — becomes a `$ref` to
 * its `$defs` entry, which is also how `z.lazy` recursion terminates.
 *
 * Constructs with no JSON Schema analogue are never dropped and never widened silently:
 *
 *   * a construct that still has a modellable shape (a `refine` on an object, a `transform` on a
 *     string, a `brand`, a `pipe`, a `preprocess`, a coercion) keeps that shape and lists itself
 *     in the vendor keyword `x-zod-limits`;
 *   * a construct with no shape at all (`z.function()`, `z.promise()`, `z.custom()`, `never`,
 *     `symbol`, `NaN`) is replaced by `{ "x-zod-unsupported": "<construct>" }`.
 *
 * ## The execution boundary
 *
 * Evaluating a module is running user code, so it happens behind three walls:
 *
 *   1. **Node's permission model.** The script re-executes itself under `--permission` with read
 *      access to its own directory only: no file outside the toolchain, no child process, no
 *      worker, no native addon — even for code that escapes the `vm` context below (and escaping
 *      it is easy: any host object, Zod included, leads back to the host `Function`).
 *   2. **A `vm` context with a time budget.** Modules are transpiled to CommonJS by the bundled
 *      `typescript` and run in a fresh context whose `require` serves `zod` and the request's own
 *      modules and nothing else. Every evaluation runs against one deadline (`budgetMs`), with
 *      microtasks included, so an infinite loop fails as `TIME_LIMIT` within budget.
 *   3. **No network, no environment.** Node's permission model does not cover sockets, so the
 *      network modules and `fetch` are disabled in-process before any user code runs — in
 *      addition to the network namespace the Python toolchain runner launches every tool in. The
 *      child starts with an empty environment, so escaped code finds no secrets in `process.env`.
 *
 * Reading the schemas runs user code too (a `z.lazy` getter, a `.default()` factory), so the
 * serialization is itself a `vm` task with its own budget: an endless getter fails as
 * `TIME_LIMIT` the same way an endless import does.
 *
 * The process exits 0 on every handled outcome (a syntax error, a module that throws, a module
 * that runs out of time). A non-zero exit is reserved for a wrapper failure.
 */

import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const SCRIPT_PATH = fileURLToPath(import.meta.url);
const SCRIPT_DIR = path.dirname(SCRIPT_PATH);
const require = createRequire(import.meta.url);

/** The time budget for evaluating the whole module set, when the request names none. */
const DEFAULT_BUDGET_MS = 5000;

/** Module extensions a relative import may omit, tried in order. */
const RESOLVE_SUFFIXES = ['', '.ts', '.tsx', '.mts', '.cts', '.d.ts', '/index.ts', '/index.tsx'];

/** Zod entry points this reader evaluates (the Zod 3 API). */
const ZOD_V3_SPECIFIERS = new Set(['zod', 'zod/v3']);

/** Zod entry points for a different major API, which this reader declines by name. */
const ZOD_OTHER_SPECIFIERS = new Set(['zod/v4', 'zod/mini', 'zod/v4-mini', 'zod/v4/core']);

/** tRPC server entry points a router module may import, served only in `routers` mode. */
const TRPC_SPECIFIERS = new Set(['@trpc/server', '@trpc/server/observable']);

/** An error the extractor raises on purpose, carrying the outcome code the response reports. */
class ExtractError extends Error {
  constructor(code, message, extra = {}) {
    super(message);
    this.code = code;
    Object.assign(this, extra);
  }
}

// ---------------------------------------------------------------------------------------
// Entry: version probe, permission re-exec, request handling
// ---------------------------------------------------------------------------------------

function printVersionAndExit() {
  const zodVersion = require('zod/package.json').version;
  process.stdout.write(`zod-extract (apiome) zod ${zodVersion}\n`);
  process.exit(0);
}

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => {
      data += chunk;
    });
    process.stdin.on('end', () => resolve(data));
    process.stdin.on('error', reject);
  });
}

/**
 * Re-run this script under Node's permission model, feeding it the same request. Only the
 * toolchain directory is readable; nothing is writable; child processes, workers, addons and WASI
 * are denied. The parent never evaluates user code itself.
 */
function reexecUnderPermission(input) {
  const result = spawnSync(
    process.execPath,
    ['--permission', `--allow-fs-read=${SCRIPT_DIR}`, SCRIPT_PATH],
    // An empty environment: nothing the service was started with is visible to user code.
    { input, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, env: {} },
  );
  if (result.error) {
    throw result.error;
  }
  process.stdout.write(result.stdout ?? '');
  process.stderr.write(result.stderr ?? '');
  process.exit(result.status ?? 1);
}

/** Disable every outbound network API in this process before user code can reach it. */
function disableNetwork() {
  const refuse = () => {
    throw new Error('network access is disabled while evaluating schemas');
  };
  // Every module is loaded first and only its *functions* are replaced: the classes stay, because
  // Node's own modules extend them (tls extends net.Socket) and would fail to load otherwise.
  const net = require('net');
  const tls = require('tls');
  const http = require('http');
  const https = require('https');
  const http2 = require('http2');
  const dgram = require('dgram');
  const dns = require('dns');
  const patches = [
    [net, ['connect', 'createConnection']],
    [net.Socket.prototype, ['connect']],
    [tls, ['connect']],
    [http, ['request', 'get']],
    [https, ['request', 'get']],
    [http2, ['connect']],
    [dgram, ['createSocket']],
    [dgram.Socket.prototype, ['send', 'connect', 'bind']],
    [dns, ['lookup', 'resolve', 'resolve4', 'resolve6', 'resolveAny']],
    [dns.promises, ['lookup', 'resolve', 'resolve4', 'resolve6', 'resolveAny']],
  ];
  for (const [target, keys] of patches) {
    for (const key of keys) {
      try {
        target[key] = refuse;
      } catch {
        // A read-only export stays; the network namespace the runner launches us in still applies.
      }
    }
  }
  globalThis.fetch = refuse;
  globalThis.WebSocket = undefined;
}

// ---------------------------------------------------------------------------------------
// Transpile and evaluate
// ---------------------------------------------------------------------------------------

/** Map a TypeScript diagnostic onto the wrapper's shape (same contract as the 8.1 extractor). */
function mapDiagnostic(ts, diagnostic, fileName, text) {
  const message = ts.flattenDiagnosticMessageText(diagnostic.messageText, '\n');
  const start = diagnostic.start ?? 0;
  const sourceFile = diagnostic.file ?? ts.createSourceFile(fileName, text, ts.ScriptTarget.ES2022);
  const { line, character } = sourceFile.getLineAndCharacterOfPosition(start);
  return {
    file: fileName,
    code: diagnostic.code,
    message,
    line: line + 1,
    column: character + 1,
    // A syntax error at the very end means the text stopped while a construct was open.
    atEnd: start >= text.trimEnd().length,
  };
}

/** Transpile every module to CommonJS, collecting syntax errors instead of throwing. */
function transpileAll(ts, files) {
  const compiled = {};
  const diagnostics = [];
  for (const [name, text] of Object.entries(files)) {
    const out = ts.transpileModule(text, {
      fileName: name,
      reportDiagnostics: true,
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        esModuleInterop: true,
        isolatedModules: true,
      },
    });
    for (const diagnostic of out.diagnostics ?? []) {
      diagnostics.push(mapDiagnostic(ts, diagnostic, name, text));
    }
    compiled[name] = out.outputText;
  }
  return { compiled, diagnostics };
}

/** Resolve a relative specifier against the importing module, within the request's files. */
function resolveRelative(files, fromName, specifier) {
  const base = path.posix.normalize(path.posix.join(path.posix.dirname(fromName), specifier));
  for (const suffix of RESOLVE_SUFFIXES) {
    const candidate = base.replace(/\.js$/, '') + suffix;
    if (Object.prototype.hasOwnProperty.call(files, candidate)) {
      return candidate;
    }
  }
  return null;
}

/**
 * Evaluate the root module (and whatever it imports) in a fresh context against one deadline.
 *
 * @returns {{ exports: object, moduleExports: Array, zod: object, runBounded: Function }} the root
 *   module's exports, every evaluated module's exports (root first), the Zod they were given, and
 *   a runner that executes a task under a fresh time budget.
 */
function evaluate(files, compiled, root, budgetMs, routers = false) {
  const zod = require('zod');
  const deadline = Date.now() + budgetMs;
  const context = vm.createContext(
    { console: { log() {}, warn() {}, error() {}, info() {}, debug() {} } },
    { microtaskMode: 'afterEvaluate', codeGeneration: { strings: false, wasm: false } },
  );
  const cache = new Map();

  const load = (name) => {
    if (cache.has(name)) {
      return cache.get(name).exports;
    }
    const module = { exports: {} };
    cache.set(name, module);
    const requireFrom = (specifier) => {
      if (ZOD_V3_SPECIFIERS.has(specifier)) {
        return zod;
      }
      if (routers && TRPC_SPECIFIERS.has(specifier)) {
        return require(specifier);
      }
      if (ZOD_OTHER_SPECIFIERS.has(specifier)) {
        throw new ExtractError('ZOD_VERSION', `\`${specifier}\` is the Zod 4 API; this reader evaluates Zod 3 (\`zod\`).`, { module: specifier });
      }
      if (specifier.startsWith('.') || specifier.startsWith('/')) {
        const target = resolveRelative(files, name, specifier);
        if (target !== null) {
          return load(target);
        }
      }
      throw new ExtractError('UNRESOLVED_MODULE', `${name} imports '${specifier}', which is not part of the import.`, { module: specifier });
    };
    const remaining = deadline - Date.now();
    if (remaining <= 0) {
      throw new ExtractError('TIME_LIMIT', `Evaluating the module took longer than ${budgetMs} ms.`);
    }
    context.__apiome = { module, requireFrom, name };
    const script = new vm.Script(
      `(function (exports, require, module, __filename, __dirname) {\n${compiled[name]}\n})` +
        '.call(__apiome.module.exports, __apiome.module.exports, __apiome.requireFrom, __apiome.module, __apiome.name, ".")',
      { filename: name },
    );
    script.runInContext(context, { timeout: remaining });
    return module.exports;
  };

  try {
    const rootExports = load(root);
    const moduleExports = [...cache.entries()].map(([moduleName, module]) => [moduleName, module.exports]);
    /**
     * Run `task` (host code that may call back into user code) under a fresh deadline. The vm
     * watchdog interrupts whatever is executing once the timeout passes — a host function
     * included — so a getter that never returns cannot outlive the budget.
     */
    const runBounded = (task) => {
      context.__apiome = { task };
      try {
        return new vm.Script('__apiome.task()', { filename: 'apiome:serialize' }).runInContext(context, { timeout: budgetMs });
      } catch (err) {
        if (err && err.code === 'ERR_SCRIPT_EXECUTION_TIMEOUT') {
          throw new ExtractError('TIME_LIMIT', `Reading the schemas took longer than ${budgetMs} ms (an endless \`z.lazy\` getter?).`);
        }
        throw err;
      }
    };
    return { exports: rootExports, moduleExports, zod, runBounded };
  } catch (err) {
    if (err instanceof ExtractError) {
      throw err;
    }
    if (err && err.code === 'ERR_SCRIPT_EXECUTION_TIMEOUT') {
      throw new ExtractError('TIME_LIMIT', `Evaluating the module took longer than ${budgetMs} ms (an endless loop?).`);
    }
    const message = err && typeof err.message === 'string' ? err.message : String(err);
    throw new ExtractError('MODULE_THREW', `The module threw while it was being imported: ${message}`);
  }
}

// ---------------------------------------------------------------------------------------
// Zod `_def` → JSON Schema
// ---------------------------------------------------------------------------------------

/** Escape a literal string for use inside a regular expression. */
function escapeRegex(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** String checks that only name a format. */
const STRING_FORMATS = {
  email: 'email',
  url: 'uri',
  uuid: 'uuid',
  cuid: 'cuid',
  cuid2: 'cuid2',
  ulid: 'ulid',
  nanoid: 'nanoid',
  emoji: 'emoji',
  datetime: 'date-time',
  date: 'date',
  time: 'time',
  duration: 'duration',
  base64: 'byte',
  base64url: 'base64url',
  jwt: 'jwt',
};

/** String checks that rewrite the value rather than test it. */
const STRING_TRANSFORMS = new Set(['trim', 'toLowerCase', 'toUpperCase']);

class Serializer {
  constructor(zod, namesByValue) {
    this.z = zod;
    this.namesByValue = namesByValue;
    this.stack = [];
    this.referenced = [];
  }

  /** The names referenced since the last call, so the caller can serialize them too. */
  drainReferenced() {
    const names = this.referenced;
    this.referenced = [];
    return names;
  }

  /** Attach a declared-limit construct to a JSON Schema node. */
  limit(node, construct) {
    const limits = node['x-zod-limits'] ?? [];
    if (!limits.includes(construct)) {
      limits.push(construct);
    }
    return { ...node, 'x-zod-limits': limits };
  }

  /** A node for a construct with no data shape at all. */
  unsupported(construct, description) {
    return { 'x-zod-unsupported': construct, ...(description ? { description } : {}) };
  }

  /** Serialize one export's schema (its own `$defs` entry, so it is never a `$ref` to itself). */
  root(schema) {
    return this.walk(schema, true);
  }

  walk(schema, isRoot = false) {
    if (!(schema instanceof this.z.ZodType)) {
      return this.unsupported('zod.unrepresentable', 'not a Zod schema');
    }
    if (!isRoot && this.namesByValue.has(schema)) {
      const name = this.namesByValue.get(schema);
      this.referenced.push(name);
      return { $ref: `#/$defs/${name}` };
    }
    if (this.stack.includes(schema)) {
      // Recursion through a schema that is not exported has no name to point a `$ref` at.
      return this.unsupported('zod.unnamed_recursion', 'recursive schema that is not exported');
    }
    this.stack.push(schema);
    try {
      const node = this.node(schema);
      return schema.description ? { ...node, description: schema.description } : node;
    } finally {
      this.stack.pop();
    }
  }

  node(schema) {
    const def = schema._def;
    switch (def.typeName) {
      case 'ZodString':
        return this.string(def);
      case 'ZodNumber':
        return this.number(def);
      case 'ZodBigInt':
        return this.coerced(def, this.numericChecks({ type: 'integer', format: 'int64' }, def.checks ?? []));
      case 'ZodBoolean':
        return this.coerced(def, { type: 'boolean' });
      case 'ZodDate':
        return this.coerced(def, { type: 'string', format: 'date-time' });
      case 'ZodNull':
        return { type: 'null' };
      case 'ZodUndefined':
      case 'ZodVoid':
        return { type: 'null', 'x-zod-type': 'undefined' };
      case 'ZodAny':
        return {};
      case 'ZodUnknown':
        return { 'x-zod-type': 'unknown' };
      case 'ZodNever':
      case 'ZodNaN':
      case 'ZodSymbol':
        return this.unsupported('zod.unrepresentable', def.typeName.replace('Zod', '').toLowerCase());
      case 'ZodLiteral':
        return { const: def.value };
      case 'ZodEnum':
        return { type: 'string', enum: [...def.values] };
      case 'ZodNativeEnum':
        return this.nativeEnum(def.values);
      case 'ZodObject':
        return this.object(schema, def);
      case 'ZodArray':
        return this.array(def);
      case 'ZodTuple':
        return {
          type: 'array',
          prefixItems: def.items.map((item) => this.walk(item)),
          items: def.rest ? this.walk(def.rest) : false,
        };
      case 'ZodSet': {
        const node = { type: 'array', uniqueItems: true, items: this.walk(def.valueType) };
        if (def.minSize) node.minItems = def.minSize.value;
        if (def.maxSize) node.maxItems = def.maxSize.value;
        return node;
      }
      case 'ZodMap':
        return { type: 'object', 'x-zod-type': 'map', propertyNames: this.walk(def.keyType), additionalProperties: this.walk(def.valueType) };
      case 'ZodRecord':
        return { type: 'object', propertyNames: this.walk(def.keyType), additionalProperties: this.walk(def.valueType) };
      case 'ZodUnion':
        return { anyOf: def.options.map((option) => this.walk(option)) };
      case 'ZodDiscriminatedUnion':
        return { oneOf: [...def.options].map((option) => this.walk(option)), 'x-zod-discriminator': def.discriminator };
      case 'ZodIntersection':
        return { allOf: [this.walk(def.left), this.walk(def.right)] };
      case 'ZodOptional':
      case 'ZodNullable':
        return { anyOf: [this.walk(def.innerType), { type: 'null' }] };
      case 'ZodDefault': {
        const node = this.walk(def.innerType);
        const value = safeDefault(def.defaultValue);
        return value === undefined ? node : { ...node, default: value };
      }
      case 'ZodCatch':
      case 'ZodReadonly':
        return this.walk(def.innerType);
      case 'ZodLazy':
        return this.walk(def.getter());
      case 'ZodEffects':
        return this.effects(def);
      case 'ZodBranded':
        return this.limit(this.walk(def.type), 'zod.brand');
      case 'ZodPipeline':
        return this.limit(this.walk(def.in), 'zod.pipe');
      case 'ZodFunction':
        return this.unsupported('zod.function', 'function schema');
      case 'ZodPromise':
        return this.unsupported('zod.promise', 'promise schema');
      default:
        return this.unsupported('zod.unrepresentable', def.typeName ?? 'unknown Zod type');
    }
  }

  coerced(def, node) {
    return def.coerce ? this.limit(node, 'zod.coerce') : node;
  }

  string(def) {
    let node = { type: 'string' };
    const patterns = [];
    let transformed = false;
    for (const check of def.checks ?? []) {
      switch (check.kind) {
        case 'min':
          node.minLength = check.value;
          break;
        case 'max':
          node.maxLength = check.value;
          break;
        case 'length':
          node.minLength = check.value;
          node.maxLength = check.value;
          break;
        case 'regex':
          patterns.push(check.regex.source);
          break;
        case 'startsWith':
          patterns.push(`^${escapeRegex(check.value)}`);
          break;
        case 'endsWith':
          patterns.push(`${escapeRegex(check.value)}$`);
          break;
        case 'includes':
          patterns.push(escapeRegex(check.value));
          break;
        case 'ip':
          node.format = check.version === 'v6' ? 'ipv6' : 'ipv4';
          break;
        case 'cidr':
          node.format = check.version === 'v6' ? 'cidrv6' : 'cidrv4';
          break;
        default:
          if (check.kind in STRING_FORMATS) {
            node.format = STRING_FORMATS[check.kind];
          } else if (STRING_TRANSFORMS.has(check.kind)) {
            transformed = true;
          }
      }
    }
    if (patterns.length === 1) {
      node.pattern = patterns[0];
    } else if (patterns.length > 1) {
      // JSON Schema holds one pattern; every one must match, so they become lookaheads.
      node.pattern = `^${patterns.map((p) => `(?=${p.startsWith('^') ? p.slice(1) : `[\\s\\S]*?(?:${p})`})`).join('')}`;
      node['x-zod-patterns'] = patterns;
    }
    node = this.coerced(def, node);
    return transformed ? this.limit(node, 'zod.transform') : node;
  }

  number(def) {
    const isInt = (def.checks ?? []).some((check) => check.kind === 'int');
    return this.coerced(def, this.numericChecks({ type: isInt ? 'integer' : 'number' }, def.checks ?? []));
  }

  numericChecks(node, checks) {
    for (const check of checks) {
      const value = typeof check.value === 'bigint' ? Number(check.value) : check.value;
      if (check.kind === 'min') {
        node[check.inclusive ? 'minimum' : 'exclusiveMinimum'] = value;
      } else if (check.kind === 'max') {
        node[check.inclusive ? 'maximum' : 'exclusiveMaximum'] = value;
      } else if (check.kind === 'multipleOf') {
        node.multipleOf = value;
      }
    }
    return node;
  }

  nativeEnum(values) {
    // A TypeScript numeric enum object maps both ways; keep only the forward keys' values.
    const forward = Object.keys(values).filter((key) => typeof values[values[key]] !== 'number');
    const members = forward.map((key) => values[key]);
    const allStrings = members.every((value) => typeof value === 'string');
    return { ...(allStrings ? { type: 'string' } : {}), enum: members };
  }

  object(schema, def) {
    const shape = def.shape();
    const properties = {};
    const required = [];
    for (const [key, value] of Object.entries(shape)) {
      let property = value;
      // An optional property is "not required", not "may be null": unwrap it here so the use
      // site records optionality, as JSON Schema does.
      if (property instanceof this.z.ZodOptional) {
        properties[key] = this.walk(property._def.innerType);
      } else {
        properties[key] = this.walk(property);
        if (!property.isOptional()) {
          required.push(key);
        }
      }
    }
    const node = { type: 'object', properties };
    if (required.length) {
      node.required = required;
    }
    const catchall = def.catchall;
    if (catchall && !(catchall instanceof this.z.ZodNever)) {
      node.additionalProperties = this.walk(catchall);
    } else if (def.unknownKeys === 'strict') {
      node.additionalProperties = false;
    } else if (def.unknownKeys === 'passthrough') {
      node.additionalProperties = true;
    }
    return node;
  }

  array(def) {
    const node = { type: 'array', items: this.walk(def.type) };
    if (def.minLength) node.minItems = def.minLength.value;
    if (def.maxLength) node.maxItems = def.maxLength.value;
    if (def.exactLength) {
      node.minItems = def.exactLength.value;
      node.maxItems = def.exactLength.value;
    }
    return node;
  }

  effects(def) {
    const effect = def.effect ?? {};
    const inner = def.schema;
    if (effect.type === 'refinement' && inner instanceof this.z.ZodAny) {
      // `z.custom()` is a predicate over `any`: there is no structure to model at all.
      return this.unsupported('zod.custom', 'custom predicate');
    }
    const construct = { refinement: 'zod.refine', transform: 'zod.transform', preprocess: 'zod.preprocess' }[effect.type] ?? 'zod.refine';
    return this.limit(this.walk(inner), construct);
  }
}

/** A default value, when it is plain JSON; a default computed by a function stays unrecorded. */
function safeDefault(factory) {
  try {
    const value = factory();
    return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
  } catch {
    return undefined;
  }
}

// ---------------------------------------------------------------------------------------
// tRPC routers (FMT-8.3)
// ---------------------------------------------------------------------------------------

/** Whether a value is a tRPC router (v10/v11: `_def.router === true` plus a procedure map). */
function isRouter(value) {
  return Boolean(value && value._def && value._def.router === true && value._def.procedures);
}

/** Meta a procedure declares with `.meta()`, kept only when it is plain JSON. */
function plainMeta(meta) {
  if (meta === undefined || meta === null) {
    return null;
  }
  try {
    return JSON.parse(JSON.stringify(meta));
  } catch {
    return null;
  }
}

/** Serialize one validator: a Zod schema through the serializer, anything else as a marker. */
function serializeParser(serializer, zod, parser, construct) {
  if (parser instanceof zod.ZodType) {
    return serializer.walk(parser);
  }
  const description = typeof parser === 'function' ? 'validator function' : `${typeof parser} validator`;
  return { 'x-trpc-unsupported': construct, description };
}

/** Describe one router: every procedure (by its full dotted path) and its lazy sub-routers. */
function describeRouter(serializer, zod, name, router) {
  const procedures = Object.entries(router._def.procedures)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([path, procedure]) => {
      const def = procedure._def ?? {};
      return {
        path,
        type: def.type ?? 'query',
        inputs: (def.inputs ?? []).map((parser) => serializeParser(serializer, zod, parser, 'trpc.non_schema_input')),
        output: def.output === undefined ? null : serializeParser(serializer, zod, def.output, 'trpc.non_schema_output'),
        meta: plainMeta(def.meta),
      };
    });
  return { name, procedures, lazy: Object.keys(router._def.lazy ?? {}).sort() };
}

// ---------------------------------------------------------------------------------------
// Request
// ---------------------------------------------------------------------------------------

function extract(request) {
  const ts = require('typescript');
  const zodVersion = require('zod/package.json').version;
  const files = request.files ?? {};
  const names = Object.keys(files).sort();
  const root = request.root && names.includes(request.root) ? request.root : names[0];
  const budgetMs = Number.isFinite(request.budgetMs) && request.budgetMs > 0 ? request.budgetMs : DEFAULT_BUDGET_MS;
  const routers = request.routers === true;
  const response = {
    ok: false,
    zodVersion,
    typescriptVersion: ts.version,
    root,
    files: names,
    exports: [],
    schema: null,
    routers: [],
    diagnostics: [],
    error: null,
  };

  const { compiled, diagnostics } = transpileAll(ts, files);
  if (diagnostics.length) {
    response.diagnostics = diagnostics;
    return response;
  }

  let evaluated;
  try {
    evaluated = evaluate(files, compiled, root, budgetMs, routers);
  } catch (err) {
    if (err instanceof ExtractError) {
      response.error = { code: err.code, message: err.message, ...(err.module ? { module: err.module } : {}) };
      return response;
    }
    throw err;
  }

  const { exports: rootExports, moduleExports, zod, runBounded } = evaluated;
  // Every schema any module exports has a name; the root's names win a collision, and a clash
  // between two siblings is suffixed. Only the root's exports are the model's surface — a
  // sibling's export becomes a `$defs` entry the first time something refers to it.
  const namesByValue = new Map();
  const taken = new Set();
  const rootNames = [];
  for (const [moduleName, exported] of [[root, rootExports], ...moduleExports.filter(([name]) => name !== root)]) {
    for (const [name, value] of Object.entries(exported ?? {})) {
      if (!(value instanceof zod.ZodType) || namesByValue.has(value)) {
        continue;
      }
      let unique = name;
      for (let suffix = 2; taken.has(unique); suffix += 1) {
        unique = `${name}_${suffix}`;
      }
      taken.add(unique);
      namesByValue.set(value, unique);
      if (moduleName === root) {
        rootNames.push(unique);
      }
    }
  }
  const serializer = new Serializer(zod, namesByValue);
  const defs = {};
  try {
    const valuesByName = new Map([...namesByValue].map(([value, name]) => [name, value]));
    runBounded(() => {
      const pending = [...rootNames];
      if (routers) {
        for (const [name, value] of Object.entries(rootExports ?? {})) {
          if (isRouter(value)) {
            response.routers.push(describeRouter(serializer, zod, name, value));
          }
        }
        pending.push(...serializer.drainReferenced());
      }
      while (pending.length) {
        const name = pending.shift();
        if (name in defs) {
          continue;
        }
        defs[name] = serializer.root(valuesByName.get(name));
        pending.push(...serializer.drainReferenced());
      }
    });
  } catch (err) {
    if (err instanceof ExtractError) {
      response.error = { code: err.code, message: err.message };
      return response;
    }
    // A `z.lazy` getter or a default factory is user code too, so a throw while reading the
    // schemas (or a router's procedures) is reported the same way as a throw at import.
    const message = err && typeof err.message === 'string' ? err.message : String(err);
    response.error = { code: 'MODULE_THREW', message: `A schema threw while it was being read: ${message}` };
    return response;
  }

  response.exports = rootNames;
  response.schema = { $schema: 'https://json-schema.org/draft/2020-12/schema', $defs: defs };
  response.ok = true;
  return response;
}

async function main() {
  if (process.argv.slice(2).includes('--version')) {
    printVersionAndExit();
    return;
  }
  const raw = await readStdin();
  if (!process.permission) {
    reexecUnderPermission(raw);
    return;
  }
  disableNetwork();
  for (const key of Object.keys(process.env)) {
    delete process.env[key];
  }
  let request;
  try {
    request = JSON.parse(raw);
  } catch (err) {
    process.stderr.write(`zod-extract: request is not JSON: ${err.message}\n`);
    process.exit(2);
  }
  if (!request || typeof request !== 'object' || typeof request.files !== 'object' || !request.files) {
    process.stderr.write('zod-extract: request must be {"files": {...}, "root": "..."}\n');
    process.exit(2);
  }
  process.stdout.write(JSON.stringify(extract(request)));
}

main().catch((err) => {
  process.stderr.write(`zod-extract wrapper failed: ${err && err.stack ? err.stack : err}\n`);
  process.exit(1);
});
