/**
 * ExportDialog — stepped export shell + target-card grid (MFX-6.1, #3855), the fidelity
 * warning panel (MFX-6.2, #3856), and the emitted-artifact preview + download (MFX-6.3, #3857).
 *
 * Covers the tickets' acceptance criteria:
 *  1. The target grid renders from a mocked `GET /api/export/targets` response and every card
 *     shows its per-source fidelity tier badge (`lossless` / `lossy` / `types-only`).
 *  2. Picking a target updates the fidelity headline (tier + preserved-%).
 *  3. Per-target options (MFX-1.4) render from the selected target's options schema.
 *  4. The stepper advances Source → Target → Fidelity → Export, and Export emits via
 *     `POST /api/export/document` into the preview card.
 *  5. An unavailable target (missing toolchain) renders disabled and cannot be selected.
 *  6. The Fidelity step fetches the `POST /api/export/preview` dry run and renders the server
 *     advisory verbatim with the expandable per-construct report (MFX-6.2).
 *  7. A lossy target gates the download behind the explicit "Export anyway" acknowledgement;
 *     a lossless target exports without one.
 *  8. The Export step previews the emitted document with the "valid · round-trip OK" status
 *     badge, and downloads it on demand as the single file or a client-built `.zip` (MFX-6.3).
 *  9. The API-client collection cards (MFX-31.5): Postman, Insomnia and Bruno each with its
 *     per-source tier, Bruno marked multi-file, and Postman's `flavor` offered as an option.
 * 10. The JSON Schema card (MFX-21.5): `types-only` for a REST source, `lossless` for a JSON Schema
 *     item, with its `draft`, `packaging` and `mode` options — from the recorded live registry.
 * 11. The COBOL copybook card (MFX-23.5): `types-only` for a REST source, `lossless` for a copybook
 *     item, with its layout options — from the recorded live registry.
 * 12. The X12 implementation-guide card (MFX-24.5): `types-only` for every source, multi-file, with the
 *     transaction-set and version picker — from the recorded live registry.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

jest.mock('@monaco-editor/react', () => ({
  __esModule: true,
  default: ({
    value,
    language,
  }: {
    value?: string;
    language?: string;
  }) => (
    <div data-testid="export-artifact-content" data-language={language}>
      {value}
    </div>
  ),
}));

/** Capture navigations from the "Open in Export Studio" escalation (MFX-41.1). */
const routerPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: routerPush, replace: jest.fn(), prefetch: jest.fn() }),
}));

import { ExportDialog } from '../src/app/components/ade/dashboard/export/ExportDialog';
import {
  EXPORT_DIALOG_COLLECTION_TARGETS as COLLECTION_TARGETS,
  EXPORT_DIALOG_TARGETS as TARGETS,
  copybookTargets,
  jsonSchemaTargets,
  mockExportDialogFetch as mockFetch,
  x12GuideTargets,
} from './helpers/export-dialog-fixture';


/** Open the dialog and advance past the Source step once targets have loaded. */
async function renderAtTargetStep(fetchMock: jest.Mock) {
  global.fetch = fetchMock as unknown as typeof fetch;
  render(<ExportDialog open onClose={jest.fn()} artifact="proj-petstore" artifactLabel="Pet Store API" />);

  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/export/targets?artifact=proj-petstore'),
      expect.anything(),
    ),
  );
  await waitFor(() =>
    expect(screen.getByRole('button', { name: /choose target/i })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole('button', { name: /choose target/i }));
  await waitFor(() => expect(screen.getByText('Choose a target format')).toBeInTheDocument());
}

/** Advance a fresh dialog to the Fidelity step for the given target. */
async function renderAtFidelityStep(fetchMock: jest.Mock, target: string) {
  await renderAtTargetStep(fetchMock);
  fireEvent.click(screen.getByTestId(`export-target-${target}`));
  fireEvent.click(screen.getByRole('button', { name: /^continue$/i }));
}

