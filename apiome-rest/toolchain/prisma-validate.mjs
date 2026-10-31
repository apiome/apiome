#!/usr/bin/env node
/**
 * Prisma schema validation wrapper (MFX-35.2, #4312).
 *
 * Reads one `schema.prisma` from STDIN, writes it into a fresh temporary directory, runs the
 * installed Prisma CLI's `prisma validate --schema schema.prisma` there, and writes one JSON object
 * to STDOUT:
 *
 *   {
 *     "ok":          boolean,                         // `prisma validate` exited 0
 *     "diagnostics": [ { "message", "line" } ]       // one per `error:` line; empty when ok
 *   }
 *
 * The CLI runs with telemetry and update checks off, `HOME` inside the temporary directory (so its
 * cache never touches the service's) and colour off. `prisma validate` reads the schema with Prisma's
 * own WebAssembly schema engine: it needs no network and no database.
 *
 * The process exits 0 on a handled outcome (valid OR invalid schema): the verdict travels in the
 * JSON body. A non-zero exit means the wrapper itself failed, with the reason on STDERR.
 *
 * Invoked by `app.db_schema_validation` through `app.toolchain_runner` under the `prisma-validator`
 * tool key.
 */

import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const PRISMA_ROOT = join(HERE, 'node_modules', 'prisma');
const PRISMA_CLI = join(PRISMA_ROOT, 'build', 'index.js');
/** How long one `prisma validate` may take before the wrapper gives up on it. */
const VALIDATE_TIMEOUT_MS = 60_000;

/** The installed `prisma` version. */
function prismaVersion() {
  try {
    return JSON.parse(readFileSync(join(PRISMA_ROOT, 'package.json'), 'utf8')).version ?? 'unknown';
  } catch {
    return 'unknown';
  }
}

/** Read all of STDIN into one UTF-8 string. */
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
 * The validation errors in the CLI's output: each `error: …` line, with the schema line its
 * following `-->  schema.prisma:<line>` pointer names.
 */
function parseDiagnostics(output) {
  // eslint-disable-next-line no-control-regex
  const lines = output.replace(/\u001b\[[0-9;]*m/g, '').split(/\r?\n/);
  const diagnostics = [];
  for (const line of lines) {
    const error = line.match(/^\s*error:\s*(.+)$/);
    if (error) {
      diagnostics.push({ message: error[1].trim(), line: null });
      continue;
    }
    const pointer = line.match(/-->\s+\S*schema\.prisma:(\d+)/);
    if (pointer && diagnostics.length && diagnostics[diagnostics.length - 1].line === null) {
      diagnostics[diagnostics.length - 1].line = Number(pointer[1]);
    }
  }
  return diagnostics;
}

async function main() {
  if (process.argv.slice(2).includes('--version')) {
    process.stdout.write(`prisma-validate (apiome) prisma ${prismaVersion()}\n`);
    return;
  }
  const schema = await readStdin();
  const workdir = mkdtempSync(join(tmpdir(), 'apiome-prisma-'));
  try {
    writeFileSync(join(workdir, 'schema.prisma'), schema, 'utf8');
    const run = spawnSync(process.execPath, [PRISMA_CLI, 'validate', '--schema', 'schema.prisma'], {
      cwd: workdir,
      encoding: 'utf8',
      timeout: VALIDATE_TIMEOUT_MS,
      env: {
        PATH: process.env.PATH ?? '',
        HOME: workdir,
        CHECKPOINT_DISABLE: '1',
        PRISMA_HIDE_UPDATE_MESSAGE: '1',
        NO_COLOR: '1',
      },
    });
    if (run.error) {
      throw run.error;
    }
    const output = `${run.stdout ?? ''}\n${run.stderr ?? ''}`;
    const ok = run.status === 0;
    let diagnostics = ok ? [] : parseDiagnostics(output);
    if (!ok && diagnostics.length === 0) {
      diagnostics = [{ message: output.trim().split(/\r?\n/).slice(-5).join(' ') || 'prisma validate failed', line: null }];
    }
    process.stdout.write(JSON.stringify({ ok, diagnostics }));
  } finally {
    rmSync(workdir, { recursive: true, force: true });
  }
}

main().catch((err) => {
  process.stderr.write(`prisma-validate wrapper failed: ${err && err.stack ? err.stack : err}\n`);
  process.exit(1);
});
