/**
 * Toolchain check console model — MFX-44.6 (#4372).
 *
 * - the NDJSON decoder turns arbitrary network chunks into whole events and skips junk lines;
 * - the console is ANSI-safe: escape sequences and control characters never reach the page;
 * - output merges per stream and is capped, oldest first;
 * - events fold into a run, and Copy gets a plain transcript;
 * - the status chip states each outcome in words, with a tone.
 */

import {
  appendConsoleOutput,
  applyToolCheckEvent,
  consoleTranscript,
  createNdjsonDecoder,
  formatToolCheckDuration,
  sanitizeConsoleText,
  startedRun,
  toolCheckConfigKey,
  toolCheckId,
  toolCheckParams,
  toolCheckStatusLabel,
  toolCheckStatusTone,
  type ToolCheckEvent,
} from '../src/app/components/ade/dashboard/export/exportToolChecks';
import type { ExportTestTool } from '../src/app/components/ade/dashboard/export/exportTestDrive';

const BUF_LINT: ExportTestTool = {
  kind: 'toolchain',
  label: 'buf lint',
  params: { tool: 'buf', check: 'lint' },
  server_side: true,
  available: true,
  unavailable_reason: null,
};

const RESULT: ToolCheckEvent = {
  event: 'result',
  tool: 'buf',
  check: 'lint',
  label: 'buf lint',
  status: 'failed',
  exit_code: 100,
  duration_ms: 140,
  command: 'buf lint',
  files: ['acme/v1/shop.proto'],
  message: 'buf lint exited 100.',
};

describe('declared checks', () => {
  it('reads the tool and check a declaration names', () => {
    expect(toolCheckParams(BUF_LINT)).toEqual({ tool: 'buf', check: 'lint' });
    expect(toolCheckId(BUF_LINT)).toBe('buf lint');
  });

  it('refuses a declaration without both', () => {
    const bare = { ...BUF_LINT, params: { tool: 'buf' } };
    expect(toolCheckParams(bare)).toBeNull();
    expect(toolCheckId(bare)).toBe('buf lint'); // falls back to the label
  });
});

describe('createNdjsonDecoder', () => {
  it('holds a partial line until the next chunk completes it', () => {
    const decoder = createNdjsonDecoder();
    const line = JSON.stringify({ event: 'output', stream: 'stdout', text: 'a.proto:1:1:x\n' });
    expect(decoder.push(line.slice(0, 10))).toEqual([]);
    expect(decoder.push(`${line.slice(10)}\n${JSON.stringify(RESULT).slice(0, 5)}`)).toEqual([
      { event: 'output', stream: 'stdout', text: 'a.proto:1:1:x\n' },
    ]);
    expect(decoder.push(JSON.stringify(RESULT).slice(5))).toEqual([]);
    expect(decoder.flush()).toEqual([RESULT]);
  });

  it('skips blank, malformed and unknown lines', () => {
    const decoder = createNdjsonDecoder();
    expect(decoder.push('\n{not json}\n{"event":"telemetry"}\n[1,2]\n')).toEqual([]);
  });
});

describe('sanitizeConsoleText', () => {
  it('removes colour codes, cursor moves and OSC titles', () => {
    expect(sanitizeConsoleText('\u001b[31merror\u001b[0m: bad')).toBe('error: bad');
    expect(sanitizeConsoleText('\u001b[2K\u001b[1Gdone')).toBe('done');
    expect(sanitizeConsoleText('\u001b]0;evil title\u0007ok')).toBe('ok');
    expect(sanitizeConsoleText('\u001b]8;;https://evil.example\u001b\\link\u001b]8;;\u001b\\')).toBe('link');
  });

  it('keeps tabs and newlines, turns carriage returns into newlines, drops other controls', () => {
    expect(sanitizeConsoleText('a\tb\r\nc\rd\u0000\u0008\u007f\u009be')).toBe('a\tb\nc\nde');
  });
});