describe('ExportDialog — target-card grid (MFX-6.1)', () => {
  beforeEach(() => {
    // jsdom implements neither createObjectURL nor revokeObjectURL; the download helper needs both.
    (URL as unknown as { createObjectURL: unknown }).createObjectURL = jest.fn(() => 'blob:mock');
    (URL as unknown as { revokeObjectURL: unknown }).revokeObjectURL = jest.fn();
    // jsdom cannot navigate; stub the download anchor's click so it doesn't warn.
    jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('shows the resolved source version on the Source step', async () => {
    const fetchMock = mockFetch();
    global.fetch = fetchMock as unknown as typeof fetch;
    render(<ExportDialog open onClose={jest.fn()} artifact="proj-petstore" artifactLabel="Pet Store API" />);

    await waitFor(() => expect(screen.getByText(/Version 1\.2\.0/)).toBeInTheDocument());
    expect(screen.getByText(/3 export targets available/)).toBeInTheDocument();
  });

  it('renders every target card with its per-source fidelity tier badge', async () => {
    await renderAtTargetStep(mockFetch());

    expect(screen.getByTestId('export-target-openapi')).toBeInTheDocument();
    expect(screen.getByTestId('export-target-proto')).toBeInTheDocument();
    expect(screen.getByTestId('export-target-avro')).toBeInTheDocument();

    expect(screen.getByTestId('export-target-openapi')).toHaveTextContent('lossless');
    expect(screen.getByTestId('export-target-proto')).toHaveTextContent('lossy');
    expect(screen.getByTestId('export-target-avro')).toHaveTextContent('types-only');
  });

  it('disables an unavailable target and keeps it unselectable', async () => {
    await renderAtTargetStep(mockFetch());

    const avroCard = screen.getByTestId('export-target-avro');
    expect(avroCard).toBeDisabled();
    fireEvent.click(avroCard);
    expect(screen.queryByTestId('export-fidelity-headline')).not.toBeInTheDocument();
  });

  it('updates the fidelity headline when a target is picked', async () => {
    await renderAtTargetStep(mockFetch());

    fireEvent.click(screen.getByTestId('export-target-proto'));
    const headline = screen.getByTestId('export-fidelity-headline');
    expect(headline).toHaveTextContent('gRPC / Protobuf');
    expect(headline).toHaveTextContent('lossy');
    expect(headline).toHaveTextContent('64% preserved');

    // Picking a different target re-computes the headline for that card.
    fireEvent.click(screen.getByTestId('export-target-openapi'));
    expect(screen.getByTestId('export-fidelity-headline')).toHaveTextContent('100% preserved');
  });

  it('renders the selected target’s per-target options from its schema', async () => {
    await renderAtTargetStep(mockFetch());

    fireEvent.click(screen.getByTestId('export-target-proto'));
    expect(screen.getByText('Target options')).toBeInTheDocument();
    expect(screen.getByLabelText(/Emit Services/i)).toBeChecked();
    expect(screen.getByLabelText(/Package/i)).toHaveValue('');

    // A target without options shows no options panel.
    fireEvent.click(screen.getByTestId('export-target-openapi'));
    expect(screen.queryByText('Target options')).not.toBeInTheDocument();
  });

  it('advances to Fidelity and shows the preserved-% summary with count chips', async () => {
    await renderAtTargetStep(mockFetch());

    fireEvent.click(screen.getByTestId('export-target-proto'));
    fireEvent.click(screen.getByRole('button', { name: /^continue$/i }));

    await waitFor(() =>
      expect(screen.getByTestId('export-preserved-percent')).toHaveTextContent('64%'),
    );
    expect(screen.getByText('3 dropped')).toBeInTheDocument();
    expect(screen.getByText('2 approximated')).toBeInTheDocument();
    expect(screen.getByText('2 synthesized')).toBeInTheDocument();
    expect(screen.getByText('51 clean')).toBeInTheDocument();
    // The dry-run preview (MFX-6.2) lands and adds the advisory to the panel.
    await waitFor(() => expect(screen.getByTestId('export-advisory')).toBeInTheDocument());
  });

  it('exports the document, sending only changed options, into the preview card', async () => {
    const fetchMock = mockFetch();
    await renderAtTargetStep(fetchMock);

    fireEvent.click(screen.getByTestId('export-target-proto'));
    // Change one option so the emit request carries it; the untouched option stays server-side.
    fireEvent.click(screen.getByLabelText(/Emit Services/i));
    fireEvent.click(screen.getByRole('button', { name: /^continue$/i }));
    // Let the dry-run preview settle so no state update lands mid-assertion.
    await waitFor(() => expect(screen.getByTestId('export-advisory')).toBeInTheDocument());
    // proto is lossy: acknowledge the fidelity loss to unlock "Export anyway" (MFX-6.2).
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: /^export anyway$/i }));

    // The emitted document lands in the preview card (MFX-6.3), not an immediate download.
    await waitFor(() =>
      expect(screen.getByTestId('export-artifact-preview')).toBeInTheDocument(),
    );
    expect(screen.getByTestId('export-artifact-preview')).toHaveTextContent('petstore.proto');

    const documentCall = fetchMock.mock.calls.find(([url]) =>
      String(url).includes('/api/export/document'),
    );
    expect(documentCall).toBeDefined();
    const body = JSON.parse((documentCall![1] as { body: string }).body);
    expect(body).toEqual({
      artifact: 'proj-petstore',
      version: null,
      target: 'proto',
      options: { emit_services: false },
    });

    // The stepper reached the final step.
    expect(screen.getByText('4. Export')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^done$/i })).toBeInTheDocument();
  });

  it('surfaces an emit failure and returns to the Fidelity step', async () => {
    const fetchMock = jest.fn((input: unknown, init?: { method?: string }) => {
      const url = typeof input === 'string' ? input : String(input);
      if (url.includes('/api/export/targets')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ success: true, ...TARGETS }),
        });
      }
      if (url.includes('/api/export/document') && init?.method === 'POST') {
        return Promise.resolve({
          ok: false,
          json: () => Promise.resolve({ success: false, error: 'Target proto is unavailable.' }),
        });
      }
      return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
    }) as unknown as jest.Mock;

    await renderAtTargetStep(fetchMock);
    fireEvent.click(screen.getByTestId('export-target-proto'));
    fireEvent.click(screen.getByRole('button', { name: /^continue$/i }));
    // This mock has no preview handler: the panel degrades to the summary + error note.
    await waitFor(() => expect(screen.getByTestId('export-advisory-error')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: /^export anyway$/i }));

    await waitFor(() =>
      expect(screen.getByText('Target proto is unavailable — try again.')).toBeInTheDocument(),
    );
    // Back on the Fidelity step, the acknowledgement persists and the user can retry.
    expect(screen.getByRole('button', { name: /^export anyway$/i })).toBeEnabled();
  });
});

