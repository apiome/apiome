/**
 * Toolchain check console model — MFX-44.6 (#4372).
 *
 * For an IDL target the authoritative test of the emitted artifact is the format's own toolchain
 * (`buf lint`, `tsp compile`, `smithy build`…). The target registry declares which checks apply
 * (`descriptor.test_tools` of kind `toolchain`, MFX-44.1); REST runs one on demand and streams its
 * console as NDJSON (`POST /v1/export/{tenant}/verify/tool-checks/{tool}`). This module is the **pure**
 * half of the Studio's console:
 *
 *  - the wire types of the stream's three events and of a check's result;
 *  - {@link createNdjsonDecoder}, which turns arbitrary network chunks into whole events;
 *  - {@link sanitizeConsoleText} — the console is *ANSI-safe*: colour codes, cursor moves and other
 *    control characters a tool writes are removed, never interpreted, so a hostile or merely
 *    colourful tool cannot restyle or spoof the page;
 *  - {@link appendConsoleOutput} with a retention cap, and {@link consoleTranscript} for **Copy**;
 *  - the status chip vocabulary ({@link toolCheckStatusLabel}, {@link toolCheckStatusTone}), which
 *    states each outcome in words before colour.
 *
 * No React and no fetch here, so it is unit-tested directly — the hook is `useExportToolChecks.ts`.
 */

import type { StatusTone } from '@/app/components/ui/statusVocabulary';
import type { ExportTestTool } from './exportTestDrive';

// ---------------------------------------------------------------------------
// Wire types
// ---------------------------------------------------------------------------

/** How a check run ended (mirrors Python `ToolCheckStatus`). */
export type ToolCheckStatus = 'passed' | 'failed' | 'timed_out' | 'unavailable' | 'error';

/** The closing `result` event's payload (mirrors Python `ExportToolCheckResult`). */
export interface ToolCheckResult {
  /** The runner tool key, e.g. `buf`. */
  tool: string;
  /** The check, e.g. `lint`. */
  check: string;
  /** The declared label, e.g. `buf lint`. */
  label: string;
  status: ToolCheckStatus;
  /** The tool's exit code, or null when it did not exit on its own. */
  exit_code: number | null;
  /** Wall-clock run time in milliseconds. */
  duration_ms: number;
  /** The command as run, relative to the staged artifact. */
  command: string;
  /** The artifact files the check read. */
  files: string[];
  /** Why it did not pass (or could not run), in words; null when it passed. */
  message: string | null;
}

/** One event of the console stream. */
export type ToolCheckEvent =
  | { event: 'start'; tool: string; check: string; label: string; command: string; files: string[] }
  | { event: 'output'; stream: ConsoleStream; text: string }
  | ({ event: 'result' } & ToolCheckResult);

/** Which of the tool's streams a chunk came from. */
export type ConsoleStream = 'stdout' | 'stderr';

/** A run of consecutive console text from one stream. */
export interface ConsoleChunk {
  stream: ConsoleStream;
  text: string;
}

/** One check's console as the Studio holds it. */
export interface ToolCheckRun {
  /** `running` until the stream closes (or the request is refused). */
  state: 'running' | 'done';
  /** The command the server reported in its `start` event, once it arrives. */
  command: string | null;
  /** The files the check read, from the `start` event. */
  files: string[];
  /** The console so far, sanitized. */
  output: ConsoleChunk[];
  /** True once older output was dropped to stay under {@link MAX_CONSOLE_CHARS}. */
  truncated: boolean;
  /** The closing result, once it arrives. */
  result: ToolCheckResult | null;
  /** A refusal or transport failure (rate limit, not installed, network), in words. */
  error: string | null;
}

/** The most console text kept per check; the oldest is dropped first. */
export const MAX_CONSOLE_CHARS = 200_000;

// ---------------------------------------------------------------------------
// Declared checks
// ---------------------------------------------------------------------------

/** The `(tool, check)` a toolchain declaration names, or null when it names neither. */
export function toolCheckParams(tool: ExportTestTool): { tool: string; check: string } | null {
  const key = tool.params?.tool;
  const check = tool.params?.check;
  return typeof key === 'string' && key && typeof check === 'string' && check ? { tool: key, check } : null;
}

