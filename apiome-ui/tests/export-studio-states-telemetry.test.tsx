/**
 * Export studio's non-happy-path states and usage telemetry — MFX-46.5 (#4383).
 *
 *  - **Telemetry:** `trackStudioEvent` posts one whitelisted event to `/api/export/studio-metrics` and
 *    swallows failures; the studio fires `target_chosen`, test-drive opens and runs, and view changes.
 *  - **Registry unreachable:** `useExportTargets` keeps each source's last good list for the session and
 *    returns it (`stale`) when the service cannot be reached — never for a refusal about the source; the
 *    notice says so and retries.
 *  - **States:** the Target step's loading / no targets / nothing chosen / retry, a test-drive tab with
 *    nothing to show, a picture with nothing to draw.
 */

import React from 'react';
import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { describe, expect, it, jest, beforeEach } from '@jest/globals';

jest.mock('@monaco-editor/react', () => ({ __esModule: true, default: () => <div /> }));
jest.mock('sonner', () => ({ __esModule: true, toast: Object.assign(jest.fn(), { success: jest.fn(), error: jest.fn() }) }));

import {
  isStudioTestTool,
  isStudioViz,
  trackStudioEvent,
} from '../src/app/components/ade/dashboard/export/studioTelemetry';
import {
  isRegistryUnreachable,
  lastTargetsKey,
  readLastTargets,
  saveLastTargets,
  useExportTargets,
} from '../src/app/components/ade/dashboard/export/useExportTargets';
import { StaleTargetsNotice } from '../src/app/components/ade/dashboard/export/StaleTargetsNotice';
import { TestDrivePanel } from '../src/app/components/ade/dashboard/export/TestDrivePanel';
import { ArtifactVizPanel } from '../src/app/components/ade/dashboard/export/ArtifactViewSwitch';
import { ExportStudio } from '../src/app/components/ade/dashboard/export/ExportStudio';
import { __resetExportJobTrackerForTests } from '../src/app/components/ade/dashboard/export/exportJobTracker';
import type { ExportTargetEntry, ExportTargetsResponse } from '../src/app/components/ade/dashboard/export/exportTargetCatalog';

function entry(key: string, label: string): ExportTargetEntry {
  return {
    descriptor: {
      key, format: key, label, description: `Export as ${label}.`, icon: 'file-json', paradigm: 'rest',
      multi_file: false, needs_toolchain: false, available: true, unavailable_reason: null,
    },
    capability_profile: { operations: true },
    options_schema: { properties: {} },
    default_options: {},
    fidelity: { tier: 'lossless', preserved_percent: 100, total: 1, preserved: 1, dropped: 0, approximated: 0, synthesized: 0 },
  } as ExportTargetEntry;
}

const TARGETS: ExportTargetsResponse = {
  artifact: 'proj-1', version: null, version_record_id: 'rev-1', version_label: '1.2.0',
  targets: [entry('openapi', 'OpenAPI 3.1'), entry('graphql', 'GraphQL SDL')],
};

type Answer = { status: number; body: unknown };
const ok = (body: unknown): Answer => ({ status: 200, body });

/** A fetch mock answering by URL prefix, recording every call. */
function mockFetch(routes: Record<string, Answer | (() => Answer)>) {
  const calls: { url: string; body?: unknown }[] = [];
  global.fetch = jest.fn((input: unknown, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const match = Object.keys(routes).find((prefix) => url.startsWith(prefix));
    const route = match ? routes[match] : { status: 404, body: { success: false } };
    const answer = typeof route === 'function' ? route() : route;
    return Promise.resolve({ ok: answer.status < 400, status: answer.status, json: () => Promise.resolve(answer.body) });
  }) as unknown as typeof fetch;
  return calls;
}

const events = (calls: { url: string; body?: unknown }[]) =>
  calls.filter((call) => call.url === '/api/export/studio-metrics').map((call) => call.body);

beforeEach(() => {
  __resetExportJobTrackerForTests();
  window.sessionStorage.clear();
});

// ===========================================================================
// Telemetry
// ===========================================================================

describe('trackStudioEvent', () => {
  it('posts one whitelisted event with its surface', async () => {
    const calls = mockFetch({ '/api/export/studio-metrics': ok({ success: true }) });
    await trackStudioEvent({ kind: 'verify_verdict', verdict: 'lossy' });
    await trackStudioEvent({ kind: 'target_chosen', target: 'graphql' }, 'dialog');
    expect(events(calls)).toEqual([
      { kind: 'verify_verdict', verdict: 'lossy', surface: 'studio' },
      { kind: 'target_chosen', target: 'graphql', surface: 'dialog' },
    ]);
  });

  it('never throws when the post fails', async () => {
    global.fetch = jest.fn(() => Promise.reject(new Error('offline'))) as unknown as typeof fetch;
    await expect(trackStudioEvent({ kind: 'viz_used', view: 'erd' })).resolves.toBeUndefined();
  });

  it('records only the known tools and views', () => {
    expect(isStudioTestTool('graphiql')).toBe(true);
    expect(isStudioTestTool('postman-runner')).toBe(false);
    expect(isStudioViz('service-map')).toBe(true);
    expect(isStudioViz('text')).toBe(false);
  });
});