describe('ExportDialog — fidelity warning panel (MFX-6.2)', () => {
  beforeEach(() => {
    (URL as unknown as { createObjectURL: unknown }).createObjectURL = jest.fn(() => 'blob:mock');
    (URL as unknown as { revokeObjectURL: unknown }).revokeObjectURL = jest.fn();
    jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('fetches the dry-run preview and renders the advisory verbatim', async () => {
    const fetchMock = mockFetch();
    await renderAtFidelityStep(fetchMock, 'proto');

    await waitFor(() => expect(screen.getByTestId('export-advisory')).toBeInTheDocument());
    const advisory = screen.getByTestId('export-advisory');
    expect(advisory).toHaveTextContent('This export loses fidelity');
    expect(advisory).toHaveTextContent(
      'Exporting to gRPC / Protobuf may lose some fidelity: 7 constructs affected.',
    );

    const previewCall = fetchMock.mock.calls.find(([url]) =>
      String(url).includes('/api/export/preview'),
    );
    expect(previewCall).toBeDefined();
    expect(JSON.parse((previewCall![1] as { body: string }).body)).toEqual({
      artifact: 'proj-petstore',
      version: null,
      target: 'proto',
      // Every option ran at its default, so no overrides are folded into the preview.
      options: null,
    });
  });

  it('expands the per-construct report with source paths and degradations', async () => {
    await renderAtFidelityStep(mockFetch(), 'proto');

    await waitFor(() => expect(screen.getByTestId('export-report-toggle')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('export-report-toggle'));

    const report = screen.getByTestId('export-fidelity-report');
    expect(report).toHaveTextContent('DROP');
    expect(report).toHaveTextContent('User.email');
    expect(report).toHaveTextContent('APPROX');
    expect(report).toHaveTextContent('query parameter → request message field');
    expect(report).toHaveTextContent('OK');
  });

  it('renders the destination-aware projection map with its synchronized table (EFP-2.2)', async () => {
    const fetchMock = mockFetch();
    await renderAtFidelityStep(fetchMock, 'proto');

    await waitFor(() => expect(screen.getByTestId('projection-table')).toBeInTheDocument());
    // The evidence request describes the same (source, target) as the preview above it.
    const evidenceCall = fetchMock.mock.calls.find(([url]) =>
      String(url).includes('/api/export/projection-evidence'),
    );
    expect(evidenceCall).toBeDefined();
    expect(JSON.parse((evidenceCall![1] as { body: string }).body)).toMatchObject({
      artifact: 'proj-petstore',
      version: null,
      target: 'proto',
      options: null,
    });

    // Graph and table render the same two evidence rows.
    expect(screen.getByTestId('projection-node-pe1')).toBeInTheDocument();
    expect(screen.getByTestId('projection-node-pe2')).toBeInTheDocument();
    expect(screen.getByTestId('projection-row-pe1')).toBeInTheDocument();
    expect(screen.getByTestId('projection-row-pe2')).toBeInTheDocument();

    // Selecting the dropped construct opens its evidence.
    fireEvent.click(screen.getByTestId('projection-row-select-pe2'));
    expect(screen.getByTestId('projection-detail')).toHaveTextContent(
      'Subscriptions are not representable.',
    );
  });

  it('keeps a lossy export disabled until the loss is acknowledged', async () => {
    await renderAtFidelityStep(mockFetch(), 'proto');
    await waitFor(() => expect(screen.getByTestId('export-advisory')).toBeInTheDocument());

    const exportButton = screen.getByRole('button', { name: /^export anyway$/i });
    expect(exportButton).toBeDisabled();

    fireEvent.click(screen.getByRole('checkbox'));
    expect(exportButton).toBeEnabled();

    // Withdrawing the acknowledgement re-locks the download.
    fireEvent.click(screen.getByRole('checkbox'));
    expect(exportButton).toBeDisabled();
  });

  it('re-requires the acknowledgement after re-picking a lossy target', async () => {
    await renderAtFidelityStep(mockFetch(), 'proto');
    await waitFor(() => expect(screen.getByTestId('export-advisory')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('checkbox'));
    expect(screen.getByRole('button', { name: /^export anyway$/i })).toBeEnabled();

    // Back to the target grid, re-pick the same lossy target: the conversion must be
    // re-acknowledged from scratch.
    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));
    fireEvent.click(screen.getByTestId('export-target-proto'));
    fireEvent.click(screen.getByRole('button', { name: /^continue$/i }));
    await waitFor(() => expect(screen.getByTestId('export-advisory')).toBeInTheDocument());

    expect(screen.getByRole('checkbox')).not.toBeChecked();
    expect(screen.getByRole('button', { name: /^export anyway$/i })).toBeDisabled();
  });

  it('clears the acknowledgement and refreshes the report and graph together on an option change (EFP-2.3)', async () => {
    const fetchMock = mockFetch();
    await renderAtFidelityStep(fetchMock, 'proto');
    await waitFor(() => expect(screen.getByTestId('export-advisory')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('checkbox'));
    expect(screen.getByRole('button', { name: /^export anyway$/i })).toBeEnabled();

    // Back to the target step, change one option: the old acknowledgement no longer
    // describes the conversion, so it cannot survive.
    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));
    fireEvent.click(screen.getByLabelText(/Emit Services/i));
    fireEvent.click(screen.getByRole('button', { name: /^continue$/i }));
    await waitFor(() => expect(screen.getByTestId('export-advisory')).toBeInTheDocument());

    expect(screen.getByRole('checkbox')).not.toBeChecked();
    expect(screen.getByRole('button', { name: /^export anyway$/i })).toBeDisabled();

    // Both the preview and the projection evidence were re-requested with the changed
    // option folded in — one configuration, one snapshot, no stale report or graph.
    await waitFor(() => {
      const previewBodies = fetchMock.mock.calls
        .filter(([url]) => String(url).includes('/api/export/preview'))
        .map((call) => JSON.parse((call[1] as { body: string }).body));
      expect(previewBodies.at(-1)).toMatchObject({ target: 'proto', options: { emit_services: false } });
    });
    await waitFor(() => {
      const evidenceBodies = fetchMock.mock.calls
        .filter(([url]) => String(url).includes('/api/export/projection-evidence'))
        .map((call) => JSON.parse((call[1] as { body: string }).body));
      expect(evidenceBodies.at(-1)).toMatchObject({ target: 'proto', options: { emit_services: false } });
    });
  });

  it('navigates back to the target step from the evidence drawer remediation (EFP-2.3)', async () => {
    await renderAtFidelityStep(mockFetch(), 'proto');
    await waitFor(() => expect(screen.getByTestId('projection-table')).toBeInTheDocument());

    // Open the dropped construct's evidence drawer: a destination format limit.
    fireEvent.click(screen.getByTestId('projection-row-select-pe2'));
    expect(screen.getByTestId('projection-detail-category')).toHaveTextContent('Format limit');

    // The safe remediation navigates back to the target grid; nothing is changed by itself.
    fireEvent.click(screen.getByTestId('projection-detail-action-change-target'));
    await waitFor(() => expect(screen.getByText('Choose a target format')).toBeInTheDocument());
  });

  it('exports a lossless target without any acknowledgement and shows the quiet reassurance', async () => {
    const fetchMock = mockFetch();
    await renderAtFidelityStep(fetchMock, 'openapi');

    // No warning gate for a clean conversion: plain Export, no checkbox, quiet advisory.
    await waitFor(() =>
      expect(screen.getByTestId('export-advisory')).toHaveTextContent(
        'Lossless export to OpenAPI 3.1',
      ),
    );
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();

    const exportButton = screen.getByRole('button', { name: /^export$/i });
    expect(exportButton).toBeEnabled();
    fireEvent.click(exportButton);
    await waitFor(() =>
      expect(screen.getByTestId('export-artifact-preview')).toBeInTheDocument(),
    );
  });
});

describe('ExportDialog — emitted-artifact preview + download (MFX-6.3)', () => {
  /** The `download` filenames handed to the browser, captured from the anchor clicks. */
  let downloads: string[];
  /** The blobs handed to `URL.createObjectURL`, captured per download. */
  let blobs: Blob[];

  beforeEach(() => {
    downloads = [];
    blobs = [];
    (URL as unknown as { createObjectURL: unknown }).createObjectURL = jest.fn((blob: unknown) => {
      blobs.push(blob as Blob);
      return 'blob:mock';
    });
    (URL as unknown as { revokeObjectURL: unknown }).revokeObjectURL = jest.fn();
    jest
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(function (this: HTMLAnchorElement) {
        downloads.push(this.download);
      });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  /** Run a fresh dialog through Fidelity into the Export step's preview for `target`. */
  async function renderAtPreview(fetchMock: jest.Mock, target: string) {
    await renderAtFidelityStep(fetchMock, target);
    await waitFor(() => expect(screen.getByTestId('export-advisory')).toBeInTheDocument());
    if (target === 'proto') {
      fireEvent.click(screen.getByRole('checkbox'));
      fireEvent.click(screen.getByRole('button', { name: /^export anyway$/i }));
    } else {
      fireEvent.click(screen.getByRole('button', { name: /^export$/i }));
    }
    await waitFor(() =>
      expect(screen.getByTestId('export-artifact-preview')).toBeInTheDocument(),
    );
  }

  it('previews the emitted document text before any download', async () => {
    await renderAtPreview(mockFetch(), 'proto');

    expect(screen.getByTestId('export-artifact-content')).toHaveTextContent('syntax = "proto3";');
    expect(screen.getByTestId('export-artifact-editor')).toHaveAttribute('data-language', 'protobuf');
    expect(screen.getByTestId('export-artifact-copy')).toBeInTheDocument();
    // Nothing was downloaded yet — the preview replaces the old immediate download.
    expect(downloads).toHaveLength(0);
  });

  it('badges a parsed lossless export as "valid · round-trip OK" (mockup wording)', async () => {
    await renderAtPreview(mockFetch(), 'openapi');

    expect(screen.getByTestId('export-artifact-badge')).toHaveTextContent(
      'valid · round-trip OK',
    );
  });

  it('badges a lossy export as a lossy round-trip, without a validity claim for unparsed formats', async () => {
    await renderAtPreview(mockFetch(), 'proto');

    // proto has no client-side parser and its report predicts losses: round-trip half only.
    expect(screen.getByTestId('export-artifact-badge')).toHaveTextContent(/^lossy round-trip$/);
  });

  it('badges a malformed emitted document as invalid', async () => {
    const fetchMock = mockFetch();
    // Corrupt the emitted JSON: the client-side re-parse must catch it.
    fetchMock.mockImplementation(((input: unknown, init?: { method?: string; body?: string }) => {
      const url = typeof input === 'string' ? input : String(input);
      if (url.includes('/api/export/document') && init?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          headers: {
            get: (name: string) => {
              if (name.toLowerCase() === 'content-disposition') {
                return 'attachment; filename="petstore.json"';
              }
              return name.toLowerCase() === 'content-type' ? 'application/json' : null;
            },
          },
          text: () => Promise.resolve('{"openapi": '),
        });
      }
      return mockFetch()(input, init);
    }) as never);

    await renderAtPreview(fetchMock, 'openapi');
    expect(screen.getByTestId('export-artifact-badge')).toHaveTextContent('invalid JSON');
  });

  it('downloads the single file on demand with its served media type', async () => {
    await renderAtPreview(mockFetch(), 'proto');

    fireEvent.click(screen.getByRole('button', { name: /download petstore\.proto/i }));
    expect(downloads).toEqual(['petstore.proto']);
    expect(blobs[0].type).toBe('text/plain');
  });

  it('downloads a client-built .zip bundle on demand', async () => {
    await renderAtPreview(mockFetch(), 'proto');

    fireEvent.click(screen.getByRole('button', { name: /download \.zip/i }));
    expect(downloads).toEqual(['petstore.zip']);
    expect(blobs[0].type).toBe('application/zip');
  });

  it('supports downloading both forms from one preview', async () => {
    await renderAtPreview(mockFetch(), 'openapi');

    fireEvent.click(screen.getByRole('button', { name: /download petstore\.json/i }));
    fireEvent.click(screen.getByRole('button', { name: /download \.zip/i }));
    expect(downloads).toEqual(['petstore.json', 'petstore.zip']);
  });

  /**
   * A multi-file target (E1-4): the document endpoint returns only the primary file, so the zip
   * is the export job's MFX-4.2 bundle — every emitted file plus `manifest.json`.
   */
  function mockMultiFileFetch(jobState: 'completed' | 'failed' = 'completed') {
    const base = mockFetch();
    const posted: Record<string, unknown>[] = [];
    const bundle = new Blob(['PK-bundle'], { type: 'application/zip' });
    const fetchMock = jest.fn(((input: unknown, init?: { method?: string; body?: string }) => {
      const url = typeof input === 'string' ? input : String(input);
      const json = (payload: unknown) =>
        Promise.resolve({ ok: true, headers: new Headers(), json: () => Promise.resolve(payload) });
      if (url.includes('/api/export/targets')) {
        const targets = TARGETS.targets.map((t) =>
          t.descriptor.key === 'proto' ? { ...t, descriptor: { ...t.descriptor, multi_file: true } } : t,
        );
        return json({ success: true, ...TARGETS, targets });
      }
      if (url === '/api/export/jobs' && init?.method === 'POST') {
        posted.push(JSON.parse(init.body ?? '{}'));
        return json({ success: true, job_id: 'job-b', status_path: '/x' });
      }
      if (url.endsWith('/api/export/jobs/job-b/download')) {
        return Promise.resolve({
          ok: true,
          headers: new Headers({ 'content-disposition': 'attachment; filename="petstore-proto.zip"' }),
          blob: () => Promise.resolve(bundle),
        });
      }
      if (url.endsWith('/api/export/jobs/job-b')) {
        return json({
          success: true,
          job_id: 'job-b',
          state: jobState,
          percent: 100,
          events: [],
          error: jobState === 'failed' ? { code: 'EMIT_FAILED', message: 'The emitter failed' } : null,
        });
      }
      return base(input, init);
    }) as never) as unknown as jest.Mock;
    return { fetchMock, posted, bundle };
  }

  it('downloads every file of a multi-file target from the export bundle (E1-4)', async () => {
    const { fetchMock, posted, bundle } = mockMultiFileFetch();
    await renderAtPreview(fetchMock, 'proto');

    expect(screen.getByTestId('export-dialog-emitted')).toHaveTextContent('This target writes several files');
    fireEvent.click(screen.getByRole('button', { name: /download all files \(\.zip\)/i }));
    await waitFor(() => expect(downloads).toEqual(['petstore-proto.zip']));
    // The served bundle, not a client-built zip of the primary file.
    expect(blobs[0]).toBe(bundle);
    expect(posted).toEqual([
      expect.objectContaining({ artifact: 'proj-petstore', target: 'proto', confirm: true }),
    ]);
    expect(posted[0]).not.toHaveProperty('targets');
  });

  it('reports a failed bundle export instead of downloading (E1-4)', async () => {
    const { fetchMock } = mockMultiFileFetch('failed');
    await renderAtPreview(fetchMock, 'proto');

    fireEvent.click(screen.getByRole('button', { name: /download all files \(\.zip\)/i }));
    expect(await screen.findByText(/The emitter failed/)).toBeInTheDocument();
    expect(downloads).toEqual([]);
  });

  it('keeps the client-built zip and the plain label for a single-file target (E1-4)', async () => {
    const { fetchMock, posted } = mockMultiFileFetch();
    await renderAtPreview(fetchMock, 'openapi');

    expect(screen.queryByRole('button', { name: /download all files/i })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /download \.zip/i }));
    expect(downloads).toEqual(['petstore.zip']);
    expect(posted).toEqual([]);
  });
});

