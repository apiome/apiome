#!/usr/bin/env node
/**
 * AsyncAPI parse + validate + dereference wrapper (MFI-8.1, #3759).
 *
 * Reads a single AsyncAPI document (JSON or YAML) from STDIN, runs it through
 * `@asyncapi/parser` — which validates it and resolves ($ref-dereferences) it — and
 * writes a single canonical JSON object to STDOUT describing the outcome:
 *
 *   {
 *     "ok":             boolean,            // parsed cleanly (a document, no error diagnostics)
 *     "asyncapiVersion": string | null,     // the document's `asyncapi` version (e.g. "3.0.0")
 *     "identity":       { "title", "version", "id" } | null,
 *     "document":       object | null,      // the dereferenced document, parser internals stripped
 *     "diagnostics":    [ { "severity", "code", "message", "path" } ]
 *   }
 *
 * The process always exits 0 on a *handled* outcome (valid OR invalid document): the
 * verdict travels in the JSON body, not the exit code, so the Python toolchain runner gets
 * parseable JSON in both cases. A non-zero exit is reserved for an unexpected wrapper
 * failure (e.g. the parser threw), with the reason on STDERR.
 *
 * Invoked by the Python `app.asyncapi_parser` service via `app.toolchain_runner` under the
 * `asyncapi-parser` tool key; it has no network access (the sandbox isolates it), so only
 * in-document `$ref`s are resolved — exactly the canonical-JSON shape MFI-8.2 consumes.
 */

import { createRequire } from 'node:module';
import { Parser } from '@asyncapi/parser';

// Spectral diagnostic severities (the parser emits these numeric levels).
const SEVERITY_NAMES = { 0: 'error', 1: 'warning', 2: 'info', 3: 'hint' };

/**
 * Print the wrapper + underlying `@asyncapi/parser` version and exit. This is the
 * `version_probe_args` the Python packaging layer (MFI-5.2) runs via `verify_tool` to confirm
 * the tool actually loads, without feeding it a document.
 */
function printVersionAndExit() {
  let parserVersion = 'unknown';
  try {
    parserVersion = createRequire(import.meta.url)('@asyncapi/parser/package.json').version;
  } catch {
    // The package.json is not resolvable in this layout; the banner still confirms the wrapper.
  }
  process.stdout.write(`asyncapi-parse (apiome) @asyncapi/parser ${parserVersion}\n`);
  process.exit(0);
}

/** Read all of STDIN into a single UTF-8 string. */
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
 * Recursively remove the `x-parser-*` extension keys the parser injects (e.g.
 * `x-parser-schema-id`, `x-parser-spec-parsed`). They are parser bookkeeping, not part of
 * the AsyncAPI document, so dropping them yields a stable canonical JSON whose fingerprint
 * depends only on the author's content.
 */
function stripParserExtensions(value) {
  if (Array.isArray(value)) {
    return value.map(stripParserExtensions);
  }
  if (value && typeof value === 'object') {
    const out = {};
    for (const [key, child] of Object.entries(value)) {
      if (key.startsWith('x-parser-')) {
        continue;
      }
      out[key] = stripParserExtensions(child);
    }
    return out;
  }
  return value;
}

/** Map one parser diagnostic onto the wrapper's stable, JSON-friendly shape. */
function mapDiagnostic(diagnostic) {
  const path = Array.isArray(diagnostic.path) ? diagnostic.path.join('/') : '';
  return {
    severity: SEVERITY_NAMES[diagnostic.severity] ?? 'error',
    code: diagnostic.code != null ? String(diagnostic.code) : '',
    message: diagnostic.message ?? '',
    path,
  };
}

async function main() {
  if (process.argv.slice(2).includes('--version')) {
    printVersionAndExit();
    return;
  }
  const raw = await readStdin();
  const parser = new Parser();
  const { document, diagnostics } = await parser.parse(raw);

  const mappedDiagnostics = (diagnostics ?? []).map(mapDiagnostic);
  const hasErrors = mappedDiagnostics.some((d) => d.severity === 'error');

  let asyncapiVersion = null;
  let identity = null;
  let cleaned = null;

  if (document) {
    const json = document.json();
    cleaned = stripParserExtensions(json);
    asyncapiVersion = typeof cleaned.asyncapi === 'string' ? cleaned.asyncapi : null;
    const info = cleaned.info ?? {};
    identity = {
      title: typeof info.title === 'string' ? info.title : null,
      version: typeof info.version === 'string' ? info.version : null,
      id: typeof cleaned.id === 'string' ? cleaned.id : null,
    };
  }

  const result = {
    ok: Boolean(document) && !hasErrors,
    asyncapiVersion,
    identity,
    document: cleaned,
    diagnostics: mappedDiagnostics,
  };

  process.stdout.write(JSON.stringify(result));
}

main().catch((err) => {
  process.stderr.write(`asyncapi-parse wrapper failed: ${err && err.stack ? err.stack : err}\n`);
  process.exit(1);
});
