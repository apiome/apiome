import { Pool, type PoolConfig } from 'pg';
import type { Writable } from 'node:stream';

import {
  createImportEngine,
  type ImportEngine,
  type ImportJobInput,
  type ImportJobState,
  type ImportStatus,
} from '../engine/import-helper';
import { PgTransactionalClient } from '../engine/pg-client';
import { installRunnerSignals } from './lifecycle';
import { writeNdjsonLine } from './stdio-events';

export const RUNNER_SCHEMA_VERSION = 1 as const;

/** CLI validation / protocol mismatch (orchestrator exit code 7). */
export const EXIT_VALIDATION = 7;

export type RunnerDbConfig = { connectionString: string } & Omit<PoolConfig, 'connectionString'>;

export type RunnerEnvelope = {
  schemaVersion: typeof RUNNER_SCHEMA_VERSION;
  jobId: string;
  input: ImportJobInput;
  dbConfig: RunnerDbConfig;
};

export type EnvelopeParseFailure = { code: string; message: string; context?: unknown };

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function readPositiveIntFromEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) return fallback;
  const parsed = Number(raw);
  if (!Number.isInteger(parsed) || parsed < 1) return fallback;
  return parsed;
}

const STATUS_POLL_INITIAL_MS = readPositiveIntFromEnv('OBJECTIFIED_IMPORTER_RUNNER_POLL_MS', 100);
const STATUS_POLL_MAX_MS = readPositiveIntFromEnv('OBJECTIFIED_IMPORTER_RUNNER_MAX_POLL_MS', 1_000);
const EMITTED_EVENT_IDS_LIMIT = readPositiveIntFromEnv('OBJECTIFIED_IMPORTER_RUNNER_MAX_TRACKED_EVENT_IDS', 2_048);

export function parseEnvelope(raw: unknown): { ok: true; envelope: RunnerEnvelope } | { ok: false; error: EnvelopeParseFailure } {
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) {
    return { ok: false, error: { code: 'INVALID_ENVELOPE', message: 'Expected a single JSON object on stdin' } };
  }

  const o = raw as Record<string, unknown>;

  if (o.schemaVersion !== RUNNER_SCHEMA_VERSION) {
    return {
      ok: false,
      error: {
        code: 'SCHEMA_VERSION_MISMATCH',
        message: `Unsupported schemaVersion (expected ${RUNNER_SCHEMA_VERSION})`,
        context: { expected: RUNNER_SCHEMA_VERSION, got: o.schemaVersion },
      },
    };
  }

  if (typeof o.jobId !== 'string' || !o.jobId.trim()) {
    return { ok: false, error: { code: 'INVALID_JOB_ID', message: 'jobId must be a non-empty string' } };
  }

  if (!o.input || typeof o.input !== 'object' || Array.isArray(o.input)) {
    return { ok: false, error: { code: 'INVALID_INPUT', message: 'input must be a JSON object (ImportJobInput)' } };
  }

  if (!o.dbConfig || typeof o.dbConfig !== 'object' || Array.isArray(o.dbConfig)) {
    return { ok: false, error: { code: 'INVALID_DB_CONFIG', message: 'dbConfig must be a JSON object' } };
  }

  const db = o.dbConfig as Record<string, unknown>;
  if (typeof db.connectionString !== 'string' || !db.connectionString.trim()) {
    return { ok: false, error: { code: 'INVALID_DB_CONFIG', message: 'dbConfig.connectionString is required' } };
  }

  return {
    ok: true,
    envelope: {
      schemaVersion: RUNNER_SCHEMA_VERSION,
      jobId: o.jobId.trim(),
      input: o.input as ImportJobInput,
      dbConfig: o.dbConfig as RunnerDbConfig,
    },
  };
}

function poolFromDbConfig(dbConfig: RunnerDbConfig): Pool {
  const { connectionString, ...rest } = dbConfig;
  return new Pool({ connectionString, ...rest });
}

function isTerminalState(state: ImportJobState): boolean {
  return (
    state === 'pending-approval' ||
    state === 'completed' ||
    state === 'failed' ||
    state === 'canceled' ||
    state === 'rolled-back'
  );
}

/** Maps engine states to NDJSON `result.state` values for the sidecar protocol. */
export function mapCliResultState(status: ImportStatus): string {
  if (status.state === 'rolled-back' || status.state === 'canceled') return 'canceled';
  if (status.state === 'failed') return 'failed';
  if (status.state === 'completed') return 'completed';
  if (status.state === 'pending-approval') return 'pending-approval';
  return status.state;
}