describe('ExportDialog — version-scoped entry-point handoff (MFX-6.5)', () => {
  beforeEach(() => {
    (URL as unknown as { createObjectURL: unknown }).createObjectURL = jest.fn(() => 'blob:mock');
    (URL as unknown as { revokeObjectURL: unknown }).revokeObjectURL = jest.fn();
    jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('reports the emitted target, fidelity, and filename via onExported', async () => {
    const onExported = jest.fn();
    const fetchMock = mockFetch();
    global.fetch = fetchMock as unknown as typeof fetch;
    render(
      <ExportDialog
        open
        onClose={jest.fn()}
        artifact="proj-petstore"
        artifactLabel="Pet Store API"
        version="rev-1"
        onExported={onExported}
      />,
    );

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /choose target/i })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: /choose target/i }));
    fireEvent.click(screen.getByTestId('export-target-proto'));
    fireEvent.click(screen.getByRole('button', { name: /^continue$/i }));
    await waitFor(() => expect(screen.getByTestId('export-advisory')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: /^export anyway$/i }));
    await waitFor(() =>
      expect(screen.getByTestId('export-artifact-preview')).toBeInTheDocument(),
    );

    // The summary is what the versions page records as a recent export (recentExports.ts).
    expect(onExported).toHaveBeenCalledTimes(1);
    expect(onExported).toHaveBeenCalledWith({
      targetKey: 'proto',
      targetLabel: 'gRPC / Protobuf',
      tier: 'lossy',
      preservedPercent: 64,
      filename: 'petstore.proto',
      // Every option ran at its default here, so no overrides are recorded (MFX-41.3).
      options: null,
    });
  });

  it('does not report a failed emit', async () => {
    const onExported = jest.fn();
    const fetchMock = jest.fn((input: unknown, init?: { method?: string; body?: string }) => {
      const url = typeof input === 'string' ? input : String(input);
      if (url.includes('/api/export/document')) {
        return Promise.resolve({
          ok: false,
          json: () => Promise.resolve({ error: 'Emit failed.' }),
        });
      }
      return (mockFetch()(input, init) as unknown) as Promise<unknown>;
    }) as unknown as jest.Mock;
    global.fetch = fetchMock as unknown as typeof fetch;
    render(
      <ExportDialog
        open
        onClose={jest.fn()}
        artifact="proj-petstore"
        onExported={onExported}
      />,
    );

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /choose target/i })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: /choose target/i }));
    fireEvent.click(screen.getByTestId('export-target-proto'));
    fireEvent.click(screen.getByRole('button', { name: /^continue$/i }));
    await waitFor(() => expect(screen.getByTestId('export-advisory')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: /^export anyway$/i }));

    await waitFor(() => expect(screen.getByText('Emit failed — try again.')).toBeInTheDocument());
    expect(onExported).not.toHaveBeenCalled();
  });
});

