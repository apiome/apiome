import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';

const mockPush = jest.fn();
const mockReplace = jest.fn();
let currentSearch = '?tab=files';

jest.mock('next/dynamic', () => {
  return () => {
    const FallbackEditor = (props: { value?: string; onChange?: (value: string) => void }) => (
      <textarea
        data-testid="monaco-editor"
        value={props.value || ''}
        onChange={(event) => props.onChange?.(event.target.value)}
      />
    );
    return FallbackEditor;
  };
});

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, replace: mockReplace }),
  useParams: () => ({ id: 'repo-1' }),
  useSearchParams: () => new URLSearchParams(currentSearch),
}));

const RepositoryDetailPage = require('../src/app/ade/dashboard/repositories/[id]/page').default as React.ComponentType;

let originalFetch: typeof global.fetch;

function setupFetchMock() {
  const fetchMock = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
    const method = (init?.method || 'GET').toUpperCase();

    if (url === '/api/repositories/repo-1' && method === 'GET') {
      return {
        ok: true,
        json: async () => ({
          success: true,
          repository: {
            id: 'repo-1',
            linkedAccountId: 'account-1',
            provider: 'github',
            owner: 'acme',
            name: 'orders',
            fullName: 'acme/orders',
            status: 'healthy',
            branches: [{ branch: 'main', subpathGlob: '**/*' }],
            timeline: [],
            manifest: 'version: 1',
          },
        }),
      } as Response;
    }
    if (url.startsWith('/api/sso/github/branches?') && method === 'GET') {
      return {
        ok: true,
        json: async () => ({ branches: ['main', 'release/*'] }),
      } as Response;
    }
    if (url === '/api/repositories/repo-1/scans?limit=100' && method === 'GET') {
      return {
        ok: true,
        json: async () => ({
          success: true,
          items: [
            {
              id: 'scan-1',
              branch: 'main',
              commitSha: 'abc123',
              trigger: 'manual',
              status: 'complete',
              startedAt: '2026-04-24T12:00:00Z',
              finishedAt: '2026-04-24T12:01:00Z',
              filesSeen: 1,
              filesClassified: 1,
              filesUnknown: 0,
              filesFailed: 0,
              diffSummary: { added: 1, modified: 0, removed: 0, unchanged: 0 },
            },
          ],
        }),
      } as Response;
    }
    if (url === '/api/repositories/repo-1/scans/scan-1/files?limit=2000' && method === 'GET') {
      return {
        ok: true,
        json: async () => ({
          success: true,
          items: [
            {
              id: 'file-1',
              scanId: 'scan-1',
              path: 'services/orders/openapi.yaml',
              blobSha: 'sha-1',
              format: 'openapi_3_1',
              confidence: 0.99,
              discriminator: null,
              tracked: true,
              projectSlug: 'orders',
              versionStrategy: 'commit-sha',
              status: 'modified',
              qualityScore: 88,
              promote: 'manual',
              settingsJson: null,
            },
          ],
        }),
      } as Response;
    }
    if (url === '/api/repositories/repo-1/scans?limit=100' && method === 'POST') {
      return {
        ok: true,
        json: async () => ({ success: true, scan: { id: 'scan-2' } }),
      } as Response;
    }
    return {
      ok: true,
      json: async () => ({ success: true, items: [] }),
    } as Response;
  });

  global.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

describe('Repository detail page tabs', () => {
  beforeAll(() => {
    originalFetch = global.fetch;
  });

  afterEach(() => {
    global.fetch = originalFetch;
    currentSearch = '?tab=files';
    mockPush.mockReset();
    mockReplace.mockReset();
  });

  it('respects deep-link tab for files view', async () => {
    setupFetchMock();
    render(<RepositoryDetailPage />);

    await waitFor(() => expect(screen.getByText('Repository files')).toBeInTheDocument());
  });

  it('opens file drawer with promote action', async () => {
    setupFetchMock();
    render(<RepositoryDetailPage />);

    await waitFor(() => expect(screen.getByText('services/orders/openapi.yaml')).toBeInTheDocument());
    fireEvent.click(screen.getByText('services/orders/openapi.yaml'));

    await waitFor(() => expect(screen.getByRole('button', { name: 'Promote to project' })).toBeInTheDocument());
    expect(screen.getByText('Classification details')).toBeInTheDocument();
  });
});
