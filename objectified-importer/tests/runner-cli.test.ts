/**
 * NDJSON-over-stdio import runner (#3304).
 */

import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import { Readable, Writable } from 'node:stream';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';

import type { ImportEngine } from '../src/engine/import-helper';
import {
  EXIT_VALIDATION,
  RUNNER_SCHEMA_VERSION,
  mapCliResultState,
  parseEnvelope,
  runImportWithEngine,
  runStdioImportCli,
} from '../src/runner/index';
import { writeNdjsonLine } from '../src/runner/stdio-events';

const pkgRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const runJs = path.join(pkgRoot, 'bin/run.js');

function collectWritable(): { stream: Writable; getText: () => string } {
  const chunks: Buffer[] = [];
  const stream = new Writable({
    write(chunk, _enc, cb) {
      chunks.push(Buffer.from(chunk));
      cb();
    },
  });
  return {
    stream,
    getText: () => Buffer.concat(chunks).toString('utf8'),
  };
}

function parseNdjsonLines(text: string): unknown[] {
  return text
    .trim()
    .split('\n')
    .filter((line) => line.length > 0)
    .map((line) => JSON.parse(line) as unknown);
}

describe('runner parseEnvelope', () => {
  test('schemaVersion mismatch is rejected', () => {
    const r = parseEnvelope({ schemaVersion: 99, jobId: 'j', input: {}, dbConfig: { connectionString: 'x' } });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error.code).toBe('SCHEMA_VERSION_MISMATCH');
  });

  test('valid envelope parses', () => {
    const r = parseEnvelope({
      schemaVersion: RUNNER_SCHEMA_VERSION,
      jobId: '550e8400-e29b-41d4-a716-446655440000',
      input: { tenantId: 't', userId: 'u' },
      dbConfig: { connectionString: 'postgresql://localhost/db' },
    });
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.envelope.jobId).toBe('550e8400-e29b-41d4-a716-446655440000');
  });
});

describe('runner mapCliResultState', () => {
  test('rolls back and cancel map to canceled', () => {
    expect(
      mapCliResultState({
        jobId: 'j',
        state: 'rolled-back',
        percent: 0,
        events: [],
      })
    ).toBe('canceled');
    expect(
      mapCliResultState({
        jobId: 'j',
        state: 'canceled',
        percent: 0,
        events: [],
      })
    ).toBe('canceled');
  });
});

describe('runner NDJSON line buffering', () => {
  test('each writeNdjsonLine is exactly one JSON line', async () => {
    const { stream, getText } = collectWritable();
    await writeNdjsonLine(stream, { type: 'progress', progress: { phase: 'creating-classes', total: 3, completed: 1 } });
    await writeNdjsonLine(stream, { type: 'result', state: 'completed', summary: { ok: true } });
    const lines = getText().trim().split('\n');
    expect(lines).toHaveLength(2);
    expect(JSON.parse(lines[0])).toMatchObject({ type: 'progress' });
    expect(JSON.parse(lines[1])).toMatchObject({ type: 'result', state: 'completed' });
  });
});