describe('ExportDialog — Export Studio escalation (MFX-41.1)', () => {
  // The escalation is offered only once the Studio is released (`lib/feature-release.ts`);
  // these cases pin its behaviour for that day, with the build-time override set.
  beforeAll(() => {
    process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = 'export-studio';
  });
  afterAll(() => {
    delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
  });

  beforeEach(() => {
    routerPush.mockClear();
    (URL as unknown as { createObjectURL: unknown }).createObjectURL = jest.fn(() => 'blob:mock');
    (URL as unknown as { revokeObjectURL: unknown }).revokeObjectURL = jest.fn();
    jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('escalates to the scoped Studio route carrying the current target selection', async () => {
    const onClose = jest.fn();
    const fetchMock = mockFetch();
    global.fetch = fetchMock as unknown as typeof fetch;
    render(
      <ExportDialog
        open
        onClose={onClose}
        artifact="proj-petstore"
        artifactLabel="Pet Store API"
        version="rev-1"
      />,
    );

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /choose target/i })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: /choose target/i }));
    fireEvent.click(screen.getByTestId('export-target-proto'));

    fireEvent.click(screen.getByRole('button', { name: /open in export studio/i }));

    // The dialog closes and hands the source + picked target to the Studio deep link.
    expect(onClose).toHaveBeenCalled();
    expect(routerPush).toHaveBeenCalledTimes(1);
    const href = routerPush.mock.calls[0][0] as string;
    expect(href).toContain('/ade/dashboard/export/studio?');
    const query = new URLSearchParams(href.split('?')[1]);
    expect(query.get('artifact')).toBe('proj-petstore');
    expect(query.get('version')).toBe('rev-1');
    expect(query.get('label')).toBe('Pet Store API');
    expect(query.get('target')).toBe('proto');
  });

  it('opens on a requested target and goes straight to its fidelity report (CDG-5.3 push-back)', async () => {
    global.fetch = mockFetch() as unknown as typeof fetch;
    render(
      <ExportDialog
        open
        onClose={jest.fn()}
        artifact="proj-petstore"
        sourceFormat="protobuf"
        studioOrigin="gateway-config"
        initialTarget="proto"
      />,
    );
    // The same-format target is kept because it was asked for, and its fidelity report shows first.
    await waitFor(() =>
      expect(screen.getByTestId('export-preserved-percent')).toHaveTextContent('64%'),
    );
    expect(screen.getByText('3 dropped')).toBeInTheDocument();
  });

  it('hides the same-format target, offers the original source, and carries origin + format into the Studio', async () => {
    const fetchMock = mockFetch();
    global.fetch = fetchMock as unknown as typeof fetch;
    render(
      <ExportDialog
        open
        onClose={jest.fn()}
        artifact="proj-petstore"
        artifactLabel="Pet Store API"
        sourceFormat="protobuf"
        studioOrigin="catalog"
      />,
    );

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /choose target/i })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: /choose target/i }));

    // The protobuf source's proto target is dropped; the original-source option replaces it.
    expect(screen.queryByTestId('export-target-proto')).not.toBeInTheDocument();
    expect(screen.getByTestId('export-original-source-download')).toHaveAttribute(
      'href',
      '/api/catalog/proj-petstore/source',
    );

    fireEvent.click(screen.getByTestId('export-target-openapi'));
    fireEvent.click(screen.getByRole('button', { name: /open in export studio/i }));

    const query = new URLSearchParams((routerPush.mock.calls[0][0] as string).split('?')[1]);
    expect(query.get('from')).toBe('catalog');
    expect(query.get('sourceFormat')).toBe('protobuf');
    expect(query.get('target')).toBe('openapi');
  });
});