describe('appendConsoleOutput', () => {
  it('merges a chunk into the last run of the same stream', () => {
    let { output } = appendConsoleOutput([], 'stdout', 'one ');
    ({ output } = appendConsoleOutput(output, 'stdout', 'two\n'));
    ({ output } = appendConsoleOutput(output, 'stderr', 'warn\n'));
    expect(output).toEqual([
      { stream: 'stdout', text: 'one two\n' },
      { stream: 'stderr', text: 'warn\n' },
    ]);
  });

  it('drops the oldest text past the cap and says so', () => {
    const first = appendConsoleOutput([], 'stdout', 'aaaa', 6);
    expect(first.truncated).toBe(false);
    const next = appendConsoleOutput(first.output, 'stderr', 'bbbb', 6);
    expect(next.truncated).toBe(true);
    expect(next.output).toEqual([
      { stream: 'stdout', text: 'aa' },
      { stream: 'stderr', text: 'bbbb' },
    ]);
    expect(appendConsoleOutput([], 'stdout', 'x'.repeat(9), 6).output).toEqual([{ stream: 'stdout', text: 'xxxxxx' }]);
  });

  it('ignores a chunk that sanitizes to nothing', () => {
    expect(appendConsoleOutput([], 'stdout', '\u001b[0m').output).toEqual([]);
  });
});

describe('runs', () => {
  const events: ToolCheckEvent[] = [
    { event: 'start', tool: 'buf', check: 'lint', label: 'buf lint', command: 'buf lint', files: ['acme/v1/shop.proto'] },
    { event: 'output', stream: 'stdout', text: '\u001b[1macme/v1/shop.proto:3:9\u001b[0m: Message name\n' },
    RESULT,
  ];

  it('folds the stream into a settled run', () => {
    const run = events.reduce(applyToolCheckEvent, startedRun());
    expect(run.state).toBe('done');
    expect(run.command).toBe('buf lint');
    expect(run.files).toEqual(['acme/v1/shop.proto']);
    expect(run.output).toEqual([{ stream: 'stdout', text: 'acme/v1/shop.proto:3:9: Message name\n' }]);
    expect(run.result).toMatchObject({ status: 'failed', exit_code: 100 });
    expect(run.result).not.toHaveProperty('event');
  });

  it('copies as a plain transcript', () => {
    const run = events.reduce(applyToolCheckEvent, startedRun());
    expect(consoleTranscript(run)).toBe('$ buf lint\nacme/v1/shop.proto:3:9: Message name\n[Failed · exit 100]\n');
    expect(consoleTranscript(startedRun())).toBe('');
  });
});

describe('status chips', () => {
  it.each([
    ['passed', 0, 'Passed', 'ok'],
    ['failed', 1, 'Failed · exit 1', 'danger'],
    ['failed', null, 'Failed', 'danger'],
    ['timed_out', null, 'Timed out', 'warn'],
    ['unavailable', null, 'Not installed', 'outline'],
    ['error', null, 'Could not run', 'warn'],
  ] as const)('%s / %s → %s', (status, exitCode, label, tone) => {
    expect(toolCheckStatusLabel({ status, exit_code: exitCode })).toBe(label);
    expect(toolCheckStatusTone(status)).toBe(tone);
  });

  it('formats durations', () => {
    expect(formatToolCheckDuration(140)).toBe('140 ms');
    expect(formatToolCheckDuration(3420)).toBe('3.4 s');
  });
});

describe('toolCheckConfigKey', () => {
  it('is independent of option order and changes with the job', () => {
    const a = toolCheckConfigKey('p', null, 'protobuf', { b: 1, a: 2 }, 'job-1');
    expect(toolCheckConfigKey('p', null, 'protobuf', { a: 2, b: 1 }, 'job-1')).toBe(a);
    expect(toolCheckConfigKey('p', null, 'protobuf', { a: 2, b: 1 }, 'job-2')).not.toBe(a);
  });
});