describe('runner mocked engine', () => {
  test('SIGTERM during startup cancels once and exits 0 with canceled result', async () => {
    let canceled = false;
    let cancelCalls = 0;
    const envelope = parseEnvelope({
      schemaVersion: RUNNER_SCHEMA_VERSION,
      jobId: '550e8400-e29b-41d4-a716-446655440010',
      input: {
        tenantId: 't',
        userId: 'u',
        sourceKind: 'openapi',
        document: {},
        project: { name: 'P', slug: 'p', description: null },
        version: { versionId: '1.0.0', description: null },
        options: { selectedSchemas: [] },
      },
      dbConfig: { connectionString: 'postgresql://noop' },
    });
    expect(envelope.ok).toBe(true);
    if (!envelope.ok) throw new Error('fixture');

    const engine: ImportEngine = {
      startImport: async (_input, opts) => {
        await new Promise((r) => setTimeout(r, 40));
        return { jobId: opts?.jobId ?? 'missing' };
      },
      getImportStatus: async (jobId) => {
        if (canceled) {
          return {
            jobId,
            state: 'canceled',
            percent: 0,
            events: [{ id: 'sig-done', ts: 1, level: 'warn', code: 'CANCELED', message: 'canceled' }],
            summary: {},
          };
        }
        return {
          jobId,
          state: 'running',
          percent: 10,
          events: [{ id: 'sig-run', ts: 1, level: 'info', code: 'RUN', message: 'running' }],
          progress: { phase: 'creating-classes', total: 10, completed: 1 },
        };
      },
      cancelImport: async () => {
        cancelCalls += 1;
        canceled = true;
        return { success: true };
      },
      commitImport: async () => ({ success: false }),
      rollbackImport: async () => ({ success: true }),
      rollbackCompletedImport: async () => ({ success: false }),
      retryImport: async () => ({ success: false }),
    };

    const { stream: stdout, getText } = collectWritable();
    const runPromise = runImportWithEngine(envelope.envelope, stdout, process.stderr, engine);
    await new Promise((r) => setTimeout(r, 10));
    process.emit('SIGTERM');

    const code = await runPromise;
    expect(code).toBe(0);
    expect(cancelCalls).toBe(1);

    const lines = parseNdjsonLines(getText());
    const last = lines[lines.length - 1] as { type?: string; state?: string };
    expect(last.type).toBe('result');
    expect(last.state).toBe('canceled');
  });

  test('cancelImport mid-run yields canceled result and exit 0', async () => {
    let canceled = false;
    const envelope = parseEnvelope({
      schemaVersion: RUNNER_SCHEMA_VERSION,
      jobId: '550e8400-e29b-41d4-a716-446655440001',
      input: {
        tenantId: 't',
        userId: 'u',
        sourceKind: 'openapi',
        document: {},
        project: { name: 'P', slug: 'p', description: null },
        version: { versionId: '1.0.0', description: null },
        options: { selectedSchemas: [] },
      },
      dbConfig: { connectionString: 'postgresql://noop' },
    });
    expect(envelope.ok).toBe(true);
    if (!envelope.ok) throw new Error('fixture');

    const engine: ImportEngine = {
      startImport: async (_input, opts) => ({ jobId: opts?.jobId ?? 'missing' }),
      getImportStatus: async (jobId) => {
        if (canceled) {
          return {
            jobId,
            state: 'canceled',
            percent: 0,
            events: [{ id: 'e-done', ts: 1, level: 'warn', code: 'CANCELED', message: 'canceled' }],
            summary: {},
          };
        }
        return {
          jobId,
          state: 'running',
          percent: 10,
          events: [{ id: 'e1', ts: 1, level: 'info', code: 'RUN', message: 'running' }],
          progress: { phase: 'creating-classes', total: 10, completed: 1 },
        };
      },
      cancelImport: async () => {
        canceled = true;
        return { success: true };
      },
      commitImport: async () => ({ success: false }),
      rollbackImport: async () => ({ success: true }),
      rollbackCompletedImport: async () => ({ success: false }),
      retryImport: async () => ({ success: false }),
    };

    const { stream: stdout, getText } = collectWritable();
    const runPromise = runImportWithEngine(envelope.envelope, stdout, process.stderr, engine);
    await new Promise((r) => setTimeout(r, 80));
    await engine.cancelImport(envelope.envelope.jobId);
    const code = await runPromise;
    expect(code).toBe(0);

    const lines = parseNdjsonLines(getText());
    const last = lines[lines.length - 1] as { type?: string; state?: string };
    expect(last.type).toBe('result');
    expect(last.state).toBe('canceled');
    expect(lines.some((l) => (l as { type?: string }).type === 'progress')).toBe(true);
    expect(lines.some((l) => (l as { type?: string }).type === 'event')).toBe(true);
  });

  test('failed terminal state still exits 0', async () => {
    const envelope = parseEnvelope({
      schemaVersion: RUNNER_SCHEMA_VERSION,
      jobId: '550e8400-e29b-41d4-a716-446655440099',
      input: {
        tenantId: 't',
        userId: 'u',
        sourceKind: 'openapi',
        document: {},
        project: { name: 'P', slug: 'p', description: null },
        version: { versionId: '1.0.0', description: null },
        options: { selectedSchemas: [] },
      },
      dbConfig: { connectionString: 'postgresql://noop' },
    });
    expect(envelope.ok).toBe(true);
    if (!envelope.ok) throw new Error('fixture');

    const engine: ImportEngine = {
      startImport: async (_input, opts) => ({ jobId: opts?.jobId ?? 'missing' }),
      getImportStatus: async (jobId) => ({
        jobId,
        state: 'failed',
        percent: 100,
        events: [{ id: 'f1', ts: 1, level: 'error', code: 'FAILED', message: 'boom' }],
        summary: { errors: 1 },
      }),
      cancelImport: async () => ({ success: true }),
      commitImport: async () => ({ success: false }),
      rollbackImport: async () => ({ success: true }),
      rollbackCompletedImport: async () => ({ success: false }),
      retryImport: async () => ({ success: false }),
    };

    const { stream: stdout, getText } = collectWritable();
    const code = await runImportWithEngine(envelope.envelope, stdout, process.stderr, engine);
    expect(code).toBe(0);

    const lines = parseNdjsonLines(getText());
    expect(lines.some((line) => (line as { type?: string; code?: string }).type === 'error')).toBe(true);
    expect(lines.some((line) => (line as { type?: string; code?: string }).code === 'FAILED')).toBe(true);
    const last = lines[lines.length - 1] as { type?: string; state?: string };
    expect(last).toMatchObject({ type: 'result', state: 'failed' });
  });
});

