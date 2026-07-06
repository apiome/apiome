/**
 * useCatalogSourceContext — the catalog-item provenance the Export Studio Source step shows when
 * an export is launched from a catalog item (MFX-41.2, #4349).
 *
 * Covers: it fetches `/api/catalog/{itemId}` only while enabled; it maps the format/protocol/counts
 * off the item envelope; and — because the context is decorative — a failed or absent fetch leaves
 * it null without throwing.
 */

import { renderHook, waitFor } from '@testing-library/react';
import { jest } from '@jest/globals';
import { useCatalogSourceContext } from '../src/app/components/ade/dashboard/export/useCatalogSourceContext';

const ITEM = {
  id: 'cat-1',
  name: 'Acme gRPC API',
  sourceFormat: 'protobuf',
  protocol: 'grpc',
  summary: { services: 2, operations: 9, types: 14, channels: null },
};

function mockOk(item: unknown): jest.Mock {
  return jest.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve({ success: true, item }) }),
  ) as unknown as jest.Mock;
}

afterEach(() => jest.restoreAllMocks());

describe('useCatalogSourceContext (MFX-41.2, #4349)', () => {
  it('fetches the catalog item and maps its format, protocol, and counts', async () => {
    const fetchMock = mockOk(ITEM);
    global.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(() => useCatalogSourceContext(true, 'cat-1'));

    await waitFor(() => expect(result.current.context).not.toBeNull());
    expect(fetchMock).toHaveBeenCalledWith('/api/catalog/cat-1', expect.anything());
    expect(result.current.context).toEqual({
      sourceFormat: 'protobuf',
      protocol: 'grpc',
      summary: { services: 2, operations: 9, types: 14, channels: null },
    });
    expect(result.current.error).toBeNull();
  });

  it('does not fetch while disabled (a non-catalog source)', () => {
    const fetchMock = mockOk(ITEM);
    global.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(() => useCatalogSourceContext(false, 'cat-1'));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.context).toBeNull();
  });

  it('degrades to null context (never throws) when the fetch fails', async () => {
    global.fetch = jest.fn(() =>
      Promise.resolve({ ok: false, json: () => Promise.resolve({ success: false, error: 'nope' }) }),
    ) as unknown as typeof fetch;

    const { result } = renderHook(() => useCatalogSourceContext(true, 'cat-1'));

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.context).toBeNull();
  });

  it('tolerates a missing summary bag (each count becomes null)', async () => {
    global.fetch = mockOk({ id: 'cat-2', sourceFormat: 'graphql', protocol: 'graph' }) as unknown as typeof fetch;

    const { result } = renderHook(() => useCatalogSourceContext(true, 'cat-2'));

    await waitFor(() => expect(result.current.context).not.toBeNull());
    expect(result.current.context?.summary).toEqual({
      services: null,
      operations: null,
      types: null,
      channels: null,
    });
  });
});
