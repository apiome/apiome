/**
 * Document store page in the admin console (COA-5.9, #7085).
 *
 * * `lib/admin-document-store.ts` — byte/duration formatting and the per-backend Settings rows.
 * * `lib/auth/admin-document-store-proxy.ts` — forwards to `/v1/admin/document-store[/test]` with
 *   the verified session and relays the upstream reply.
 * * `DocumentStoreClient` (RTL, mocked `/api/admin/document-store` proxy) — status, settings,
 *   usage, the startup-fallback notice, **Test connection** and its per-step result, and the
 *   expired-session and unreachable-server messages.
 *
 * The docs screenshot `admin-document-store` (`apiome-docs/screens.json`) is captured from the
 * dump the last test writes:
 * `A11Y_FIXTURE_DUMP=1 npx jest tests/admin-document-store.test.tsx -t "docs fixture"`.
 */
import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import DocumentStoreClient from '../src/app/admin/dashboard/document-store/DocumentStoreClient';
import {
  formatBytes,
  formatSeconds,
  formatWhen,
  settingRows,
  type DocumentStoreProbeResult,
  type DocumentStoreStatus,
} from '../lib/admin-document-store';
import { proxyGetDocumentStore, proxyTestDocumentStore } from '../lib/auth/admin-document-store-proxy';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), refresh: jest.fn() }),
  usePathname: () => '/admin/dashboard/document-store',
}));

/** An S3 store on a MinIO-style endpoint, reachable, with a verified index. */
function makeStatus(overrides: Partial<DocumentStoreStatus> = {}): DocumentStoreStatus {
  return {
    backend: 's3',
    configuredBackend: 's3',
    fallback: false,
    fallbackReason: null,
    backends: ['db', 's3', 'filesystem'],
    bucket: 'northwind-apiome-documents',
    prefix: 'apiome',
    region: 'eu-west-1',
    endpointUrl: null,
    addressingStyle: 'auto',
    path: null,
    encryption: 'sse-kms',
    kmsKeyId: 'alias/apiome-documents',
    credentials: 'default-chain',
    presignTtlSeconds: 300,
    maxObjectBytes: null,
    health: { ok: true, checkedAt: 1_795_600_000, error: null },
    usage: {
      objects: 12_480,
      bytes: 3_489_660_928,
      byBackend: [
        { backend: 'db', objects: 312, bytes: 9_437_184 },
        { backend: 's3', objects: 12_168, bytes: 3_480_223_744 },
      ],
      integrity: { lastVerifiedAt: '2026-11-21T03:00:00Z', verifiedObjects: 12_168 },
    },
    ...overrides,
  };
}

const PASSED: DocumentStoreProbeResult = {
  ok: true,
  backend: 's3',
  checkedAt: 1_795_600_100,
  durationMs: 142.6,
  steps: [
    { name: 'write', ok: true, skipped: false, durationMs: 88.1, error: null },
    { name: 'read', ok: true, skipped: false, durationMs: 31.4, error: null },
    { name: 'delete', ok: true, skipped: false, durationMs: 22.9, error: null },
  ],
};

/** JSON `Response` stand-in. */
function reply(status: number, body: unknown): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as unknown as Response;
}

/** Route the mocked proxy: GET status, POST test. */
function mockFetch(statusBody: unknown, probeBody: unknown = PASSED, statusCode = 200, probeCode = 200) {
  const fetchMock = jest.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/test') && init?.method === 'POST') return reply(probeCode, probeBody);
    return reply(statusCode, statusBody);
  });
  global.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

afterEach(() => {
  jest.restoreAllMocks();
});

// ---------------------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------------------