/** A stable id for one declared check (`buf lint`), used to key its console. */
export function toolCheckId(tool: ExportTestTool): string {
  const params = toolCheckParams(tool);
  return params ? `${params.tool} ${params.check}` : tool.label;
}

/** A fresh console for a run that is starting. */
export function startedRun(): ToolCheckRun {
  return { state: 'running', command: null, files: [], output: [], truncated: false, result: null, error: null };
}

// ---------------------------------------------------------------------------
// Stream decoding
// ---------------------------------------------------------------------------

/** Whether a parsed line is a console event this build understands. */
function isEvent(value: unknown): value is ToolCheckEvent {
  const event = (value as { event?: unknown } | null)?.event;
  return event === 'start' || event === 'output' || event === 'result';
}

/**
 * A decoder from network chunks to whole NDJSON events.
 *
 * A chunk may end mid-line (or mid-character — decode bytes with a streaming `TextDecoder` before
 * pushing), so the partial last line is held until the next chunk completes it. Lines that are not
 * JSON, or not an event, are skipped rather than failing the console.
 *
 * @returns `push(text)` → the events the text completes; `flush()` → any final unterminated event.
 */
export function createNdjsonDecoder(): { push: (text: string) => ToolCheckEvent[]; flush: () => ToolCheckEvent[] } {
  let pending = '';
  const parse = (lines: string[]): ToolCheckEvent[] => {
    const events: ToolCheckEvent[] = [];
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const value: unknown = JSON.parse(line);
        if (isEvent(value)) events.push(value);
      } catch {
        // A malformed line is dropped; the closing result still settles the run.
      }
    }
    return events;
  };
  return {
    push(text) {
      const lines = (pending + text).split('\n');
      pending = lines.pop() ?? '';
      return parse(lines);
    },
    flush() {
      const rest = pending;
      pending = '';
      return parse([rest]);
    },
  };
}

// ---------------------------------------------------------------------------
// Console text
// ---------------------------------------------------------------------------

// CSI (`ESC [ … final`), OSC (`ESC ] … BEL|ST`), and any other two-character escape.
const ANSI_SEQUENCE = /\u001b\[[0-?]*[ -/]*[@-~]|\u001b\][^\u0007\u001b]*(?:\u0007|\u001b\\)?|\u001b[@-_]?/g;
// C0 controls other than tab and newline, DEL, and C1 controls.
const CONTROL_CHARACTERS = /[\u0000-\u0008\u000b-\u001f\u007f-\u009f]/g;

/**
 * Tool output made safe to show verbatim: ANSI escape sequences and control characters removed.
 *
 * `\r\n` becomes `\n`, and a lone `\r` (a progress line redrawing itself) becomes a newline rather
 * than being dropped, so no output is silently merged into the line before it.
 *
 * @param text Raw text from the stream.
 * @returns The text with only printable characters, tabs and newlines.
 */
export function sanitizeConsoleText(text: string): string {
  return text
    .replace(ANSI_SEQUENCE, '')
    .replace(/\r\n?/g, '\n')
    .replace(CONTROL_CHARACTERS, '');
}

/**
 * Append a chunk to a console, merging it into the last run of the same stream and dropping the
 * oldest text past {@link MAX_CONSOLE_CHARS}.
 *
 * @param output The console so far (not mutated).
 * @param stream Which stream the chunk came from.
 * @param text The raw chunk; it is sanitized here.
 * @param limit The retention cap (tests pass a small one).
 * @returns The new console and whether anything was dropped.
 */
export function appendConsoleOutput(
  output: readonly ConsoleChunk[],
  stream: ConsoleStream,
  text: string,
  limit: number = MAX_CONSOLE_CHARS,
): { output: ConsoleChunk[]; truncated: boolean } {
  const clean = sanitizeConsoleText(text);
  if (!clean) return { output: [...output], truncated: false };
  const next = [...output];
  const last = next[next.length - 1];
  if (last && last.stream === stream) next[next.length - 1] = { stream, text: last.text + clean };
  else next.push({ stream, text: clean });

  let total = next.reduce((sum, chunk) => sum + chunk.text.length, 0);
  let truncated = false;
  while (total > limit && next.length > 0) {
    const excess = total - limit;
    const first = next[0];
    truncated = true;
    if (first.text.length <= excess) {
      next.shift();
      total -= first.text.length;
    } else {
      next[0] = { stream: first.stream, text: first.text.slice(excess) };
      total -= excess;
    }
  }
  return { output: next, truncated };
}