describe('runner stdio CLI validation exit codes', () => {
  test('schema mismatch exits 7 with single error object on stdout', async () => {
    const stdin = Readable.from(
      [
        JSON.stringify({
          schemaVersion: 2,
          jobId: '550e8400-e29b-41d4-a716-446655440002',
          input: {},
          dbConfig: { connectionString: 'postgresql://x' },
        }),
      ],
      { encoding: 'utf8' }
    );

    const out = collectWritable();
    const err = collectWritable();

    const code = await runStdioImportCli({
      stdin,
      stdout: out.stream,
      stderr: err.stream,
    });

    expect(code).toBe(EXIT_VALIDATION);
    const lines = parseNdjsonLines(out.getText());
    expect(lines).toHaveLength(1);
    expect(lines[0]).toMatchObject({ type: 'error', code: 'SCHEMA_VERSION_MISMATCH' });
  });
});

describe('runner bin/spawn integration', () => {
  test('sample-job.json dry run emits progress, events, and completed result', async () => {
    const fixturePath = path.join(pkgRoot, 'tests/fixtures/sample-job.json');
    const raw = await fs.readFile(fixturePath, 'utf8');

    const proc = spawn(process.execPath, [runJs], {
      cwd: pkgRoot,
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env },
    });

    proc.stdin.write(raw);
    proc.stdin.end();

    const stdoutChunks: Buffer[] = [];
    proc.stdout.on('data', (c: Buffer) => stdoutChunks.push(c));

    proc.stderr.on('data', () => {});

    const exitCode: number = await new Promise((resolve, reject) => {
      proc.on('error', reject);
      proc.on('close', (code) => resolve(code ?? 1));
    });

    expect(exitCode).toBe(0);
    const lines = parseNdjsonLines(Buffer.concat(stdoutChunks).toString('utf8'));
    expect(lines.some((l) => (l as { type?: string }).type === 'progress')).toBe(true);
    expect(lines.filter((l) => (l as { type?: string }).type === 'event').length).toBeGreaterThanOrEqual(1);
    const last = lines[lines.length - 1] as { type?: string; state?: string };
    expect(last.type).toBe('result');
    expect(last.state).toBe('completed');
  });
});
