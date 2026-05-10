import type { ObjectifiedApi, SpecImportJobStatus } from "../client.js";

/** Default interval between GET …/imports/{job_id} polls when `--poll` is omitted (ms). */
export const DEFAULT_SPEC_IMPORT_POLL_INTERVAL_MS = 400;

const POLL_MS_MIN = 50;
const POLL_MS_MAX = 120_000;

/** Optional stderr hook for `objectified import spec --verbose`. */
export type SpecImportPollLog = (line: string) => void;

/** Clamp `--poll` values to a supported range (ms). */
export function clampSpecImportPollIntervalMs(ms: number): number {
  return Math.min(Math.max(ms, POLL_MS_MIN), POLL_MS_MAX);
}

function resolvePollIntervalMs(pollMs: number | undefined): number {
  return pollMs === undefined
    ? DEFAULT_SPEC_IMPORT_POLL_INTERVAL_MS
    : clampSpecImportPollIntervalMs(pollMs);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function describeSpecImportLifecycleState(st: SpecImportJobStatus): string {
  const pct = st.percent ?? 0;
  switch (st.state) {
    case "queued":
      return `the job is queued on the server (reported progress ${String(pct)}% — work has not started yet or the worker is picking it up)`;
    case "running":
      return `the server is actively processing your specification (${String(pct)}% — parsing entities and applying them to the catalog preview)`;
    case "pending-approval":
      return `the preview transaction is ready for review (${String(pct)}% — commit to persist, rollback to discard, or stop here with --no-commit)`;
    case "committing":
      return `the server is committing the approved preview into the catalog (${String(pct)}%)`;
    case "completed":
      return `the import finished successfully (${String(pct)}%)`;
    case "failed":
      return `the import failed (${String(pct)}% — inspect events on the job or retry)`;
    case "canceled":
      return `the import was canceled (${String(pct)}%)`;
    case "rolled-back":
      return `the preview was rolled back (${String(pct)}%)`;
    default:
      return `unrecognized lifecycle state ${String(st.state)} (${String(pct)}%)`;
  }
}

function describeSpecImportProgressDetail(progress: SpecImportJobStatus["progress"]): string | null {
  if (!progress || typeof progress.phase !== "string") return null;
  const bits: string[] = [];
  bits.push(`phase "${progress.phase}"`);
  if (typeof progress.total === "number" && typeof progress.completed === "number") {
    bits.push(`step ${String(progress.completed)} of ${String(progress.total)}`);
  }
  const cur = progress.current_item;
  if (typeof cur === "string" && cur.trim() !== "") {
    bits.push(`currently working on "${cur.trim()}"`);
  }
  return `Structured progress from the importer: ${bits.join("; ")}.`;
}

function describeLatestSpecImportEvent(st: SpecImportJobStatus): string | null {
  const evs = st.events;
  if (evs === undefined || evs.length === 0) return null;
  const last = evs[evs.length - 1];
  if (last?.code === undefined || last.code === "") return null;
  const msg =
    typeof last.message === "string" && last.message.trim() !== ""
      ? `: ${last.message.trim()}`
      : "";
  return `Most recent server event: ${last.code}${msg}`;
}

/**
 * Human-readable snapshot after each GET …/imports/{job_id}.
 * Includes plain-language lifecycle state plus structured progress and last event when present.
 */
export function formatSpecImportPollLine(attempt: number, st: SpecImportJobStatus): string {
  const head = `Import status check #${String(attempt)} (job ${st.job_id}): ${describeSpecImportLifecycleState(st)}`;
  const prog = describeSpecImportProgressDetail(st.progress);
  const ev = describeLatestSpecImportEvent(st);
  const tail = [prog, ev].filter((x): x is string => x !== null);
  if (tail.length === 0) return head;
  return `${head} ${tail.join(" ")}`;
}

/** Explains the deliberate delay between poll requests (shown when `--verbose` is set). */
export function formatSpecImportPollWaitLine(intervalMs: number): string {
  return `Waiting ${String(intervalMs)}ms before requesting import status again (gives the server time to advance parsing, validation, or catalog writes).`;
}

/** Poll until the job needs finalize, ends successfully without approval, or fails. */
export async function pollSpecImportUntilGate(opts: {
  api: Pick<ObjectifiedApi, "getSpecImportStatus">;
  tenantSlug: string;
  jobId: string;
  signal?: AbortSignal;
  log?: SpecImportPollLog;
  /** Interval between polls (ms); see `--poll` on import spec (default {@link DEFAULT_SPEC_IMPORT_POLL_INTERVAL_MS}). */
  pollIntervalMs?: number;
}): Promise<SpecImportJobStatus> {
  const intervalMs = resolvePollIntervalMs(opts.pollIntervalMs);
  let attempt = 0;
  for (;;) {
    opts.signal?.throwIfAborted();
    const st = await opts.api.getSpecImportStatus(opts.tenantSlug, opts.jobId);
    opts.log?.(formatSpecImportPollLine(attempt, st));
    if (
      st.state === "pending-approval" ||
      st.state === "completed" ||
      st.state === "failed" ||
      st.state === "canceled" ||
      st.state === "rolled-back"
    ) {
      return st;
    }
    opts.log?.(formatSpecImportPollWaitLine(intervalMs));
    await sleep(intervalMs);
    attempt++;
  }
}

/** Poll until a terminal lifecycle state (includes rolled-back). */
export async function pollSpecImportUntilTerminal(opts: {
  api: Pick<ObjectifiedApi, "getSpecImportStatus">;
  tenantSlug: string;
  jobId: string;
  signal?: AbortSignal;
  log?: SpecImportPollLog;
  /** Interval between polls (ms); see `--poll` on import spec (default {@link DEFAULT_SPEC_IMPORT_POLL_INTERVAL_MS}). */
  pollIntervalMs?: number;
}): Promise<SpecImportJobStatus> {
  const intervalMs = resolvePollIntervalMs(opts.pollIntervalMs);
  let attempt = 0;
  for (;;) {
    opts.signal?.throwIfAborted();
    const st = await opts.api.getSpecImportStatus(opts.tenantSlug, opts.jobId);
    opts.log?.(formatSpecImportPollLine(attempt, st));
    if (
      st.state === "completed" ||
      st.state === "failed" ||
      st.state === "canceled" ||
      st.state === "rolled-back"
    ) {
      return st;
    }
    opts.log?.(formatSpecImportPollWaitLine(intervalMs));
    await sleep(intervalMs);
    attempt++;
  }
}