describe('document store helpers', () => {
  it('formats bytes with binary units', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(1536)).toBe('1.5 KiB');
    expect(formatBytes(33_554_432)).toBe('32 MiB');
    expect(formatBytes(3_489_660_928)).toBe('3.3 GiB');
    expect(formatBytes(Number.NaN)).toBe('0 B');
  });

  it('formats durations in the largest whole unit', () => {
    expect(formatSeconds(45)).toBe('45 seconds');
    expect(formatSeconds(60)).toBe('1 minute');
    expect(formatSeconds(300)).toBe('5 minutes');
    expect(formatSeconds(7200)).toBe('2 hours');
  });

  it('formats missing or invalid timestamps with the fallback', () => {
    expect(formatWhen(null)).toBe('Never');
    expect(formatWhen('not a date', '—')).toBe('—');
    expect(formatWhen(0)).not.toBe('Never');
  });

  it('lists only the settings of the active backend, never a credential', () => {
    const s3 = settingRows(makeStatus());
    expect(s3.map((row) => row.label)).toEqual([
      'Backend',
      'Bucket',
      'Region',
      'Endpoint',
      'Addressing style',
      'Encryption',
      'Credentials',
      'Download link lifetime',
      'Prefix',
    ]);
    expect(s3.find((row) => row.label === 'Endpoint')?.value).toBe('AWS S3');
    expect(s3.find((row) => row.label === 'Encryption')?.value).toBe('SSE-KMS · alias/apiome-documents');
    expect(s3.find((row) => row.label === 'Credentials')?.value).toBe('Default credential chain or IAM role');

    const fs = settingRows(makeStatus({ backend: 'filesystem', path: '/var/lib/apiome/documents', prefix: '' }));
    expect(fs).toEqual([
      { label: 'Backend', value: 'Filesystem' },
      { label: 'Directory', value: '/var/lib/apiome/documents', mono: true },
      { label: 'Prefix', value: '(bucket root)', mono: false },
    ]);

    const db = settingRows(makeStatus({ backend: 'db', maxObjectBytes: 33_554_432 }));
    expect(db.find((row) => row.label === 'Largest object')?.value).toBe('32 MiB');
  });
});

// ---------------------------------------------------------------------------------------
// Proxy
// ---------------------------------------------------------------------------------------

describe('document store proxy', () => {
  it('forwards GET and POST with the admin session and relays the reply', async () => {
    const fetchImpl = jest.fn(async () => reply(200, { ok: true })) as unknown as typeof fetch;
    await expect(proxyGetDocumentStore('token-1', fetchImpl)).resolves.toEqual({ status: 200, body: { ok: true } });
    await proxyTestDocumentStore('token-1', fetchImpl);
    const calls = (fetchImpl as unknown as jest.Mock).mock.calls;
    expect(calls[0][0]).toMatch(/\/admin\/document-store$/);
    expect(calls[0][1]).toMatchObject({ method: 'GET', headers: { 'X-Admin-Session': 'token-1' } });
    expect(calls[1][0]).toMatch(/\/admin\/document-store\/test$/);
    expect(calls[1][1]).toMatchObject({ method: 'POST' });
  });

  it('answers 502 when apiome-rest cannot be reached', async () => {
    const fetchImpl = jest.fn(async () => {
      throw new Error('ECONNREFUSED');
    }) as unknown as typeof fetch;
    const result = await proxyGetDocumentStore('token-1', fetchImpl);
    expect(result.status).toBe(502);
  });
});

// ---------------------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------------------