// ===========================================================================
// The registry is unreachable: the last list, with a retry
// ===========================================================================

describe('the last good targets list', () => {
  it('is kept per source and read back', () => {
    expect(readLastTargets('proj-1', null)).toBeNull();
    saveLastTargets('proj-1', null, TARGETS);
    expect(readLastTargets('proj-1', null)?.response.targets).toHaveLength(2);
    expect(readLastTargets('proj-1', 'rev-2')).toBeNull();
    window.sessionStorage.setItem(lastTargetsKey('proj-2'), '{not json');
    expect(readLastTargets('proj-2')).toBeNull();
  });

  it('stands in only when the service cannot be reached', () => {
    expect(isRegistryUnreachable(null, null)).toBe(true);
    expect(isRegistryUnreachable(503, null)).toBe(true);
    expect(isRegistryUnreachable(404, null)).toBe(false);
    expect(isRegistryUnreachable(500, 'source-not-captured')).toBe(false);
  });

  it('is returned, marked stale, when a later load fails — and an error when none was kept', async () => {
    let down = false;
    mockFetch({ '/api/export/targets': () => (down ? { status: 503, body: { success: false, error: 'Bad gateway' } } : ok(TARGETS)) });
    const { result } = renderHook(() => useExportTargets(true, 'proj-1', null));
    await waitFor(() => expect(result.current.response?.targets).toHaveLength(2));
    expect(result.current.stale).toBeNull();
    down = true;
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.stale).not.toBeNull());
    expect(result.current.error).toBeNull();
    expect(result.current.response?.targets).toHaveLength(2);

    const other = renderHook(() => useExportTargets(true, 'proj-9', null));
    await waitFor(() => expect(other.result.current.error).toBe('Bad gateway'));
    expect(other.result.current.response).toBeNull();
  });

  it('is not used for a refusal about the source', async () => {
    saveLastTargets('proj-1', null, TARGETS);
    mockFetch({ '/api/export/targets': { status: 404, body: { success: false, error: 'No such version' } } });
    const { result } = renderHook(() => useExportTargets(true, 'proj-1', null));
    await waitFor(() => expect(result.current.error).toBe('No such version'));
    expect(result.current.stale).toBeNull();
  });

  it('says how old the list is and retries', () => {
    const retry = jest.fn();
    render(<StaleTargetsNotice savedAt="2026-11-05T09:30:00Z" onRetry={retry} />);
    expect(screen.getByTestId('export-targets-stale')).toHaveTextContent(/couldn.t be reached.*fidelity may be out of date/);
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(retry).toHaveBeenCalled();
  });
});

// ===========================================================================
// States and telemetry in the studio's panels
// ===========================================================================

describe('Test drive', () => {
  const tools = [
    { kind: 'swagger-ui', label: 'Swagger UI', available: true },
    { kind: 'graphiql', label: 'GraphiQL', available: true },
  ] as Parameters<typeof TestDrivePanel>[0]['tools'];

  it('says when a tab has nothing to show yet, and reports the tabs opened', () => {
    const onOpen = jest.fn();
    render(<TestDrivePanel tools={tools} targetKey="openapi" renderers={{ 'swagger-ui': () => null, graphiql: () => <p>ok</p> }}
      onOpen={onOpen} />);
    expect(screen.getByTestId('test-drive-empty')).toHaveTextContent('Nothing to test drive yet');
    expect(onOpen).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('test-drive-tab-graphiql'));
    expect(onOpen).toHaveBeenCalledWith('graphiql');
    expect(screen.queryByTestId('test-drive-empty')).not.toBeInTheDocument();
  });
});

describe('Visualizations', () => {
  const props = { modes: [], selectedEntityKey: null, onSelectEntityKey: () => undefined };

  it('says there is nothing to draw instead of a blank panel', () => {
    const { rerender } = render(<ArtifactVizPanel view="erd" relational={null} {...props} />);
    expect(screen.getByTestId('artifact-viz-empty')).toHaveTextContent('Nothing to draw');
    rerender(<ArtifactVizPanel view="service-map" views={{ 'service-map': { mode: 'service-map', nodes: [], edges: [] } }} {...props} />);
    expect(screen.getByTestId('artifact-viz-empty')).toBeInTheDocument();
    rerender(<ArtifactVizPanel view="text" {...props} />);
    expect(screen.queryByTestId('artifact-viz-empty')).not.toBeInTheDocument();
  });
});

