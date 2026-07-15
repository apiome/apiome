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
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
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
import type { ExportTargetsResponse } from '../src/app/components/ade/dashboard/export/exportTargetCatalog';
import type { ExportFidelityEnvelope } from '../src/app/components/ade/dashboard/export/exportFidelityPreview';

/** A three-target registry: lossless OpenAPI, lossy Protobuf (with options), unavailable Avro. */
const TARGETS: ExportTargetsResponse = {
  artifact: 'proj-petstore',
  version: null,
  version_record_id: 'rev-1',
  version_label: '1.2.0',
  targets: [
    {
      descriptor: {
        key: 'avro',
        format: 'avro-1.12',
        label: 'Avro',
        description: 'Export record schemas to Avro.',
        icon: 'layers',
        paradigm: 'data',
        multi_file: false,
        needs_toolchain: true,
        available: false,
        unavailable_reason: 'Requires the avro toolchain, which is not available in this runtime.',
      },
      capability_profile: {},
      options_schema: {},
      default_options: {},
      fidelity: {
        tier: 'types-only',
        preserved_percent: 31,
        total: 58,
        preserved: 18,
        dropped: 38,
        approximated: 2,
        synthesized: 0,
      },
    },
    {
      descriptor: {
        key: 'openapi',
        format: 'openapi-3.1',
        label: 'OpenAPI 3.1',
        description: 'Export the canonical model as an OpenAPI 3.1 document.',
        icon: 'file-json',
        paradigm: 'rest',
        multi_file: false,
        needs_toolchain: false,
        available: true,
        unavailable_reason: null,
      },
      capability_profile: { operations: true },
      options_schema: {},
      default_options: {},
      fidelity: {
        tier: 'lossless',
        preserved_percent: 100,
        total: 58,
        preserved: 58,
        dropped: 0,
        approximated: 0,
        synthesized: 0,
      },
    },
    {
      descriptor: {
        key: 'proto',
        format: 'proto-3',
        label: 'gRPC / Protobuf',
        description: 'Export services and messages as a .proto file.',
        icon: 'binary',
        paradigm: 'rpc',
        multi_file: false,
        needs_toolchain: false,
        available: true,
        unavailable_reason: null,
      },
      capability_profile: { operations: true },
      options_schema: {
        properties: {
          emit_services: {
            type: 'boolean',
            default: true,
            title: 'Emit Services',
            description: 'Emit service/rpc blocks.',
          },
          package: {
            anyOf: [{ type: 'string' }, { type: 'null' }],
            default: null,
            title: 'Package',
          },
        },
        type: 'object',
      },
      default_options: { emit_services: true, package: null },
      fidelity: {
        tier: 'lossy',
        preserved_percent: 64,
        total: 58,
        preserved: 51,
        dropped: 3,
        approximated: 2,
        synthesized: 2,
      },
    },
  ],
};

/** The MFX-6.2 dry-run previews (advisory + per-construct report) per selectable target. */
const PREVIEWS: Record<string, ExportFidelityEnvelope> = {
  proto: {
    target: TARGETS.targets[2].descriptor,
    summary: TARGETS.targets[2].fidelity,
    report: {
      items: [
        {
          construct: 'User.name',
          kind: 'ok',
          severity: 'info',
          message: 'Carried faithfully.',
          target_mapping: null,
        },
        {
          construct: 'User.email',
          kind: 'drop',
          severity: 'warn',
          message: 'The email format constraint is unrepresentable in proto3.',
          target_mapping: null,
        },
        {
          construct: 'GET /pets/{id}',
          kind: 'approx',
          severity: 'warn',
          message: 'Query parameters become request-message fields.',
          target_mapping: 'query parameter → request message field',
        },
      ],
      kind_counts: { drop: 1, approx: 1, synth: 0, ok: 1 },
      severity_counts: { info: 1, warn: 2, critical: 0 },
    },
    advisory: {
      show: true,
      severity: 'warn',
      requires_ack: false,
      target_format: 'gRPC / Protobuf',
      dropped: 3,
      approximated: 2,
      synthesized: 2,
      affected: 7,
      headline: 'This export loses fidelity',
      message: 'Exporting to gRPC / Protobuf may lose some fidelity: 7 constructs affected.',
    },
  },
  openapi: {
    target: TARGETS.targets[1].descriptor,
    summary: TARGETS.targets[1].fidelity,
    report: {
      items: [
        {
          construct: 'User.name',
          kind: 'ok',
          severity: 'info',
          message: 'Carried faithfully.',
          target_mapping: null,
        },
      ],
      kind_counts: { drop: 0, approx: 0, synth: 0, ok: 1 },
      severity_counts: { info: 1, warn: 0, critical: 0 },
    },
    advisory: {
      show: false,
      severity: null,
      requires_ack: false,
      target_format: 'OpenAPI 3.1',
      dropped: 0,
      approximated: 0,
      synthesized: 0,
      affected: 0,
      headline: 'Lossless export to OpenAPI 3.1',
      message: 'Every construct is carried faithfully to OpenAPI 3.1.',
    },
  },
};

