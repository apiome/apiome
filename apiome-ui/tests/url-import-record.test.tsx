/**
 * Recording a URL import for auto-refresh (RAR-6.1, #3538).
 *
 * Pins: the record body carries the project, the version, the URL, the importer kind and the
 * options the import used (never `dryRun`), and says whether the fetch used credentials; nothing is
 * recorded without a URL source or a project; sending is best-effort; and the URL Import panel hands
 * the dialog the URL, whether auth was used and the response type.
 */

import React, { createRef } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { describe, expect, jest, test } from '@jest/globals';

const fetchSpecificationFromUrl = jest.fn<(...args: unknown[]) => Promise<unknown>>();

jest.mock('@/app/utils/url-import', () => {
  const actual = jest.requireActual('@/app/utils/url-import') as Record<string, unknown>;
  return { ...actual, fetchSpecificationFromUrl: (...args: unknown[]) => fetchSpecificationFromUrl(...args) };
});

import UrlImportPanel, { type UrlImportPanelHandle } from '@/app/components/ade/dashboard/UrlImportPanel';
import { buildUrlImportRecord, recordUrlImport } from '@/app/utils/url-import-record';

const SOURCE = { url: 'https://specs.example.com/orders.json', authenticated: false, contentType: 'application/json' };
const RESULT = { projectId: 'p-1', versionId: 'v-1' };

describe('buildUrlImportRecord', () => {
  test('carries the target, the URL, the kind and the replayed options', () => {
    expect(buildUrlImportRecord(SOURCE, RESULT, 'openapi', { classPrefix: 'Ord', dryRun: false })).toEqual({
      projectId: 'p-1',
      versionId: 'v-1',
      url: 'https://specs.example.com/orders.json',
      sourceKind: 'openapi',
      contentType: 'application/json',
      options: { classPrefix: 'Ord' },
      authenticated: false,
    });
  });

  test('says when the fetch used credentials', () => {
    expect(buildUrlImportRecord({ ...SOURCE, authenticated: true }, RESULT, 'openapi', {})?.authenticated).toBe(true);
  });

  test('records nothing without a URL source or a project', () => {
    expect(buildUrlImportRecord(null, RESULT, 'openapi', {})).toBeNull();
    expect(buildUrlImportRecord({ ...SOURCE, url: '  ' }, RESULT, 'openapi', {})).toBeNull();
    expect(buildUrlImportRecord(SOURCE, { versionId: 'v-1' }, 'openapi', {})).toBeNull();
    expect(buildUrlImportRecord(SOURCE, undefined, 'openapi', {})).toBeNull();
  });

  test('leaves the version out when the result has none', () => {
    expect(buildUrlImportRecord(SOURCE, { projectId: 'p-1' }, 'arazzo', {})).not.toHaveProperty('versionId');
  });
});

describe('recordUrlImport', () => {
  const body = buildUrlImportRecord(SOURCE, RESULT, 'openapi', {})!;

  test('posts the body to the proxy', async () => {
    const fetchImpl = jest.fn(async () => ({ ok: true, status: 201 }));
    await expect(recordUrlImport(body, fetchImpl as unknown as typeof fetch)).resolves.toBe(true);
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/url-imports');
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual(body);
  });

  test('a refusal or a network error is reported, never thrown', async () => {
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => undefined);
    const refused = jest.fn(async () => ({ ok: false, status: 422 }));
    const down = jest.fn(async () => {
      throw new TypeError('offline');
    });
    await expect(recordUrlImport(body, refused as unknown as typeof fetch)).resolves.toBe(false);
    await expect(recordUrlImport(body, down as unknown as typeof fetch)).resolves.toBe(false);
    warn.mockRestore();
  });
});

describe('UrlImportPanel', () => {
  async function fetchWith(auth: 'None' | 'Bearer Token') {
    fetchSpecificationFromUrl.mockResolvedValue({
      success: true,
      content: '{"openapi":"3.1.0","info":{"title":"Orders","version":"1"},"paths":{}}',
      filename: 'orders.json',
      contentType: 'application/json',
    });
    const onFetched = jest.fn();
    const ref = createRef<UrlImportPanelHandle>();
    render(<UrlImportPanel ref={ref} onSpecificationFetched={onFetched} />);
    fireEvent.change(screen.getByPlaceholderText('https://api.example.com/openapi.yaml'), {
      target: { value: ' https://specs.example.com/orders.json ' },
    });
    fireEvent.click(screen.getByLabelText(auth));
    if (auth === 'Bearer Token') {
      fireEvent.change(screen.getByPlaceholderText('Enter your bearer token'), { target: { value: 'secret' } });
    }
    await act(async () => {
      await ref.current!.testUrl();
    });
    return onFetched;
  }

  test('hands over the URL, no auth and the response type', async () => {
    const onFetched = await fetchWith('None');
    expect(onFetched).toHaveBeenCalledTimes(1);
    expect(onFetched.mock.calls[0][3]).toEqual({
      url: 'https://specs.example.com/orders.json',
      authenticated: false,
      contentType: 'application/json',
    });
  });

  test('marks a fetch with credentials as authenticated, without the credential', async () => {
    const onFetched = await fetchWith('Bearer Token');
    const source = onFetched.mock.calls[0][3] as Record<string, unknown>;
    expect(source.authenticated).toBe(true);
    expect(JSON.stringify(source)).not.toContain('secret');
  });
});