describe('ExportDialog — pending and failed targets read (RC6-H3, #6210)', () => {
  it('says it is measuring while the targets load', async () => {
    global.fetch = jest.fn(() => new Promise(() => {})) as unknown as typeof fetch;
    render(<ExportDialog open onClose={jest.fn()} artifact="proj-petstore" artifactLabel="Pet Store API" />);
    expect(await screen.findByText('Measuring export fidelity for this source…')).toBeInTheDocument();
    expect(screen.getByTestId('export-dialog-choose-target')).toBeDisabled();
  });

  it('says a failed targets read failed, with a retry that loads them', async () => {
    const answer = mockFetch();
    let fail = true;
    global.fetch = jest.fn((input: unknown, init?: { method?: string; body?: string }) =>
      fail && String(input).includes('/api/export/targets')
        ? Promise.resolve({ ok: false, status: 503, json: () => Promise.resolve({ success: false, error: 'Registry unavailable' }) })
        : answer(input, init)
    ) as unknown as typeof fetch;
    render(<ExportDialog open onClose={jest.fn()} artifact="proj-petstore" artifactLabel="Pet Store API" />);
    const error = await screen.findByTestId('export-dialog-targets-error');
    expect(error).toHaveTextContent("Couldn't load the export targets");
    expect(error).toHaveTextContent('Registry unavailable');
    fail = false;
    fireEvent.click(within(error).getByRole('button', { name: /try again/i }));
    await waitFor(() => expect(screen.getByTestId('export-dialog-choose-target')).toBeEnabled());
    expect(screen.queryByTestId('export-dialog-targets-error')).not.toBeInTheDocument();
  });
});

