/**
 * `useArazzoWorkflowCount` — the probe that decides whether the project Versions page shows its
 * Workflows tab (COA-1.3, #7039).
 *
 * The count is read once per revision, a failed read counts as "no workflows" (no tab rather
 * than a tab that opens on an error), and a count read for one revision never shows on another.
 */

import { renderHook, waitFor } from '@testing-library/react';

import { useArazzoWorkflowCount } from '../src/app/components/ade/workflows/useArazzoWorkflowCount';
import { WORKFLOWS_RESPONSE } from './helpers/arazzo-workflows-fixture';

const originalFetch = global.fetch;

function respond(body: unknown, status = 200) {
  return Promise.resolve({ ok: status < 400, status, json: async () => body } as Response);
}

afterEach(() => {
  global.fetch = originalFetch;
});

describe('useArazzoWorkflowCount', () => {
  it('counts the revision’s workflows', async () => {
    global.fetch = jest.fn(() => respond({ success: true, workflows: WORKFLOWS_RESPONSE })) as unknown as typeof fetch;
    const { result } = renderHook(() => useArazzoWorkflowCount('rev-1'));
    expect(result.current).toBe(0);
    await waitFor(() => expect(result.current).toBe(2));
    expect(global.fetch).toHaveBeenCalledWith('/api/workflows/versions/rev-1');
  });

  it('reads nothing without a revision', () => {
    global.fetch = jest.fn() as unknown as typeof fetch;
    const { result } = renderHook(() => useArazzoWorkflowCount(null));
    expect(result.current).toBe(0);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('treats a failed read as no workflows', async () => {
    global.fetch = jest.fn(() => respond({ success: false, error: 'Version not found' }, 404)) as unknown as typeof fetch;
    const { result } = renderHook(() => useArazzoWorkflowCount('rev-1'));
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(result.current).toBe(0);
  });

  it('does not carry a count over to another revision', async () => {
    let resolveSecond: (value: Response) => void = () => {};
    global.fetch = jest
      .fn()
      .mockImplementationOnce(() => respond({ success: true, workflows: WORKFLOWS_RESPONSE }))
      .mockImplementationOnce(
        () => new Promise<Response>((resolve) => (resolveSecond = resolve))
      ) as unknown as typeof fetch;
    const { result, rerender } = renderHook(({ id }) => useArazzoWorkflowCount(id), { initialProps: { id: 'rev-1' } });
    await waitFor(() => expect(result.current).toBe(2));
    rerender({ id: 'rev-2' });
    expect(result.current).toBe(0);
    resolveSecond({ ok: true, status: 200, json: async () => ({ success: true, workflows: { workflows: [] } }) } as Response);
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
    expect(result.current).toBe(0);
  });
});
