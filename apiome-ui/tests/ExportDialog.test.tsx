/**
 * ExportDialog — stepped export shell + target-card grid (MFX-6.1, #3855).
 *
 * Covers the ticket's acceptance criteria:
 *  1. The target grid renders from a mocked `GET /api/export/targets` response and every card
 *     shows its per-source fidelity tier badge (`lossless` / `lossy` / `types-only`).
 *  2. Picking a target updates the fidelity headline (tier + preserved-%).
 *  3. Per-target options (MFX-1.4) render from the selected target's options schema.
 *  4. The stepper advances Source → Target → Fidelity → Export, and Export emits via
 *     `POST /api/export/document` and reports the downloaded filename.
 *  5. An unavailable target (missing toolchain) renders disabled and cannot be selected.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import { ExportDialog } from '../src/app/components/ade/dashboard/export/ExportDialog';
import type { ExportTargetsResponse } from '../src/app/components/ade/dashboard/export/exportTargetCatalog';

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

function mockFetch(): jest.Mock {
  return jest.fn((input: unknown, init?: { method?: string }) => {
    const url = typeof input === 'string' ? input : String(input);
    if (url.includes('/api/export/targets')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ success: true, ...TARGETS }),
      });
    }
    if (url.includes('/api/export/document') && init?.method === 'POST') {
      return Promise.resolve({
        ok: true,
        headers: {
          get: (name: string) =>
            name.toLowerCase() === 'content-disposition' ? 'attachment; filename="petstore.proto"' : null,
        },
        blob: () => Promise.resolve(new Blob(['syntax = "proto3";'], { type: 'text/plain' })),
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
  });

  it('exports the document, sending only changed options, and reports the filename', async () => {
    const fetchMock = mockFetch();
    await renderAtTargetStep(fetchMock);

    fireEvent.click(screen.getByTestId('export-target-proto'));
    // Change one option so the emit request carries it; the untouched option stays server-side.
    fireEvent.click(screen.getByLabelText(/Emit Services/i));
    fireEvent.click(screen.getByRole('button', { name: /^continue$/i }));
    fireEvent.click(screen.getByRole('button', { name: /^export$/i }));

    await waitFor(() =>
      expect(screen.getByText(/check your downloads/i)).toBeInTheDocument(),
    );
    expect(screen.getByText('petstore.proto')).toBeInTheDocument();

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
    expect(URL.createObjectURL).toHaveBeenCalled();

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
    fireEvent.click(screen.getByRole('button', { name: /^export$/i }));

    await waitFor(() =>
      expect(screen.getByText('Target proto is unavailable.')).toBeInTheDocument(),
    );
    // Back on the Fidelity step, the user can retry.
    expect(screen.getByRole('button', { name: /^export$/i })).toBeEnabled();
  });
});
