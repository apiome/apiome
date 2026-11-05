#!/usr/bin/env node
/**
 * Build the GraphiQL test-drive bundle — MFX-44.3 (#4369).
 *
 * Bundles `lib/test-drive/graphiql-app.tsx` (React, GraphiQL, `graphql`, `@graphql-tools/mock`) into
 * `public/test-drive/graphiql/graphiql-test-drive.{js,css}`, the only script the sandboxed GraphiQL
 * page (`/test-drive/graphql`) loads. The output is generated, not committed (see `.gitignore`); `yarn
 * build` and `scripts/run.sh dev` run this first.
 *
 * Usage: node scripts/build-test-drive-graphiql.mjs
 */

import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { build } from 'esbuild';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

await build({
  entryPoints: { 'graphiql-test-drive': path.join(ROOT, 'lib/test-drive/graphiql-app.tsx') },
  outdir: path.join(ROOT, 'public/test-drive/graphiql'),
  bundle: true,
  format: 'iife',
  platform: 'browser',
  target: ['es2020'],
  jsx: 'automatic',
  minify: true,
  legalComments: 'linked',
  // GraphiQL's stylesheet embeds its fonts and icons; keep them inline (the page allows data: URLs).
  loader: { '.woff': 'dataurl', '.woff2': 'dataurl', '.ttf': 'dataurl', '.svg': 'dataurl', '.png': 'dataurl' },
  define: { 'process.env.NODE_ENV': '"production"' },
  logLevel: 'warning',
});

console.log('Built public/test-drive/graphiql/graphiql-test-drive.{js,css}');