describe('the Target step', () => {
  async function openTarget(routes: Record<string, Answer | (() => Answer)>) {
    const calls = mockFetch({ '/api/export/studio-metrics': ok({ success: true }), ...routes });
    render(<ExportStudio artifact="proj-1" version="rev-1" initialStep="target" workspaceName="Acme" />);
    return calls;
  }

  it('asks for a target, and reports the one chosen', async () => {
    const calls = await openTarget({ '/api/export/targets': ok({ success: true, ...TARGETS }) });
    expect(await screen.findByTestId('export-studio-choose-target')).toHaveTextContent('Choose a target to continue.');
    fireEvent.click(await screen.findByText('GraphQL SDL'));
    await waitFor(() => expect(events(calls)).toContainEqual({ kind: 'target_chosen', target: 'graphql', mode: 'single', surface: 'studio' }));
    expect(screen.queryByTestId('export-studio-choose-target')).not.toBeInTheDocument();
  });

  it('says when no target can take this source', async () => {
    await openTarget({ '/api/export/targets': ok({ success: true, ...TARGETS, targets: [] }) });
    expect(await screen.findByTestId('export-studio-no-targets')).toHaveTextContent('No export targets for this source');
  });

  it('offers Retry when the targets cannot load, and recovers', async () => {
    let down = true;
    await openTarget({
      '/api/export/targets': () => (down ? { status: 503, body: { success: false, error: 'Bad gateway' } } : ok({ success: true, ...TARGETS })),
    });
    const retry = await screen.findByTestId('export-studio-retry-targets');
    down = false;
    fireEvent.click(retry);
    // A link that could not be restored stays on Source; the retried load fills it in.
    expect(await screen.findByText(/export targets available/)).toBeInTheDocument();
    expect(screen.queryByTestId('export-studio-retry-targets')).not.toBeInTheDocument();
  });

  it('keeps the last list, marked stale, when the service goes away', async () => {
    saveLastTargets('proj-1', 'rev-1', { ...TARGETS, version: 'rev-1' });
    await openTarget({ '/api/export/targets': { status: 502, body: { success: false, error: 'Bad gateway' } } });
    expect(await screen.findByTestId('export-targets-stale')).toBeInTheDocument();
    expect(await screen.findByText('GraphQL SDL')).toBeInTheDocument();
    expect(screen.queryByTestId('export-studio-error')).not.toBeInTheDocument();
  });
});

/**
 * The docs fixture (`apiome-docs/screens.json`: `export-studio-targets-stale`): the Target step while the
 * export targets can't be reached, showing the list kept from earlier. Written into
 * `e2e/fixtures/hive-export-studio/` when `EXPORT_STUDIO_FIXTURE_DUMP=1`.
 */
describe('the docs fixtures', () => {
  it('writes the Target step with the last list kept', async () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const fs = require('node:fs') as typeof import('node:fs');
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const path = require('node:path') as typeof import('node:path');
    const wide = {
      ...TARGETS,
      version: 'rev-1',
      targets: [
        entry('openapi', 'OpenAPI 3.1'), entry('graphql', 'GraphQL SDL'), entry('proto3', 'Protocol Buffers'),
        entry('avro', 'Apache Avro'), entry('asyncapi', 'AsyncAPI 3'), entry('json-schema', 'JSON Schema'),
      ],
    };
    window.sessionStorage.setItem(lastTargetsKey('proj-1', 'rev-1'), JSON.stringify({ savedAt: '2026-11-05T09:30:00', response: wide }));
    mockFetch({
      '/api/export/studio-metrics': ok({ success: true }),
      '/api/export/targets': { status: 502, body: { success: false, error: 'Bad gateway' } },
      '/api/export/jobs?': ok({ success: true, jobs: [], total: 0 }),
    });
    render(<ExportStudio artifact="proj-1" artifactLabel="Pet Store API" version="rev-1" initialStep="target" workspaceName="Acme" />);
    await screen.findByTestId('export-targets-stale');
    await screen.findByText('Apache Avro');
    const html = (document.querySelector('.page') as HTMLElement).outerHTML;
    expect(html.length).toBeGreaterThan(0);
    if (process.env.EXPORT_STUDIO_FIXTURE_DUMP !== '1') return;
    const out = path.join(__dirname, '..', 'e2e', 'fixtures', 'hive-export-studio');
    fs.mkdirSync(out, { recursive: true });
    fs.writeFileSync(path.join(out, 'targets-stale.html'), html);
  });
});
