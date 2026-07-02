#!/usr/bin/env node
/**
 * GraphQL-Inspector diff / breaking-change wrapper (MFI-10.5, #3774).
 *
 * Reads a single JSON object from STDIN holding two GraphQL SDL strings — the older/"from"
 * side and the newer/"to" side:
 *
 *   { "old": "<SDL text>", "new": "<SDL text>" }
 *
 * (the canonical SDL MFI-10.2 preserves on `CanonicalApi.raw.sdl`), builds both into
 * `graphql-js` schemas with `buildSchema`, diffs them with `@graphql-inspector/core`'s `diff()`
 * — which classifies every change `BREAKING` / `DANGEROUS` / `NON_BREAKING` under its standard
 * rule set — and writes a single canonical JSON object to STDOUT:
 *
 *   {
 *     "ok":      true,
 *     "changes": [                          // every classified change, in tool order
 *       {
 *         "criticality": "BREAKING" | "DANGEROUS" | "NON_BREAKING",
 *         "type":        "FIELD_REMOVED",   // GraphQL-Inspector's own ChangeType identifier
 *         "path":        "User.email",      // dot-path schema coordinate, when the tool sets one
 *         "message":     "Field 'email' was removed from object type 'User'"
 *       }
 *     ]
 *   }
 *
 * `path` follows GraphQL's own schema-coordinate notation (`Type.field`, bare `Type`, or
 * `Enum.VALUE`), which is exactly the grammar `app.normalizer.Keys` assigns canonical
 * type/field/operation/enum-value keys under — so the Python side can join a change onto the
 * canonical entity it grades by simple key lookup, no path parsing beyond a `.` split.
 *
 * The process exits 0 on a handled outcome (the diff body travels in the JSON, not the exit
 * code). A non-zero exit is reserved for an unexpected wrapper failure (bad input, a schema that
 * fails to build, or the library threw), with the reason on STDERR — the toolchain runner maps
 * that to an infrastructure error.
 *
 * Invoked by the Python `app.graphql_diff` service via `app.toolchain_runner` under the
 * `graphql-inspector-diff` tool key; it has no network access (the sandbox isolates it).
 */

import { createRequire } from 'node:module';
import { buildSchema } from 'graphql';
import { diff } from '@graphql-inspector/core';

/**
 * Print the wrapper + underlying `@graphql-inspector/core` version and exit. This is the
 * `version_probe_args` the Python packaging layer (MFI-5.2) runs via `verify_tool` to confirm
 * the tool actually loads, without feeding it schemas.
 */
function printVersionAndExit() {
  let coreVersion = 'unknown';
  try {
    coreVersion = createRequire(import.meta.url)('@graphql-inspector/core/package.json').version;
  } catch {
    // The package.json is not resolvable in this layout; the banner still confirms the wrapper.
  }
  process.stdout.write(`graphql-inspector-diff (apiome) @graphql-inspector/core ${coreVersion}\n`);
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

/** Map one `@graphql-inspector/core` change onto the wrapper's stable, JSON-friendly shape. */
function mapChange(change) {
  return {
    criticality: change.criticality && change.criticality.level,
    type: change.type,
    path: typeof change.path === 'string' && change.path ? change.path : null,
    message: typeof change.message === 'string' ? change.message : '',
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
    throw new Error('input must be a JSON object with `old` and `new` GraphQL SDL strings');
  }

  const oldSchema = buildSchema(input.old);
  const newSchema = buildSchema(input.new);

  // The standard rule set (no override) is used: @graphql-inspector/core already ships the
  // breaking/dangerous/non-breaking classification the roadmap calls for.
  const changes = await diff(oldSchema, newSchema);

  process.stdout.write(JSON.stringify({ ok: true, changes: changes.map(mapChange) }));
}

main().catch((err) => {
  process.stderr.write(
    `graphql-inspector-diff wrapper failed: ${err && err.stack ? err.stack : err}\n`
  );
  process.exit(1);
});