/**
 * Apply one stream event to a run.
 *
 * @param run The run so far.
 * @param event The event just decoded.
 * @returns The updated run (a `result` settles it).
 */
export function applyToolCheckEvent(run: ToolCheckRun, event: ToolCheckEvent): ToolCheckRun {
  switch (event.event) {
    case 'start':
      return { ...run, command: event.command, files: event.files };
    case 'output': {
      const { output, truncated } = appendConsoleOutput(run.output, event.stream, event.text);
      return { ...run, output, truncated: run.truncated || truncated };
    }
    case 'result':
      return {
        ...run,
        state: 'done',
        result: {
          tool: event.tool,
          check: event.check,
          label: event.label,
          status: event.status,
          exit_code: event.exit_code,
          duration_ms: event.duration_ms,
          command: event.command,
          files: event.files,
          message: event.message,
        },
      };
  }
}

/**
 * The console as plain text, for **Copy**: the command as a `$` prompt line, then the output.
 *
 * @param run The run.
 * @returns The transcript.
 */
export function consoleTranscript(run: ToolCheckRun): string {
  const lines: string[] = [];
  if (run.command) lines.push(`$ ${run.command}`);
  const body = run.output.map((chunk) => chunk.text).join('');
  if (body) lines.push(body.replace(/\n$/, ''));
  if (run.result) lines.push(`[${toolCheckStatusLabel(run.result)}]`);
  return lines.length ? `${lines.join('\n')}\n` : '';
}

// ---------------------------------------------------------------------------
// Status chips
// ---------------------------------------------------------------------------

/**
 * The status chip's words.
 *
 * @param result The run's result.
 * @returns e.g. `Passed`, `Failed · exit 100`, `Timed out`, `Not installed`, `Could not run`.
 */
export function toolCheckStatusLabel(result: Pick<ToolCheckResult, 'status' | 'exit_code'>): string {
  switch (result.status) {
    case 'passed':
      return 'Passed';
    case 'failed':
      return result.exit_code === null ? 'Failed' : `Failed · exit ${result.exit_code}`;
    case 'timed_out':
      return 'Timed out';
    case 'unavailable':
      return 'Not installed';
    default:
      return 'Could not run';
  }
}

/**
 * The status chip's tone (always paired with {@link toolCheckStatusLabel}).
 *
 * @param status The run's status.
 * @returns The Hive tone.
 */
export function toolCheckStatusTone(status: ToolCheckStatus): StatusTone {
  switch (status) {
    case 'passed':
      return 'ok';
    case 'failed':
      return 'danger';
    case 'timed_out':
      return 'warn';
    case 'unavailable':
      return 'outline';
    default:
      return 'warn';
  }
}

/**
 * Format a run's duration for the console header.
 *
 * @param ms Milliseconds.
 * @returns `120 ms` under a second, else seconds with one decimal (`3.4 s`).
 */
export function formatToolCheckDuration(ms: number): string {
  return ms < 1000 ? `${Math.max(0, Math.round(ms))} ms` : `${(ms / 1000).toFixed(1)} s`;
}

/**
 * The configuration a set of check results describes, as a stable key. Results attach to the
 * verify report of this configuration only; any change (another target, option, job) starts over.
 *
 * @returns A key string.
 */
export function toolCheckConfigKey(
  artifact: string | null,
  version: string | null,
  target: string | null,
  options: Record<string, unknown> | null | undefined,
  jobId: string | null,
): string {
  const sorted = options
    ? Object.fromEntries(Object.entries(options).sort(([a], [b]) => a.localeCompare(b)))
    : null;
  return JSON.stringify([artifact, version, target, sorted, jobId]);
}
