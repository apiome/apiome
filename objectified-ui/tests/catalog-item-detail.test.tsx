/**
 * Render/interaction tests for the catalog item detail view (MFI-23.9, #4018).
 *
 * The detail view must show the four things the ticket calls for — source material (viewable /
 * downloadable), provenance (tool versions + import job), a normalized summary (services/operations/
 * types/channels), and the format/protocol pills + quality/lint orbs — all read off the
 * `/api/catalog/{id}` payload, and must stay publish-free. These assertions pin that contract and
 * the graceful "not captured" degradation when the import has recorded nothing yet.
 */

import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';

const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}));

import { CatalogItemDetailClient } from '../src/app/ade/dashboard/catalog/[id]/CatalogItemDetailClient';

const RICH_ITEM = {
  id: '11111111-2222-3333-4444-555555555555',
  name: 'Acme gRPC API',
  slug: 'acme-grpc-api',
  description: 'Imported from a .proto file.',
  enabled: true,
  deleted_at: null,
  created_at: '2026-06-01T00:00:00.000Z',
  updated_at: '2026-06-20T12:00:00.000Z',
  creator_name: 'Dana Import',
  creator_email: 'dana@example.com',
  qualityScore: 82,
  qualityGrade: 'B',
  publishable: false,
  sourceFormat: 'protobuf',
  protocol: 'grpc',
  formatMetadata: {
    sourceLabel: 'acme.proto',
    inputKind: 'file',
    importJobId: 'job-abc-123',
    sourceContent: 'syntax = "proto3";',
  },
  toolVersions: { protoc: '25.1' },
  summary: { services: 2, operations: 7, types: 12, channels: 0 },
  source: { kind: 'file', label: 'acme.proto', uri: null, hasContent: true, downloadable: true },
};

function mockFetchItem(item: unknown, ok = true) {
  global.fetch = jest.fn().mockResolvedValue({
    ok,
    json: async () => (ok ? { success: true, item } : { success: false, error: 'Catalog item not found.' }),
  }) as unknown as typeof fetch;
}