describe('DocumentStoreClient', () => {
  it('shows the backend, its health, settings and usage', async () => {
    mockFetch(makeStatus());
    render(<DocumentStoreClient />);
    const status = await screen.findByTestId('document-store-status');
    expect(within(status).getByRole('heading', { name: 'S3-compatible bucket' })).toBeInTheDocument();
    expect(within(status).getByText('Reachable')).toBeInTheDocument();

    const settings = screen.getByTestId('document-store-settings');
    expect(within(settings).getByText('northwind-apiome-documents')).toBeInTheDocument();
    expect(within(settings).getByText('apiome/')).toBeInTheDocument();

    const usage = screen.getByTestId('document-store-usage');
    expect(within(usage).getByText('12,480')).toBeInTheDocument();
    expect(within(usage).getByText('3.3 GiB')).toBeInTheDocument();
    expect(within(usage).getByText(/12,168 verified/)).toBeInTheDocument();
    expect(within(usage).getAllByTestId('document-store-backend-row')).toHaveLength(2);
    expect(screen.queryByTestId('document-store-fallback')).not.toBeInTheDocument();
  });

  it('reports an unreachable store with its redacted error', async () => {
    mockFetch(
      makeStatus({ health: { ok: false, checkedAt: 1_795_600_000, error: 'The document store could not reach bucket.' } }),
    );
    render(<DocumentStoreClient />);
    const status = await screen.findByTestId('document-store-status');
    expect(within(status).getByText('Unreachable')).toBeInTheDocument();
    expect(within(status).getByRole('alert')).toHaveTextContent('could not reach bucket');
  });

  it('explains a startup fallback to the database store', async () => {
    mockFetch(
      makeStatus({
        backend: 'db',
        configuredBackend: 's3',
        fallback: true,
        fallbackReason: "The document store could not reach bucket 'northwind' (NoSuchBucket).",
        maxObjectBytes: 33_554_432,
      }),
    );
    render(<DocumentStoreClient />);
    const notice = await screen.findByTestId('document-store-fallback');
    expect(notice).toHaveTextContent('the configured S3-compatible bucket is not usable');
    expect(notice).toHaveTextContent('NoSuchBucket');
  });

  it('says when no object has been verified and when the index is unreadable', async () => {
    mockFetch(
      makeStatus({
        usage: { objects: 0, bytes: 0, byBackend: [], integrity: { lastVerifiedAt: null, verifiedObjects: 0 } },
      }),
    );
    const { unmount } = render(<DocumentStoreClient />);
    expect(await screen.findByText('No object has been verified yet')).toBeInTheDocument();
    unmount();

    mockFetch(makeStatus({ usage: null }));
    render(<DocumentStoreClient />);
    expect(await screen.findByText(/The document index could not be read/)).toBeInTheDocument();
  });

  it('runs Test connection and lists each step', async () => {
    const fetchMock = mockFetch(makeStatus());
    render(<DocumentStoreClient />);
    await screen.findByTestId('document-store-status');
    fireEvent.click(screen.getByRole('button', { name: 'Test connection' }));
    const probe = await screen.findByTestId('document-store-probe');
    expect(within(probe).getByText('Passed')).toBeInTheDocument();
    expect(within(probe).getByTestId('probe-step-write')).toHaveTextContent('Write a probe object — 88 ms');
    expect(within(probe).getByTestId('probe-step-delete')).toHaveTextContent('Delete it');
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(post?.[0]).toBe('/api/admin/document-store/test');
    // The test refreshes the status afterwards.
    await waitFor(() => expect(fetchMock.mock.calls.filter(([, init]) => init?.method !== 'POST')).toHaveLength(2));
  });

  it('shows a failed step and the skipped ones', async () => {
    mockFetch(makeStatus(), {
      ok: false,
      backend: 's3',
      checkedAt: 1_795_600_100,
      durationMs: 12,
      steps: [
        { name: 'write', ok: false, skipped: false, durationMs: 11.2, error: 'AccessDenied: Access Denied' },
        { name: 'read', ok: false, skipped: true, durationMs: 0, error: null },
        { name: 'delete', ok: false, skipped: true, durationMs: 0, error: null },
      ],
    });
    render(<DocumentStoreClient />);
    await screen.findByTestId('document-store-status');
    fireEvent.click(screen.getByRole('button', { name: 'Test connection' }));
    const probe = await screen.findByTestId('document-store-probe');
    expect(within(probe).getByText('Failed')).toBeInTheDocument();
    expect(within(probe).getByTestId('probe-step-write')).toHaveTextContent('AccessDenied');
    expect(within(probe).getByTestId('probe-step-read')).toHaveTextContent('skipped');
  });

  it('explains an expired session', async () => {
    mockFetch({ error: 'forbidden' }, PASSED, 403);
    render(<DocumentStoreClient />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Your admin session has expired');
    expect(screen.getByRole('button', { name: 'Test connection' })).toBeDisabled();
  });

  it('explains an unreachable server', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('down')) as unknown as typeof fetch;
    render(<DocumentStoreClient />);
    expect(await screen.findByRole('alert')).toHaveTextContent('the server could not be reached');
  });
});

// ---------------------------------------------------------------------------------------
// The docs fixture
// ---------------------------------------------------------------------------------------

describe('the docs fixture', () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { liveMarkup, writeA11yFixture } = require('./helpers/a11y-fixture-dump') as typeof import('./helpers/a11y-fixture-dump');
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const AdminSidebar = require('../src/app/admin/dashboard/AdminSidebar').default as React.ComponentType;

  it('renders the S3 store after a passed connection test', async () => {
    mockFetch(makeStatus());
    render(
      <div className="flex h-screen overflow-hidden bg-slate-100 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
        <AdminSidebar />
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <DocumentStoreClient />
        </div>
      </div>,
    );
    await screen.findByTestId('document-store-status');
    fireEvent.click(screen.getByRole('button', { name: 'Test connection' }));
    await screen.findByTestId('document-store-probe');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Refresh' })).toBeEnabled());
    expect(screen.getByRole('button', { name: /Document store/ })).toBeInTheDocument();
    writeA11yFixture('admin-document-store', liveMarkup(document.body).replace(/^<body[^>]*>|<\/body>$/g, ''));
  });
});