describe('ExportDialog — a source with nothing captured (E1-6, #6221)', () => {
  function failTargets(code: string | null, status = 422) {
    global.fetch = jest.fn(() =>
      Promise.resolve({
        ok: false,
        status,
        json: () =>
          Promise.resolve({ success: false, error: 'This catalog item has no captured source material.', code }),
      }),
    ) as unknown as typeof fetch;
  }

  it('says why and offers Re-import instead of a bare 422', async () => {
    failTargets('source-not-captured');
    render(<ExportDialog open onClose={jest.fn()} artifact="proj-petstore" artifactLabel="Pet Store API" />);
    const notice = await screen.findByTestId('export-missing-source');
    expect(notice).toHaveTextContent("Pet Store API can't be exported: its source file wasn't kept");
    expect(screen.getByTestId('export-missing-source-reimport')).toHaveAttribute(
      'href',
      '/ade/dashboard/catalog?open=import-catalog',
    );
    expect(screen.queryByTestId('export-dialog-targets-error')).not.toBeInTheDocument();
    expect(screen.getByTestId('export-dialog-choose-target')).toBeDisabled();
  });

  it('explains a source withheld for credentials', async () => {
    failTargets('source-withheld');
    render(<ExportDialog open onClose={jest.fn()} artifact="proj-petstore" artifactLabel="Pet Store API" />);
    expect(await screen.findByTestId('export-missing-source')).toHaveTextContent('contained credentials');
  });

  it('keeps the retry banner for any other failure', async () => {
    failTargets(null, 503);
    render(<ExportDialog open onClose={jest.fn()} artifact="proj-petstore" artifactLabel="Pet Store API" />);
    expect(await screen.findByTestId('export-dialog-targets-error')).toBeInTheDocument();
    expect(screen.queryByTestId('export-missing-source')).not.toBeInTheDocument();
  });
});

describe('ExportDialog — no path into the held-back Export studio (RC6-H4, #6211)', () => {
  it('offers no studio link or navigation at any step while export-studio is unreleased', async () => {
    delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
    routerPush.mockClear();
    global.fetch = mockFetch() as unknown as typeof fetch;
    render(<ExportDialog open onClose={jest.fn()} artifact="proj-petstore" artifactLabel="Pet Store API" />);

    /** No anchor, button or navigation reaches the studio route. */
    const assertNoStudio = () => {
      const links = Array.from(document.querySelectorAll('a[href]')).map((a) => a.getAttribute('href') ?? '');
      expect(links.filter((href) => href.includes('/export/studio'))).toEqual([]);
      expect(screen.queryByRole('button', { name: /export studio/i })).not.toBeInTheDocument();
      expect(routerPush).not.toHaveBeenCalled();
    };

    const chooseTarget = await screen.findByTestId('export-dialog-choose-target');
    await waitFor(() => expect(chooseTarget).toBeEnabled());
    assertNoStudio();
    fireEvent.click(chooseTarget);
    fireEvent.click(await screen.findByTestId('export-target-proto'));
    assertNoStudio();
    fireEvent.click(screen.getByTestId('export-dialog-continue'));
    await screen.findByTestId('export-ack');
    assertNoStudio();
    fireEvent.click(screen.getByTestId('export-ack'));
    fireEvent.click(screen.getByTestId('export-dialog-export'));
    await screen.findByTestId('export-dialog-emitted');
    assertNoStudio();
  });
});


describe('ExportDialog — API-client collection targets (MFX-31.5)', () => {
  it('renders the Postman, Insomnia and Bruno cards, each with its per-source tier', async () => {
    await renderAtTargetStep(mockFetch(COLLECTION_TARGETS));

    for (const [key, label] of [
      ['postman', 'Postman'],
      ['insomnia', 'Insomnia'],
      ['bruno', 'Bruno'],
    ] as const) {
      const card = screen.getByTestId(`export-target-${key}`);
      expect(card).toBeEnabled();
      expect(within(card).getByText(label)).toBeInTheDocument();
      expect(within(card).getByText(/lossy/i)).toBeInTheDocument();
    }
    // Bruno is a folder of files: its card says the export is several files.
    expect(within(screen.getByTestId('export-target-bruno')).getByText(/multi-file/)).toBeInTheDocument();
    expect(within(screen.getByTestId('export-target-insomnia')).queryByText(/multi-file/)).toBeNull();
  });

  it('offers the Postman flavor as a choice between the three collection formats', async () => {
    await renderAtTargetStep(mockFetch(COLLECTION_TARGETS));

    fireEvent.click(screen.getByTestId('export-target-postman'));
    expect(screen.getByText('Target options')).toBeInTheDocument();
    const flavor = screen.getByRole('radiogroup', { name: 'Flavor' });
    expect(within(flavor).getAllByRole('radio').map((option) => option.textContent)).toEqual([
      'postman',
      'insomnia',
      'bruno',
    ]);
    expect(within(flavor).getByRole('radio', { name: 'postman' })).toBeChecked();

    // Insomnia and Bruno carry their folder and example options, but no flavor of their own.
    fireEvent.click(screen.getByTestId('export-target-bruno'));
    expect(screen.queryByRole('radiogroup', { name: 'Flavor' })).toBeNull();
    expect(screen.getByRole('radiogroup', { name: 'Folder Strategy' })).toBeInTheDocument();
  });

  it('updates the fidelity headline for the picked collection card', async () => {
    await renderAtTargetStep(mockFetch(COLLECTION_TARGETS));

    fireEvent.click(screen.getByTestId('export-target-bruno'));
    expect(screen.getByTestId('export-fidelity-headline')).toHaveTextContent('66% preserved');
  });
});