describe('CatalogItemDetailClient', () => {
  afterEach(() => {
    jest.restoreAllMocks();
    mockPush.mockReset();
  });

  it('renders the header with name, format/protocol/source pills', async () => {
    mockFetchItem(RICH_ITEM);
    render(<CatalogItemDetailClient itemId={RICH_ITEM.id} />);

    await waitFor(() => expect(screen.getByText('Acme gRPC API')).toBeInTheDocument());
    // The format + protocol pills appear in the header (and again in the provenance panel).
    expect(screen.getAllByTestId('format-pill')[0]).toHaveTextContent('Protobuf');
    expect(screen.getAllByTestId('protocol-pill')[0]).toHaveTextContent('grpc');
    expect(screen.getAllByTestId('source-badge').length).toBeGreaterThanOrEqual(1);
    // Fetched the detail proxy for this id.
    expect(global.fetch).toHaveBeenCalledWith(`/api/catalog/${encodeURIComponent(RICH_ITEM.id)}`);
  });

  it('shows the normalized summary counts', async () => {
    mockFetchItem(RICH_ITEM);
    render(<CatalogItemDetailClient itemId={RICH_ITEM.id} />);

    const summary = await screen.findByTestId('catalog-detail-summary');
    expect(summary).toHaveTextContent('Services');
    expect(summary).toHaveTextContent('2');
    expect(summary).toHaveTextContent('Operations');
    expect(summary).toHaveTextContent('7');
    expect(summary).toHaveTextContent('Types');
    expect(summary).toHaveTextContent('12');
  });

  it('offers a raw-source download when the source is downloadable', async () => {
    mockFetchItem(RICH_ITEM);
    render(<CatalogItemDetailClient itemId={RICH_ITEM.id} />);

    const dl = await screen.findByTestId('catalog-detail-download');
    expect(dl).toHaveAttribute('href', `/api/catalog/${encodeURIComponent(RICH_ITEM.id)}/source`);
    expect(dl).toHaveTextContent(/download raw source/i);
  });

  it('shows provenance: tool versions and the import-job reference', async () => {
    mockFetchItem(RICH_ITEM);
    render(<CatalogItemDetailClient itemId={RICH_ITEM.id} />);

    const provenance = await screen.findByTestId('catalog-detail-provenance');
    expect(provenance).toHaveTextContent('protoc');
    expect(provenance).toHaveTextContent('25.1');
    expect(provenance).toHaveTextContent('job-abc-123');
    expect(provenance).toHaveTextContent('Dana Import');
  });

  it('opens the shared quality dialog from the quality orb', async () => {
    mockFetchItem(RICH_ITEM);
    render(<CatalogItemDetailClient itemId={RICH_ITEM.id} />);

    const orb = await screen.findByTestId('catalog-detail-quality-orb');
    expect(orb).toHaveTextContent('82');
    fireEvent.click(orb);
    // The shared ProjectQualityHistoryDialog renders open (a dialog role appears).
    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());
  });

  it('opens the server-backed lint report from the lint orb (MFI-23.10)', async () => {
    const LINT_REPORT = {
      success: true,
      projectId: RICH_ITEM.id,
      versionRecordId: 'rev-1',
      versionId: '1.0.0',
      score: 72,
      grade: 'C',
      findings: [
        {
          id: 'lint-1',
          path: 'components.schemas.Payment',
          category: 'documentation',
          rule: 'documentation.schema-missing-description',
          severity: 'warning',
          message: 'Schema is missing a description.',
        },
      ],
      ruleHits: { 'documentation.schema-missing-description': 1 },
      severityCounts: { error: 0, warning: 1, info: 0 },
      reportFingerprint: 'fp',
      baseRevisionId: null,
      compatibilityOverall: null,
    };
    // Resolve the detail payload and the lint report by URL so the lazy lint fetch is honoured.
    global.fetch = jest.fn((url: string) =>
      Promise.resolve({
        ok: true,
        json: async () =>
          url.endsWith('/lint') ? LINT_REPORT : { success: true, item: RICH_ITEM },
      })
    ) as unknown as typeof fetch;

    render(<CatalogItemDetailClient itemId={RICH_ITEM.id} />);

    const orb = await screen.findByTestId('catalog-detail-lint-orb');
    fireEvent.click(orb);

    await waitFor(() =>
      expect(screen.getByText('documentation.schema-missing-description')).toBeInTheDocument()
    );
    expect(global.fetch).toHaveBeenCalledWith(
      `/api/catalog/${encodeURIComponent(RICH_ITEM.id)}/lint`,
      expect.objectContaining({ method: 'GET' })
    );
    expect(screen.getByText('Schema is missing a description.')).toBeInTheDocument();
  });

  it('degrades gracefully when nothing was captured at import', async () => {
    mockFetchItem({
      ...RICH_ITEM,
      formatMetadata: null,
      toolVersions: null,
      summary: { services: null, operations: null, types: null, channels: null },
      source: { kind: null, label: null, uri: null, hasContent: false, downloadable: false },
    });
    render(<CatalogItemDetailClient itemId={RICH_ITEM.id} />);

    await waitFor(() => expect(screen.getByText('Acme gRPC API')).toBeInTheDocument());
    expect(screen.getByTestId('catalog-detail-no-source')).toBeInTheDocument();
    expect(screen.getByTestId('catalog-detail-summary')).toHaveTextContent(/not been captured/i);
    expect(screen.queryByTestId('catalog-detail-download')).not.toBeInTheDocument();
  });

  it('renders an error state when the item is not found', async () => {
    mockFetchItem(null, false);
    render(<CatalogItemDetailClient itemId="missing" />);

    await waitFor(() =>
      expect(screen.getByTestId('catalog-detail-error')).toHaveTextContent(/not found/i),
    );
  });

  it('never renders a Publish affordance (non-publishable invariant, MFI-23.1)', async () => {
    mockFetchItem(RICH_ITEM);
    render(<CatalogItemDetailClient itemId={RICH_ITEM.id} />);

    await waitFor(() => expect(screen.getByText('Acme gRPC API')).toBeInTheDocument());
    expect(screen.queryByText(/publish/i)).not.toBeInTheDocument();
  });
});
