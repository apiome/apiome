/**
 * CatalogImportDialog — a SOAP service URL in URL Import (MFI-13.6, #3793).
 *
 * A `?wsdl` URL (or a bare `.svc` endpoint) is read from `?singleWsdl` when the service offers it —
 * the description with every import inlined — and from `?wsdl` otherwise; the catalog item records
 * the URL that answered. A `.wsdl` file URL is fetched once, as entered.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import { CatalogImportDialog } from '../src/app/components/ade/dashboard/catalog/CatalogImportDialog';
import type { ImportSourceDescriptor } from '../src/app/components/ade/dashboard/importSourceCatalog';

const SERVICE = 'https://soap.example.com/Calculator.svc';
const WSDL_URL = `${SERVICE}?wsdl`;
const SINGLE_WSDL_URL = `${SERVICE}?singleWsdl`;
const FILE_URL = 'https://files.example.com/calculator.wsdl';

const WSDL =
  '<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/" name="Calculator" ' +
  'targetNamespace="urn:example:calculator"><wsdl:portType name="CalculatorPort"/></wsdl:definitions>';
const HELP_PAGE = '<html><body>You have created a service.</body></html>';

const SOURCES: ImportSourceDescriptor[] = [
  {
    key: 'wsdl',
    label: 'WSDL',
    description: 'Import a SOAP WSDL 1.1 or 2.0 service description.',
    icon: 'network',
    paradigm: 'rpc',
    input_kinds: ['file', 'url', 'paste', 'discovery', 'fileset'],
    supports_live_discovery: true,
    formats: ['wsdl', 'wsdl-2.0'],
    available: true,
  },
];

const DETECTION = {
  matched: true,
  detected: { format: 'wsdl', confidence: 0.97, reason: '`<wsdl:definitions>` root', importable: true },
};

/**
 * A routing fetch mock: the registry, detection, and the two remote documents. Each detection
 * request body is recorded so a test can assert what was detected.
 *
 * @param detected Collects the parsed body of every `/api/import/detect` request.
 * @param remote The remote URL → body map the URL intake fetches from.
 */
function mockFetch(detected: Array<Record<string, unknown>>, remote: Record<string, string>): jest.Mock {
  return jest.fn((input: unknown, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : String(input);
    if (url.includes('/api/import/sources')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ success: true, sources: SOURCES }) });
    }
    if (url.includes('/api/import/detect')) {
      detected.push(JSON.parse(String(init?.body ?? '{}')));
      return Promise.resolve({ ok: true, json: () => Promise.resolve(DETECTION) });
    }
    if (url in remote) {
      return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve(remote[url]) });
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
  }) as unknown as jest.Mock;
}

/** Open the dialog on URL Import, enter `url` and click **Fetch and detect**. */
async function fetchAndDetect(url: string): Promise<void> {
  render(<CatalogImportDialog open onClose={jest.fn()} onSuccess={jest.fn()} />);
  await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/api/import/sources', expect.anything()));
  fireEvent.click(screen.getByTestId('catalog-import-source-url'));
  fireEvent.change(screen.getByLabelText('Document URL'), { target: { value: url } });
  fireEvent.click(screen.getByRole('button', { name: /fetch and detect/i }));
  await waitFor(() => expect(screen.getByText(/Auto-detected:/i)).toBeInTheDocument());
}

/** The URLs the browser fetched directly (everything outside `/api/`). */
function remoteFetches(): string[] {
  return (global.fetch as unknown as jest.Mock).mock.calls
    .map((call) => String(call[0]))
    .filter((url) => !url.startsWith('/api/'));
}

describe('CatalogImportDialog — SOAP service URL (MFI-13.6)', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('reads a ?wsdl URL from ?singleWsdl when the service offers it', async () => {
    const detected: Array<Record<string, unknown>> = [];
    global.fetch = mockFetch(detected, { [SINGLE_WSDL_URL]: WSDL, [WSDL_URL]: WSDL }) as unknown as typeof fetch;

    await fetchAndDetect(WSDL_URL);

    expect(remoteFetches()).toEqual([SINGLE_WSDL_URL]);
    expect(detected).toHaveLength(1);
    expect(detected[0].text).toBe(WSDL);
    expect(detected[0].url).toBe(SINGLE_WSDL_URL);
  });

  it('falls back to ?wsdl when ?singleWsdl is not offered', async () => {
    const detected: Array<Record<string, unknown>> = [];
    global.fetch = mockFetch(detected, { [WSDL_URL]: WSDL }) as unknown as typeof fetch;

    await fetchAndDetect(WSDL_URL);

    expect(remoteFetches()).toEqual([SINGLE_WSDL_URL, WSDL_URL]);
    expect(detected[0].url).toBe(WSDL_URL);
  });

  it('reads a bare .svc endpoint, whose own page is HTML, from its description', async () => {
    const detected: Array<Record<string, unknown>> = [];
    global.fetch = mockFetch(detected, { [SERVICE]: HELP_PAGE, [SINGLE_WSDL_URL]: WSDL }) as unknown as typeof fetch;

    await fetchAndDetect(SERVICE);

    expect(remoteFetches()).toEqual([SINGLE_WSDL_URL]);
    expect(detected[0].text).toBe(WSDL);
  });

  it('fetches a .wsdl file URL once, as entered', async () => {
    const detected: Array<Record<string, unknown>> = [];
    global.fetch = mockFetch(detected, { [FILE_URL]: WSDL }) as unknown as typeof fetch;

    await fetchAndDetect(FILE_URL);

    expect(remoteFetches()).toEqual([FILE_URL]);
    expect(detected[0].url).toBe(FILE_URL);
  });

  it('reports the URL failing when neither description answers', async () => {
    const detected: Array<Record<string, unknown>> = [];
    global.fetch = mockFetch(detected, {}) as unknown as typeof fetch;

    render(<CatalogImportDialog open onClose={jest.fn()} onSuccess={jest.fn()} />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/api/import/sources', expect.anything()));
    fireEvent.click(screen.getByTestId('catalog-import-source-url'));
    fireEvent.change(screen.getByLabelText('Document URL'), { target: { value: WSDL_URL } });
    fireEvent.click(screen.getByRole('button', { name: /fetch and detect/i }));

    await waitFor(() => expect(screen.getByText(/Fetch failed with HTTP 404/i)).toBeInTheDocument());
    expect(detected).toHaveLength(0);
  });
});