describe('ExportDialog — JSON Schema target card (MFX-21.5)', () => {
  it('badges a REST source types-only, because its operations are dropped', async () => {
    await renderAtTargetStep(mockFetch(jsonSchemaTargets('rest')));

    const card = screen.getByTestId('export-target-json-schema');
    expect(card).toBeEnabled();
    expect(within(card).getByText('JSON Schema')).toBeInTheDocument();
    expect(within(card).getByText('types-only')).toBeInTheDocument();
    // One bundle by default: the card is not a multi-file target.
    expect(within(card).queryByText(/multi-file/)).toBeNull();
  });

  it('badges a JSON Schema item lossless', async () => {
    await renderAtTargetStep(mockFetch(jsonSchemaTargets('json-schema')));

    const card = screen.getByTestId('export-target-json-schema');
    expect(within(card).getByText('lossless')).toBeInTheDocument();
    fireEvent.click(card);
    expect(screen.getByTestId('export-fidelity-headline')).toHaveTextContent('100% preserved');
  });

  it('offers the draft, packaging and output mode as options', async () => {
    await renderAtTargetStep(mockFetch(jsonSchemaTargets('rest')));

    fireEvent.click(screen.getByTestId('export-target-json-schema'));
    expect(screen.getByText('Target options')).toBeInTheDocument();
    const choices = (name: string) =>
      within(screen.getByRole('radiogroup', { name })).getAllByRole('radio').map((option) => option.textContent);
    expect(choices('Draft')).toEqual(['2020-12', 'draft-07', 'draft-04']);
    expect(choices('Packaging')).toEqual(['bundle', 'per-type']);
    expect(choices('Mode')).toEqual(['json-schema', 'jtd']);
    expect(within(screen.getByRole('radiogroup', { name: 'Draft' })).getByRole('radio', { name: '2020-12' })).toBeChecked();
  });
});


describe('ExportDialog — COBOL copybook target card (MFX-23.5)', () => {
  it('badges a REST source types-only — copybook is one of the lossiest targets', async () => {
    await renderAtTargetStep(mockFetch(copybookTargets('rest')));

    const card = screen.getByTestId('export-target-cobolcopybook');
    expect(card).toBeEnabled();
    expect(within(card).getByText('COBOL Copybook')).toBeInTheDocument();
    expect(within(card).getByText('types-only')).toBeInTheDocument();
    fireEvent.click(card);
    // Most of the model is synthesized or approximated: the headline says how little is kept as is.
    expect(screen.getByTestId('export-fidelity-headline')).toHaveTextContent(/\d+% preserved/);
    expect(screen.getByTestId('export-fidelity-headline')).not.toHaveTextContent('100% preserved');
  });

  it('badges a copybook item lossless', async () => {
    await renderAtTargetStep(mockFetch(copybookTargets('copybook')));

    const card = screen.getByTestId('export-target-cobolcopybook');
    expect(within(card).getByText('lossless')).toBeInTheDocument();
  });

  it('offers the numeric usage, fixed format and header comment as options', async () => {
    await renderAtTargetStep(mockFetch(copybookTargets('rest')));

    fireEvent.click(screen.getByTestId('export-target-cobolcopybook'));
    expect(screen.getByText('Target options')).toBeInTheDocument();
    const usage = screen.getByRole('radiogroup', { name: 'Numeric Usage' });
    expect(within(usage).getAllByRole('radio').map((option) => option.textContent)).toEqual(['comp', 'display']);
    expect(within(usage).getByRole('radio', { name: 'comp' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /Fixed Format/ })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /Include Comments/ })).toBeChecked();
    // The integer layout defaults (string length, occurs, decimal scale) have no generic form
    // control, so they stay at their server defaults here and are set with the CLI's --option.
    expect(screen.queryByText('Default Occurs')).toBeNull();
  });
});


describe('ExportDialog — X12 implementation guide target card (MFX-24.5)', () => {
  it.each(['rest', 'x12'] as const)('badges a %s source types-only and marks the guide multi-file', async (source) => {
    await renderAtTargetStep(mockFetch(x12GuideTargets(source)));

    const card = screen.getByTestId('export-target-x12-guide');
    expect(card).toBeEnabled();
    expect(within(card).getByText('X12 implementation guide')).toBeInTheDocument();
    expect(within(card).getByText('types-only')).toBeInTheDocument();
    // The JSON guide, the segment CSV and the Markdown guide come as one download.
    expect(within(card).getByText(/multi-file/)).toBeInTheDocument();
  });

  it('offers the transaction set and version as the picker', async () => {
    await renderAtTargetStep(mockFetch(x12GuideTargets('rest')));

    fireEvent.click(screen.getByTestId('export-target-x12-guide'));
    expect(screen.getByText('Target options')).toBeInTheDocument();
    const transactionSet = screen.getByLabelText('Transaction Set');
    const version = screen.getByLabelText('Version');
    // Empty means the server default: an imported X12 item's own set and release, else 850 / 005010.
    expect(transactionSet).toHaveValue('');
    expect(version).toHaveValue('');
    fireEvent.change(transactionSet, { target: { value: '810' } });
    expect(transactionSet).toHaveValue('810');
  });
});