function mockFetch(): jest.Mock {
  return jest.fn((input: unknown, init?: { method?: string; body?: string }) => {
    const url = typeof input === 'string' ? input : String(input);
    if (url.includes('/api/export/targets')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ success: true, ...TARGETS }),
      });
    }
    if (url.includes('/api/export/preview') && init?.method === 'POST') {
      const target = String(JSON.parse(init?.body ?? '{}').target);
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            success: true,
            artifact: 'proj-petstore',
            version: null,
            version_record_id: 'rev-1',
            version_label: '1.2.0',
            fidelity: PREVIEWS[target],
          }),
      });
    }
    if (url.includes('/api/export/projection-evidence') && init?.method === 'POST') {
      // A minimal, internally consistent evidence page (EFP-2.2): one retained field and
      // one dropped operation, for whichever target the dialog is previewing.
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            success: true,
            artifact: 'proj-petstore',
            version: null,
            version_record_id: 'rev-1',
            version_label: '1.2.0',
            redacted: false,
            summary: {
              manifest_hash: 'hash-dialog-evidence',
              target: {},
              status_counts: { retained: 1, dropped: 1 },
              reason_counts: { destination_unsupported: 1 },
              total_constructs: 2,
              node_count: 3,
              edge_count: 2,
              evidence_count: 2,
              is_lossless: false,
              worst_severity: 'warn',
              truncated: false,
            },
            page: {
              manifest_hash: 'hash-dialog-evidence',
              nodes: [
                { id: 'c1', kind: 'canonical', label: 'User.name', construct_key: 'User.name' },
                { id: 'c2', kind: 'canonical', label: 'Sub.onPing', construct_key: 'Sub.onPing' },
                { id: 't1', kind: 'target', label: 'name', target: { json_pointer: '/User/name' } },
              ],
              edges: [
                { id: 'pe1', relation: 'projects', source: 'c1', target: 't1', status: 'retained', severity: 'info', detail: 'Carried faithfully.' },
                { id: 'pe2', relation: 'projects', source: 'c2', target: null, status: 'dropped', severity: 'warn', reason: 'destination_unsupported', detail: 'Subscriptions are not representable.' },
              ],
              next_cursor: null,
              total: 2,
            },
          }),
      });
    }
    if (url.includes('/api/export/document') && init?.method === 'POST') {
      const target = String(JSON.parse(init?.body ?? '{}').target);
      const doc =
        target === 'openapi'
          ? { filename: 'petstore.json', type: 'application/json', text: '{"openapi":"3.1.0"}' }
          : { filename: 'petstore.proto', type: 'text/plain', text: 'syntax = "proto3";' };
      return Promise.resolve({
        ok: true,
        headers: {
          get: (name: string) => {
            if (name.toLowerCase() === 'content-disposition') {
              return `attachment; filename="${doc.filename}"`;
            }
            return name.toLowerCase() === 'content-type' ? doc.type : null;
          },
        },
        text: () => Promise.resolve(doc.text),
      });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
  }) as unknown as jest.Mock;
}

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
      expect(screen.getByText('Target proto is unavailable.')).toBeInTheDocument(),
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

    await waitFor(() => expect(screen.getByText('Emit failed.')).toBeInTheDocument());
    expect(onExported).not.toHaveBeenCalled();
  });
});

describe('ExportDialog — Export Studio escalation (MFX-41.1)', () => {
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
