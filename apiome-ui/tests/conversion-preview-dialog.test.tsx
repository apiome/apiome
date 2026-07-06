/**
 * Tests for the catalog → OpenAPI conversion preview dialog (MFI-22.4, #4005).
 *
 * The dialog dry-runs the conversion lazily on open, renders the fidelity report as two columns with
 * a tier-scaled warning banner, gates Convert behind an acknowledgement on low-tier sources, flows
 * user-supplied defaults into the commit, and makes no changes on cancel.
 */
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';

jest.mock('@monaco-editor/react', () => ({
  __esModule: true,
  default: ({ value, language }: { value?: string; language?: string }) => (
    <div data-testid="conversion-raw-content" data-language={language}>
      {value}
    </div>
  ),
}));

import { ConversionPreviewDialog } from '../src/app/components/ade/dashboard/catalog/ConversionPreviewDialog';

/** A low-tier dry-run result: pub/sub source, gaps + losses, gated behind acknowledgement. */
const LOW_TIER = {
  success: true,
  report: {
    score: 41,
    grade: 'F',
    tier: 'low',
    penalty: 59,
    coverage_counts: { present: 1, inferred: 1, missing: 1, 'n/a': 1 },
    items: [
      { key: 'schemas', title: 'Component schemas', coverage: 'present', weight: 5, count: 3, examples: ['#/components/schemas/Order'], reason: 'schemas carried from the source' },
      { key: 'operationId', title: 'Operation ids', coverage: 'inferred', weight: 2, count: 2, examples: [], reason: 'operationIds synthesized from channel names' },
      { key: 'servers', title: 'Servers', coverage: 'missing', weight: 3, count: 0, examples: [], reason: 'source declares no servers' },
      { key: 'responses', title: 'Responses', coverage: 'n/a', weight: 4, count: 0, examples: [], reason: 'a pub/sub source has no responses' },
    ],
    losses: [
      { kind: 'n/a', subject: 'pubsub-action', detail: 'publish/subscribe actions have no OpenAPI representation', pointer: null },
    ],
  },
  openapi: { openapi: '3.1.0', info: { title: 'x' } },
  sourceFormat: 'asyncapi',
};

/** A high-tier dry-run result: near-lossless, no acknowledgement required. */
const HIGH_TIER = {
  success: true,
  report: {
    score: 100,
    grade: 'A',
    tier: 'high',
    penalty: 0,
    coverage_counts: { present: 2 },
    items: [
      { key: 'paths', title: 'Paths', coverage: 'present', weight: 5, count: 4, examples: [], reason: 'paths carried from the source' },
    ],
    losses: [],
  },
  sourceFormat: 'odata',
};

function okFetch(payload: unknown) {
  return jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(payload) });
}

