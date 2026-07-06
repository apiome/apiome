/**
 * useExportVerify — the manual "Run verification" hook behind the Studio's Verify workbench
 * (MFX-42.1, #4354). Unlike the auto-fetching preview hook, verification is explicit: `run`
 * POSTs to `/api/export/verify`, and `reset` clears a stale verdict when the config changes.
 */

import { renderHook, act } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import { useExportVerify } from '../src/app/components/ade/dashboard/export/useExportVerify';

const RESULT = {
  success: true,
  artifact: 'proj-1',
  version: null,
  version_record_id: 'rev-1',
  version_label: '1.0.0',
  fidelity: { summary: { tier: 'lossless' } },
  validation: { verdict: 'valid', blocks_delivery: false },
  lint: null,
  verdict: 'clean',
};

/** A fetch mock whose verify response resolves only when `release()` is called (to test in-flight). */
function deferredFetch() {
  let release!: (value: unknown) => void;
  const pending = new Promise((resolve) => {
    release = resolve;
  });
  const mock = jest.fn(() => pending.then(() => ({ ok: true, json: () => Promise.resolve(RESULT) })));
  return { mock, release };
}

afterEach(() => jest.restoreAllMocks());

describe('useExportVerify', () => {
  it('is idle before any run', () => {
    global.fetch = jest.fn() as unknown as typeof fetch;
    const { result } = renderHook(() => useExportVerify('proj-1', null, 'openapi', null));
    expect(result.current.hasRun).toBe(false);
    expect(result.current.running).toBe(false);
    expect(result.current.result).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it('does nothing when no target is selected', async () => {
    const fetchMock = jest.fn();
    global.fetch = fetchMock as unknown as typeof fetch;
    const { result } = renderHook(() => useExportVerify('proj-1', null, null, null));
    await act(async () => {
      await result.current.run();
    });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.hasRun).toBe(false);
  });

  it('runs, exposes the settled result, and sends the changed options', async () => {
    const fetchMock = jest.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve(RESULT) }),
    );
    global.fetch = fetchMock as unknown as typeof fetch;
    const { result } = renderHook(() =>
      useExportVerify('proj-1', 'rev-1', 'proto', { package: 'com.example' }),
    );

    await act(async () => {
      await result.current.run();
    });

    expect(result.current.hasRun).toBe(true);
    expect(result.current.result?.verdict).toBe('clean');
    const body = JSON.parse((fetchMock.mock.calls[0][1] as { body: string }).body);
    expect(body).toEqual({
      artifact: 'proj-1',
      version: 'rev-1',
      target: 'proto',
      options: { package: 'com.example' },
    });
  });

  it('surfaces a failed run and keeps the gate closed (no result)', async () => {
    const fetchMock = jest.fn(() =>
      Promise.resolve({ ok: false, json: () => Promise.resolve({ error: 'boom' }) }),
    );
    global.fetch = fetchMock as unknown as typeof fetch;
    const { result } = renderHook(() => useExportVerify('proj-1', null, 'proto', null));
    await act(async () => {
      await result.current.run();
    });
    expect(result.current.error).toBe('boom');
    expect(result.current.result).toBeNull();
    expect(result.current.hasRun).toBe(true);
  });

  it('reset clears the result so a stale verdict cannot gate Generate', async () => {
    const fetchMock = jest.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve(RESULT) }),
    );
    global.fetch = fetchMock as unknown as typeof fetch;
    const { result } = renderHook(() => useExportVerify('proj-1', null, 'proto', null));
    await act(async () => {
      await result.current.run();
    });
    expect(result.current.result).not.toBeNull();

    act(() => result.current.reset());
    expect(result.current.result).toBeNull();
    expect(result.current.hasRun).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it('ignores an in-flight run superseded by reset', async () => {
    const { mock, release } = deferredFetch();
    global.fetch = mock as unknown as typeof fetch;
    const { result } = renderHook(() => useExportVerify('proj-1', null, 'proto', null));

    let runPromise!: Promise<void>;
    act(() => {
      runPromise = result.current.run();
    });
    expect(result.current.running).toBe(true);

    // Reset while the run is still in flight; the late response must not settle state.
    act(() => result.current.reset());
    await act(async () => {
      release(undefined);
      await runPromise;
    });
    expect(result.current.result).toBeNull();
    expect(result.current.hasRun).toBe(false);
    expect(result.current.running).toBe(false);
  });
});