async function streamUntilTerminal(engine: ImportEngine, jobId: string, stdout: Writable): Promise<ImportJobState> {
  const emittedEventIds = new Set<string>();
  const emittedEventOrder: string[] = [];
  let lastProgressJson: string | null = null;
  let previousState: ImportJobState | null = null;
  let pollDelayMs = STATUS_POLL_INITIAL_MS;

  for (;;) {
    const status = await engine.getImportStatus(jobId);
    const stateChanged = previousState !== status.state;
    previousState = status.state;
    let observedOutput = false;

    for (const ev of status.events) {
      if (!emittedEventIds.has(ev.id)) {
        emittedEventIds.add(ev.id);
        emittedEventOrder.push(ev.id);
        while (emittedEventOrder.length > EMITTED_EVENT_IDS_LIMIT) {
          const evictedId = emittedEventOrder.shift();
          if (evictedId === undefined) {
            continue;
          }
          emittedEventIds.delete(evictedId);
        }
        await writeNdjsonLine(stdout, { type: 'event', event: ev });
        observedOutput = true;
      }
    }

    if (status.progress) {
      const pj = JSON.stringify(status.progress);
      if (pj !== lastProgressJson) {
        lastProgressJson = pj;
        await writeNdjsonLine(stdout, { type: 'progress', progress: status.progress });
        observedOutput = true;
      }
    }

    if (isTerminalState(status.state)) {
      if (status.state === 'failed') {
        const lastErr = [...status.events].reverse().find((e) => e.level === 'error');
        if (lastErr) {
          await writeNdjsonLine(stdout, {
            type: 'error',
            code: lastErr.code,
            message: lastErr.message,
            context: lastErr.context,
          });
        }
      }

      await writeNdjsonLine(stdout, {
        type: 'result',
        state: mapCliResultState(status),
        summary: status.summary,
      });

      return status.state;
    }

    if (stateChanged || observedOutput) {
      pollDelayMs = STATUS_POLL_INITIAL_MS;
    } else {
      pollDelayMs = Math.min(STATUS_POLL_MAX_MS, pollDelayMs * 2);
    }
    await sleep(pollDelayMs);
  }
}

export async function runImportWithEngine(
  envelope: RunnerEnvelope,
  stdout: Writable,
  stderr: Writable,
  engine: ImportEngine
): Promise<number> {
  let importStarted = false;
  let cancelAfterStart = false;
  const disposeSignals = installRunnerSignals(async () => {
    if (!importStarted) {
      cancelAfterStart = true;
      return;
    }
    await engine.cancelImport(envelope.jobId);
  });

  try {
    await engine.startImport(envelope.input, { jobId: envelope.jobId });
    importStarted = true;
    if (cancelAfterStart) {
      await engine.cancelImport(envelope.jobId);
    }

    await streamUntilTerminal(engine, envelope.jobId, stdout);
    return 0;
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    stderr.write(`${message}\n`);
    await writeNdjsonLine(stdout, {
      type: 'error',
      code: 'RUNNER_EXCEPTION',
      message,
    });
    await writeNdjsonLine(stdout, { type: 'result', state: 'failed', summary: undefined });
    return 0;
  } finally {
    disposeSignals();
  }
}

export async function runStdioImportCli(streams: {
  stdin: NodeJS.ReadableStream;
  stdout: Writable;
  stderr: Writable;
}): Promise<number> {
  const chunks: Buffer[] = [];
  try {
    for await (const chunk of streams.stdin) {
      chunks.push(Buffer.from(chunk));
    }
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    await writeNdjsonLine(streams.stdout, { type: 'error', code: 'STDIN_READ_FAILED', message });
    return EXIT_VALIDATION;
  }

  const text = Buffer.concat(chunks).toString('utf8').trim();
  if (!text) {
    await writeNdjsonLine(streams.stdout, {
      type: 'error',
      code: 'EMPTY_STDIN',
      message: 'Expected one JSON envelope on stdin',
    });
    return EXIT_VALIDATION;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(text) as unknown;
  } catch {
    await writeNdjsonLine(streams.stdout, { type: 'error', code: 'INVALID_JSON', message: 'stdin is not valid JSON' });
    return EXIT_VALIDATION;
  }

  const parsedEnvelope = parseEnvelope(parsed);
  if (!parsedEnvelope.ok) {
    await writeNdjsonLine(streams.stdout, {
      type: 'error',
      code: parsedEnvelope.error.code,
      message: parsedEnvelope.error.message,
      context: parsedEnvelope.error.context,
    });
    return EXIT_VALIDATION;
  }

  const { envelope } = parsedEnvelope;
  const pool = poolFromDbConfig(envelope.dbConfig);

  try {
    const engine = createImportEngine({
      txClient: new PgTransactionalClient(pool),
    });
    return await runImportWithEngine(envelope, streams.stdout, streams.stderr, engine);
  } finally {
    await pool.end().catch(() => {});
  }
}