describe('ConversionPreviewDialog', () => {
  afterEach(() => jest.restoreAllMocks());

  it('does not fetch while closed', () => {
    global.fetch = jest.fn() as unknown as typeof fetch;
    render(<ConversionPreviewDialog itemId={null} itemName="Acme" open={false} onOpenChange={() => {}} />);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('dry-runs on open and renders both columns from the report', async () => {
    global.fetch = okFetch(LOW_TIER) as unknown as typeof fetch;
    render(<ConversionPreviewDialog itemId="cat-1" itemName="Orders" sourceFormat="asyncapi" open onOpenChange={() => {}} />);

    await waitFor(() => expect(screen.getByTestId('conversion-provided-column')).toBeInTheDocument());
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/catalog/cat-1/convert?dryRun=true',
      expect.objectContaining({ method: 'POST' })
    );

    // Provided column has present + inferred; missing column has missing + n/a + the loss.
    const provided = screen.getByTestId('conversion-provided-column');
    expect(provided).toHaveTextContent('Component schemas');
    expect(provided).toHaveTextContent('Operation ids');
    const missing = screen.getByTestId('conversion-missing-column');
    expect(missing).toHaveTextContent('Servers');
    expect(missing).toHaveTextContent('Responses');
    expect(missing).toHaveTextContent('pubsub-action');

    // Header shows grade + tier.
    expect(screen.getByText('F')).toBeInTheDocument();
    expect(screen.getByTestId('conversion-tier-pill')).toHaveTextContent('low fidelity');
  });

  it('shows the mandatory warning banner and gates Convert on low tier', async () => {
    global.fetch = okFetch(LOW_TIER) as unknown as typeof fetch;
    render(<ConversionPreviewDialog itemId="cat-1" itemName="Orders" open onOpenChange={() => {}} />);

    await waitFor(() => expect(screen.getByTestId('conversion-warning-banner')).toBeInTheDocument());
    expect(screen.getByTestId('conversion-warning-banner')).toHaveAttribute('data-severity', 'critical');
    expect(screen.getByTestId('conversion-warning-banner')).toHaveTextContent(
      'may not be complete enough'
    );

    // Convert disabled until the acknowledgement is checked.
    const convert = screen.getByTestId('conversion-convert-btn');
    expect(convert).toBeDisabled();
    fireEvent.click(screen.getByTestId('conversion-ack'));
    expect(convert).toBeEnabled();
  });

  it('does not gate Convert on high tier (warning shown, no acknowledgement)', async () => {
    global.fetch = okFetch(HIGH_TIER) as unknown as typeof fetch;
    render(<ConversionPreviewDialog itemId="cat-1" itemName="Catalog" open onOpenChange={() => {}} />);

    await waitFor(() => expect(screen.getByTestId('conversion-convert-btn')).toBeInTheDocument());
    expect(screen.getByTestId('conversion-warning-banner')).toHaveAttribute('data-severity', 'info');
    expect(screen.queryByTestId('conversion-ack')).not.toBeInTheDocument();
    expect(screen.getByTestId('conversion-convert-btn')).toBeEnabled();
  });

  it('flows user-entered defaults into the commit and refreshes on success', async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(HIGH_TIER) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ success: true, projectId: 'p1' }) });
    global.fetch = fetchMock as unknown as typeof fetch;
    const onConverted = jest.fn();
    const onOpenChange = jest.fn();
    render(
      <ConversionPreviewDialog
        itemId="cat-1"
        itemName="Catalog"
        open
        onOpenChange={onOpenChange}
        onConverted={onConverted}
      />
    );

    await waitFor(() => expect(screen.getByTestId('conversion-default-title')).toBeInTheDocument());
    fireEvent.change(screen.getByTestId('conversion-default-title'), { target: { value: 'My API' } });
    fireEvent.change(screen.getByTestId('conversion-default-servers'), {
      target: { value: 'https://api.example.com, ' },
    });
    fireEvent.click(screen.getByTestId('conversion-convert-btn'));

    await waitFor(() => expect(onConverted).toHaveBeenCalled());
    // Second fetch is the commit (dryRun=false) carrying the cleaned defaults.
    const commitCall = fetchMock.mock.calls[1];
    expect(commitCall[0]).toBe('/api/catalog/cat-1/convert');
    const body = JSON.parse((commitCall[1] as { body: string }).body);
    expect(body).toMatchObject({
      dryRun: false,
      defaults: { title: 'My API', servers: ['https://api.example.com'] },
    });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('cancel makes no changes (no commit request, no onConverted)', async () => {
    const fetchMock = okFetch(HIGH_TIER);
    global.fetch = fetchMock as unknown as typeof fetch;
    const onConverted = jest.fn();
    const onOpenChange = jest.fn();
    render(
      <ConversionPreviewDialog itemId="cat-1" itemName="Catalog" open onOpenChange={onOpenChange} onConverted={onConverted} />
    );

    await waitFor(() => expect(screen.getByText('Cancel')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Cancel'));

    expect(onConverted).not.toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
    // Only the initial dry-run fired — no commit.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('shows an error with a retry that re-runs the dry-run', async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 500, json: () => Promise.resolve({ success: false, error: 'boom' }) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(HIGH_TIER) });
    global.fetch = fetchMock as unknown as typeof fetch;
    render(<ConversionPreviewDialog itemId="cat-1" itemName="Catalog" open onOpenChange={() => {}} />);

    await waitFor(() => expect(screen.getByTestId('conversion-preview-error')).toBeInTheDocument());
    expect(screen.getByText('boom')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Retry'));
    await waitFor(() => expect(screen.getByTestId('conversion-convert-btn')).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('toggles the collapsible raw OpenAPI preview when a document is present', async () => {
    global.fetch = okFetch(LOW_TIER) as unknown as typeof fetch;
    render(<ConversionPreviewDialog itemId="cat-1" itemName="Orders" open onOpenChange={() => {}} />);

    await waitFor(() => expect(screen.getByTestId('conversion-raw-toggle')).toBeInTheDocument());
    expect(screen.queryByTestId('conversion-raw-preview')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('conversion-raw-toggle'));
    expect(screen.getByTestId('conversion-raw-preview')).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId('conversion-raw-content')).toHaveTextContent('3.1.0'),
    );
    expect(screen.getByTestId('conversion-raw-content')).toHaveAttribute('data-language', 'json');
  });
});
