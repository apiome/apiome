#!/usr/bin/env node
/**
 * AsyncAPI diff / breaking-change wrapper (MFI-8.4, #3762).
 *
 * Reads a single JSON object from STDIN holding two *already-validated and dereferenced*
 * AsyncAPI documents (the canonical JSON MFI-8.1 produces) — the older/"from" side and the
 * newer/"to" side:
 *
 *   { "old": <asyncapi document>, "new": <asyncapi document> }
 *
 * runs them through `@asyncapi/diff` with its built-in standard ruleset (which classifies
 * each change `breaking` / `non-breaking` / `unclassified`), and writes a single canonical
 * JSON object to STDOUT:
 *
 *   {
 *     "ok":      boolean,                 // the diff was computed
 *     "changes": [                        // every classified change, in @asyncapi/diff order
 *       {
 *         "action":  "add" | "remove" | "edit",
 *         "type":    "breaking" | "non-breaking" | "unclassified",
 *         "pointer": "/channels/user~1signedup",   // the raw RFC-6901 JSON Pointer
 *         "path":    ["channels", "user/signedup"]  // pointer decoded into plain segments
 *       }
 *     ]
 *   }
 *
 * Both documents are passed as plain objects (`@asyncapi/diff` diffs them with fast-json-patch
 * and classifies by JSON-Pointer prefix against its standard config), so no parser instance is
 * needed here. The JSON Pointer is decoded into a `path` segment array — with RFC-6901 `~1`→`/`
 * and `~0`→`~` unescaping applied — so the Python side can join a change onto a canonical
 * entity (a channel address, an operation name) without re-implementing pointer parsing.
 *
 * The process exits 0 on a handled outcome (the diff body travels in the JSON, not the exit
 * code). A non-zero exit is reserved for an unexpected wrapper failure (bad input, or the
 * library threw), with the reason on STDERR — the toolchain runner maps that to an
 * infrastructure error.
 *
 * Invoked by the Python `app.asyncapi_diff` service via `app.toolchain_runner` under the
 * `asyncapi-diff` tool key; it has no network access (the sandbox isolates it).
 */

import { createRequire } from 'node:module';
import { diff } from '@asyncapi/diff';

/**
 * Print the wrapper + underlying `@asyncapi/diff` version and exit. This is the
 * `version_probe_args` the Python packaging layer (MFI-5.2) runs via `verify_tool` to confirm
 * the tool actually loads, without feeding it documents.
 */
function printVersionAndExit() {
  let diffVersion = 'unknown';
  try {
    diffVersion = createRequire(import.meta.url)('@asyncapi/diff/package.json').version;
  } catch {
    // The package.json is not resolvable in this layout; the banner still confirms the wrapper.
  }
  process.stdout.write(`asyncapi-diff (apiome) @asyncapi/diff ${diffVersion}\n`);
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
 * Decode an RFC-6901 JSON Pointer (e.g. `/channels/user~1signedup`) into its plain segment
 * array (`["channels", "user/signedup"]`), reversing the `~1`→`/` and `~0`→`~` escaping. An
 * empty pointer (the document root) decodes to an empty array.
 */
function decodePointer(pointer) {
  if (typeof pointer !== 'string' || pointer === '') {
    return [];
  }
  return pointer
    .split('/')
    .slice(1) // a JSON Pointer starts with a leading "/", so the first split piece is empty
    .map((segment) => segment.replace(/~1/g, '/').replace(/~0/g, '~'));
}

/** Map one @asyncapi/diff change onto the wrapper's stable, JSON-friendly shape. */
function mapChange(change) {
  const pointer = typeof change.path === 'string' ? change.path : '';
  return {
    action: change.action,
    type: change.type,
    pointer,
    path: decodePointer(pointer),
  };
}

async function main() {
  if (process.argv.slice(2).includes('--version')) {
    printVersionAndExit();
    return;
  }

  const raw = await readStdin();
  const input = JSON.parse(raw);
  if (!input || typeof input !== 'object' || !input.old || !input.new) {
    throw new Error('input must be a JSON object with `old` and `new` AsyncAPI documents');
  }

  // The standard config (no override) is used: @asyncapi/diff already ships a v2 and v3
  // breaking/non-breaking ruleset. `outputType: 'json'` makes the change accessors return
  // structured arrays rather than a formatted string.
  const result = diff(input.old, input.new, { outputType: 'json' });
  const changes = result.getOutput().changes.map(mapChange);

  process.stdout.write(JSON.stringify({ ok: true, changes }));
}

main().catch((err) => {
  process.stderr.write(`asyncapi-diff wrapper failed: ${err && err.stack ? err.stack : err}\n`);
  process.exit(1);
});
