/**
 * The Toolchain checks test-drive tab — MFX-44.6 (#4372).
 *
 * - each declared check is a row: installed ones get **Run**, a missing tool shows the server's reason
 *   and no Run;
 * - Run streams the server's NDJSON console into a monospace log (ANSI-safe), then a status chip and
 *   the outcome in words; Copy puts the transcript on the clipboard;
 * - a refusal (rate limit, not installed) is shown as the server says it;
 * - the hook posts the configuration (never the artifact), keys consoles by configuration, and aborts
 *   a run when the configuration changes;
 * - settled results attach to the verify report.
 */

import React from 'react';
import { act, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

import type { ExportTestTool } from '../src/app/components/ade/dashboard/export/exportTestDrive';
import {
  ToolCheckReport,
  ToolchainChecksConsole,
} from '../src/app/components/ade/dashboard/export/ToolchainChecksConsole';
import {
  applyToolCheckEvent,
  startedRun,
  type ToolCheckEvent,
  type ToolCheckRun,
} from '../src/app/components/ade/dashboard/export/exportToolChecks';
import {
  useExportToolChecks,
  type ToolCheckConfig,
} from '../src/app/components/ade/dashboard/export/useExportToolChecks';
import { TestDrivePanel } from '../src/app/components/ade/dashboard/export/TestDrivePanel';
import { writeA11yFixture } from './helpers/a11y-fixture-dump';

const check = (label: string, extra: Partial<ExportTestTool> = {}): ExportTestTool => {
  const [tool, name] = label.split(' ');
  return {
    kind: 'toolchain',
    label,
    params: { tool, check: name },
    server_side: true,
    available: true,
    unavailable_reason: null,
    ...extra,
  };
};

const BUF_LINT = check('buf lint');
const BUF_BUILD = check('buf build');
const TSP = check('tsp compile', {
  available: false,
  unavailable_reason: 'The tsp toolchain is not installed on this server.',
});

const STREAM: ToolCheckEvent[] = [
  { event: 'start', tool: 'buf', check: 'lint', label: 'buf lint', command: 'buf lint', files: ['acme/v1/shop.proto'] },
  { event: 'output', stream: 'stdout', text: 'acme/v1/shop.proto:3:9:Message name "widget" should be PascalCase, such as "Widget".\n' },
  { event: 'output', stream: 'stdout', text: '\u001b[33macme/v1/shop.proto:3:25:Field name "Name" should be lower_snake_case, such as "name".\u001b[0m\n' },
  {
    event: 'result', tool: 'buf', check: 'lint', label: 'buf lint', status: 'failed', exit_code: 100,
    duration_ms: 182, command: 'buf lint', files: ['acme/v1/shop.proto'], message: 'buf lint exited 100.',
  },
];

const PASSED: ToolCheckEvent[] = [
  { event: 'start', tool: 'buf', check: 'build', label: 'buf build', command: 'buf build', files: ['acme/v1/shop.proto'] },
  {
    event: 'result', tool: 'buf', check: 'build', label: 'buf build', status: 'passed', exit_code: 0,
    duration_ms: 64, command: 'buf build', files: ['acme/v1/shop.proto'], message: null,
  },
];

const settled = (events: ToolCheckEvent[]): ToolCheckRun => events.reduce(applyToolCheckEvent, startedRun());

/** A fetch response whose body yields `chunks` (strings) through `getReader()`, like a real stream. */
function streamResponse(chunks: string[]) {
  const encoder = new TextEncoder();
  let index = 0;
  return {
    ok: true,
    status: 200,
    body: {
      getReader: () => ({
        read: async () =>
          index < chunks.length ? { value: encoder.encode(chunks[index++]), done: false } : { value: undefined, done: true },
      }),
    },
    json: async () => ({}),
  };
}

const ndjson = (events: ToolCheckEvent[]) => events.map((event) => `${JSON.stringify(event)}\n`).join('');

describe('ToolchainChecksConsole', () => {
  it('offers Run for an installed check and the reason for a missing one', () => {
    const onRun = jest.fn();
    render(<ToolchainChecksConsole tools={[BUF_LINT, TSP]} runs={{}} onRun={onRun} />);
    expect(screen.getByTestId('toolchain-check-buf-lint')).toHaveTextContent('Installed on this server');
    fireEvent.click(screen.getByTestId('toolchain-run-buf-lint'));
    expect(onRun).toHaveBeenCalledWith(BUF_LINT);
    const tsp = screen.getByTestId('toolchain-check-tsp-compile');
    expect(tsp).toHaveTextContent('The tsp toolchain is not installed on this server.');
    expect(within(tsp).queryByRole('button')).toBeNull();
  });

  it('shows a running check without a second Run', () => {
    render(<ToolchainChecksConsole tools={[BUF_LINT]} runs={{ 'buf lint': startedRun() }} onRun={jest.fn()} />);
    expect(screen.getByTestId('toolchain-check-buf-lint')).toHaveTextContent('Running…');
    expect(screen.getByTestId('toolchain-run-buf-lint')).toBeDisabled();
    expect(screen.getByRole('log', { name: 'buf lint output' })).toHaveTextContent('Waiting for output…');
  });

  it('renders the streamed console, the exit chip and the outcome in words', () => {
    render(<ToolchainChecksConsole tools={[BUF_LINT]} runs={{ 'buf lint': settled(STREAM) }} onRun={jest.fn()} />);
    expect(screen.getByTestId('toolchain-status-buf-lint')).toHaveTextContent('Failed · exit 100');
    const log = screen.getByRole('log', { name: 'buf lint output' });
    expect(log).toHaveTextContent('Message name "widget" should be PascalCase');
    expect(log.textContent).not.toContain('\u001b'); // ANSI-safe
    expect(screen.getByTestId('toolchain-console-buf-lint')).toHaveTextContent('$ buf lint');
    expect(screen.getByTestId('toolchain-console-buf-lint')).toHaveTextContent('182 ms');
    expect(screen.getByTestId('toolchain-message-buf-lint')).toHaveTextContent('buf lint exited 100.');
    expect(screen.getByTestId('toolchain-run-buf-lint')).toHaveTextContent('Run again');
  });

  it('copies the transcript', async () => {
    const writeText = jest.fn(() => Promise.resolve());
    Object.assign(navigator, { clipboard: { writeText } });
    render(<ToolchainChecksConsole tools={[BUF_LINT]} runs={{ 'buf lint': settled(STREAM) }} onRun={jest.fn()} />);
    fireEvent.click(screen.getByTestId('toolchain-copy-buf-lint'));
    expect(writeText).toHaveBeenCalledWith(expect.stringMatching(/^\$ buf lint\n.*PascalCase.*\n\[Failed · exit 100\]\n$/s));
    await waitFor(() => expect(screen.getByTestId('toolchain-copy-buf-lint')).toHaveTextContent('Copied'));
  });

  it('shows a refusal as the server words it', () => {
    const refused: ToolCheckRun = { ...startedRun(), state: 'done', error: 'Too many toolchain checks in a short time.' };
    render(<ToolchainChecksConsole tools={[BUF_LINT]} runs={{ 'buf lint': refused }} onRun={jest.fn()} />);
    expect(screen.getByTestId('toolchain-status-buf-lint')).toHaveTextContent('Could not run');
    expect(screen.getByTestId('toolchain-message-buf-lint')).toHaveTextContent('Too many toolchain checks');
  });

  it('has no axe violations with a console open', async () => {
    const { container } = render(
      <ToolchainChecksConsole tools={[BUF_LINT, BUF_BUILD, TSP]} runs={{ 'buf lint': settled(STREAM) }} onRun={jest.fn()} />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe('ToolCheckReport', () => {
  it('lists each settled check under the verify report', () => {
    render(<ToolCheckReport results={[settled(STREAM).result!, settled(PASSED).result!]} />);
    const report = screen.getByTestId('toolcheck-report');
    expect(report).toHaveTextContent('Toolchain checks');
    expect(report).toHaveTextContent('buf lintFailed · exit 100acme/v1/shop.proto');
    expect(report).toHaveTextContent('buf buildPassed');
  });

  it('draws nothing before a check has run', () => {
    const { container } = render(<ToolCheckReport results={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe('useExportToolChecks', () => {
  const CONFIG: ToolCheckConfig = {
    artifact: 'proj-shop',
    version: 'rev-1',
    target: 'protobuf',
    options: { package: 'acme.v1' },
    jobId: 'job-1',
  };

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('posts the configuration (not the artifact) and streams events into the run', async () => {
    const body = ndjson(STREAM);
    const fetchMock = jest.fn(async () => streamResponse([body.slice(0, 40), body.slice(40, 200), body.slice(200)]));
    global.fetch = fetchMock as unknown as typeof fetch;
    const { result } = renderHook(() => useExportToolChecks(CONFIG));

    act(() => result.current.run(BUF_LINT));
    await waitFor(() => expect(result.current.runs['buf lint']?.state).toBe('done'));

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/export/verify/tool-checks/buf');
    expect(JSON.parse(String(init.body))).toEqual({
      artifact: 'proj-shop', version: 'rev-1', target: 'protobuf', options: { package: 'acme.v1' },
      check: 'lint', jobId: 'job-1',
    });
    const run = result.current.runs['buf lint'];
    expect(run.command).toBe('buf lint');
    expect(run.output.map((chunk) => chunk.text).join('')).toContain('lower_snake_case');
    expect(result.current.results).toEqual([expect.objectContaining({ label: 'buf lint', status: 'failed', exit_code: 100 })]);
  });

  it('reports a refusal with the server message', async () => {
    global.fetch = jest.fn(async () => ({
      ok: false,
      status: 503,
      body: null,
      json: async () => ({ success: false, error: 'The buf toolchain is not installed on this server.' }),
    })) as unknown as typeof fetch;
    const { result } = renderHook(() => useExportToolChecks(CONFIG));
    act(() => result.current.run(BUF_LINT));
    await waitFor(() => expect(result.current.runs['buf lint']?.state).toBe('done'));
    expect(result.current.runs['buf lint'].error).toBe('The buf toolchain is not installed on this server.');
    expect(result.current.results).toEqual([]);
  });

  it('says so when the stream ends without a result', async () => {
    global.fetch = jest.fn(async () => streamResponse([ndjson(STREAM.slice(0, 2))])) as unknown as typeof fetch;
    const { result } = renderHook(() => useExportToolChecks(CONFIG));
    act(() => result.current.run(BUF_LINT));
    await waitFor(() => expect(result.current.runs['buf lint']?.state).toBe('done'));
    expect(result.current.runs['buf lint'].error).toBe('The check stopped before reporting a result.');
  });

  it('starts over, aborting the run in flight, when the configuration changes', async () => {
    let signal: AbortSignal | undefined;
    global.fetch = jest.fn((_url: string, init: RequestInit) => {
      signal = init.signal ?? undefined;
      return new Promise(() => undefined); // never answers
    }) as unknown as typeof fetch;
    const { result, rerender } = renderHook((config: ToolCheckConfig) => useExportToolChecks(config), {
      initialProps: CONFIG,
    });
    act(() => result.current.run(BUF_LINT));
    expect(result.current.runs['buf lint']?.state).toBe('running');

    rerender({ ...CONFIG, options: { package: 'acme.v2' } });
    expect(signal?.aborted).toBe(true);
    expect(result.current.runs).toEqual({});
  });

  it('does nothing without a source or target', () => {
    const fetchMock = jest.fn();
    global.fetch = fetchMock as unknown as typeof fetch;
    const { result } = renderHook(() => useExportToolChecks({ ...CONFIG, target: null }));
    act(() => result.current.run(BUF_LINT));
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('the docs fixture', () => {
  it('renders a proto target with buf lint run and failed, buf build passed', () => {
    const { container } = render(
      <div className="xstd-stack">
        <ToolCheckReport results={[settled(STREAM).result!, settled(PASSED).result!]} />
        <TestDrivePanel
          tools={[BUF_LINT, BUF_BUILD]}
          targetKey="protobuf"
          renderers={{
            toolchain: (tab) => (
              <ToolchainChecksConsole
                tools={tab.tools}
                runs={{ 'buf lint': settled(STREAM), 'buf build': settled(PASSED) }}
                onRun={() => undefined}
              />
            ),
          }}
        />
      </div>,
    );
    expect(screen.getByTestId('toolchain-status-buf-build')).toHaveTextContent('Passed');
    writeA11yFixture('export-studio-toolchain-console', container.innerHTML);
  });
});
