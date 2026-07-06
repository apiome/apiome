/**
 * ExportStudio — the full-page Export Studio route + stepper shell (MFX-41.1, #4348).
 *
 * Covers the ticket's acceptance criteria:
 *  1. The Studio opens scoped to a source (name + resolved version), with the target carried from
 *     the dialog escalation pre-selected.
 *  2. All registered targets render in the shared grid with their per-source fidelity badges.
 *  3. The generated options form validates against the emitter schema and gates the Options step.
 *  4. Stepper state (selected target, option values) survives navigating back and forth.
 *  5. Forward navigation is gated: no Verify until a target is picked; no Generate until Verify
 *     ran (or was skipped with the lossy loss acknowledged).
 *  6. Generate emits via `POST /api/export/document` into the Review preview card.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

jest.mock('@monaco-editor/react', () => ({
  __esModule: true,
  default: ({ value, language }: { value?: string; language?: string }) => (
    <div data-testid="export-artifact-content" data-language={language}>
      {value}
    </div>
  ),
}));

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={typeof href === 'string' ? href : '#'}>{children}</a>
  ),
}));

import { ExportStudio } from '../src/app/components/ade/dashboard/export/ExportStudio';
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
        unavailable_reason: 'Requires the avro toolchain.',
      },
      capability_profile: {},
      options_schema: {},
      default_options: {},
      fidelity: { tier: 'types-only', preserved_percent: 31, total: 58, preserved: 18, dropped: 38, approximated: 2, synthesized: 0 },
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
      fidelity: { tier: 'lossless', preserved_percent: 100, total: 58, preserved: 58, dropped: 0, approximated: 0, synthesized: 0 },
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
        type: 'object',
        required: ['package'],
        properties: {
          emit_services: { type: 'boolean', default: true, title: 'Emit Services', description: 'Emit service/rpc blocks.' },
          package: { anyOf: [{ type: 'string' }, { type: 'null' }], default: null, title: 'Package' },
        },
      },
      default_options: { emit_services: true, package: null },
      fidelity: { tier: 'lossy', preserved_percent: 64, total: 58, preserved: 51, dropped: 3, approximated: 2, synthesized: 2 },
    },
  ],
};

const PREVIEWS: Record<string, ExportFidelityEnvelope> = {
  proto: {
    target: TARGETS.targets[2].descriptor,
    summary: TARGETS.targets[2].fidelity,
    report: {
      items: [
        { construct: 'User.email', kind: 'drop', severity: 'warn', message: 'Unrepresentable in proto3.', target_mapping: null },
      ],
      kind_counts: { drop: 1, approx: 0, synth: 0, ok: 0 },
      severity_counts: { info: 0, warn: 1, critical: 0 },
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
      items: [{ construct: 'User.name', kind: 'ok', severity: 'info', message: 'Carried faithfully.', target_mapping: null }],
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
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ success: true, ...TARGETS }) });
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
    if (url.includes('/api/export/document') && init?.method === 'POST') {
      const target = String(JSON.parse(init?.body ?? '{}').target);
      const doc =
        target === 'openapi'
          ? { filename: 'petstore.json', type: 'application/json', text: '{"openapi":"3.1.0"}' }
          : { filename: 'petstore.proto', type: 'text/plain', text: 'syntax = "proto3";' };
      return Promise.resolve({
        ok: true,
        headers: {
          get: (name: string) =>
            name.toLowerCase() === 'content-disposition'
              ? `attachment; filename="${doc.filename}"`
              : name.toLowerCase() === 'content-type'
                ? doc.type
                : null,
        },
        text: () => Promise.resolve(doc.text),
      });
    }
    // Catalog-source context for the Source step (MFX-41.2) — a non-OpenAPI (gRPC) import.
    if (url.includes('/api/catalog/')) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            success: true,
            item: {
              id: 'proj-petstore',
              name: 'Pet Store API',
              sourceFormat: 'protobuf',
              protocol: 'grpc',
              summary: { services: 3, operations: 12, types: 27, channels: null },
            },
          }),
      });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
  }) as unknown as jest.Mock;
}

/** Render the Studio and wait for the target list to load. */
async function renderStudio(
  fetchMock: jest.Mock,
  props: Partial<React.ComponentProps<typeof ExportStudio>> = {},
) {
  global.fetch = fetchMock as unknown as typeof fetch;
  const utils = render(
    <ExportStudio artifact="proj-petstore" artifactLabel="Pet Store API" version="rev-1" {...props} />,
  );
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/export/targets?artifact=proj-petstore'),
      expect.anything(),
    ),
  );
  await waitFor(() => expect(screen.getByText(/export targets available/)).toBeInTheDocument());
  return utils;
}

beforeEach(() => {
  (URL as unknown as { createObjectURL: unknown }).createObjectURL = jest.fn(() => 'blob:mock');
  (URL as unknown as { revokeObjectURL: unknown }).revokeObjectURL = jest.fn();
  jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe('ExportStudio — scope + target grid (MFX-41.1)', () => {
  it('opens scoped to the source with its resolved version', async () => {
    await renderStudio(mockFetch());
    expect(screen.getByTestId('export-studio')).toBeInTheDocument();
    expect(screen.getAllByText(/Pet Store API/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Version 1\.2\.0/)).toBeInTheDocument();
  });

  it('resolves the back link to the launch origin', async () => {
    await renderStudio(mockFetch(), { origin: 'catalog' });
    expect(screen.getByRole('link', { name: /back to catalog/i })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /back to versions/i })).not.toBeInTheDocument();
  });

  it('defaults the back link to Versions when no origin was carried', async () => {
    await renderStudio(mockFetch());
    expect(screen.getByRole('link', { name: /back to versions/i })).toBeInTheDocument();
  });

  it('shows catalog-item context on the Source step for a catalog launch (MFX-41.2)', async () => {
    await renderStudio(mockFetch(), { origin: 'catalog', sourceFormat: 'protobuf' });

    // The Source step carries the item's provenance — format + paradigm pills and the counts.
    const context = await screen.findByTestId('export-studio-catalog-context');
    expect(context).toHaveTextContent(/Protobuf/i);
    expect(context).toHaveTextContent(/gRPC|grpc/i);
    const counts = screen.getByTestId('export-studio-catalog-counts');
    expect(counts).toHaveTextContent('3');
    expect(counts).toHaveTextContent('Services');
    expect(counts).toHaveTextContent('Operations');
    // A null count (channels) is omitted, not shown as a zero.
    expect(counts).not.toHaveTextContent('Channels');
    // The Source step restates that exporting never turns the item into a project.
    expect(screen.getByTestId('export-studio-body')).toHaveTextContent(
      /never turns the item into a project/i,
    );
  });

  it('shows no catalog context for a version launch', async () => {
    await renderStudio(mockFetch(), { origin: 'versions' });
    expect(screen.queryByTestId('export-studio-catalog-context')).not.toBeInTheDocument();
  });

  it('renders all five stepper stops', async () => {
    await renderStudio(mockFetch());
    for (const key of ['source', 'target', 'options', 'verify', 'review']) {
      expect(screen.getByTestId(`export-studio-step-${key}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId('export-studio-step-source')).toHaveAttribute('data-state', 'current');
  });

  it('renders every registered target with its fidelity badge on the Target step', async () => {
    await renderStudio(mockFetch());
    fireEvent.click(screen.getByRole('button', { name: /choose target/i }));

    expect(screen.getByTestId('export-target-openapi')).toHaveTextContent('lossless');
    expect(screen.getByTestId('export-target-proto')).toHaveTextContent('lossy');
    expect(screen.getByTestId('export-target-avro')).toHaveTextContent('types-only');
    expect(screen.getByTestId('export-target-avro')).toBeDisabled();
  });

  it('pre-selects the target carried from the dialog escalation', async () => {
    await renderStudio(mockFetch(), { initialTarget: 'proto' });
    fireEvent.click(screen.getByRole('button', { name: /choose target/i }));
    // The fidelity headline reflects the pre-selected target without a manual pick.
    expect(screen.getByTestId('export-fidelity-headline')).toHaveTextContent('gRPC / Protobuf');
    expect(screen.getByRole('button', { name: /^continue$/i })).toBeEnabled();
  });

  it('hides the same-format target and offers the original source when the format is known', async () => {
    await renderStudio(mockFetch(), { sourceFormat: 'protobuf' });
    fireEvent.click(screen.getByRole('button', { name: /choose target/i }));

    // proto (a protobuf emitter) is dropped — re-exporting to the source format is redundant.
    expect(screen.queryByTestId('export-target-proto')).not.toBeInTheDocument();
    expect(screen.getByTestId('export-target-openapi')).toBeInTheDocument();

    // The "Original source" option downloads the stored source from the catalog endpoint.
    const original = screen.getByTestId('export-original-source');
    expect(original).toHaveTextContent(/protobuf/i);
    expect(screen.getByTestId('export-original-source-download')).toHaveAttribute(
      'href',
      '/api/catalog/proj-petstore/source',
    );
  });
});

describe('ExportStudio — step gating + options validation (MFX-41.1)', () => {
  it('blocks reaching Verify until a target is picked', async () => {
    await renderStudio(mockFetch());
    fireEvent.click(screen.getByRole('button', { name: /choose target/i }));
    // No target picked yet: Continue is disabled.
    expect(screen.getByRole('button', { name: /^continue$/i })).toBeDisabled();
    fireEvent.click(screen.getByTestId('export-target-openapi'));
    expect(screen.getByRole('button', { name: /^continue$/i })).toBeEnabled();
  });

  it('gates the Options step until a required option validates', async () => {
    await renderStudio(mockFetch(), { initialTarget: 'proto' });
    fireEvent.click(screen.getByRole('button', { name: /choose target/i }));
    fireEvent.click(screen.getByRole('button', { name: /^continue$/i })); // → options

    // proto marks `package` required; empty fails validation and blocks Continue.
    expect(screen.getByRole('button', { name: /^continue$/i })).toBeDisabled();
    expect(screen.getByText(/Package is required\./)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/Package/i), { target: { value: 'com.example' } });
    expect(screen.queryByText(/Package is required\./)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^continue$/i })).toBeEnabled();
  });

  it('shows a no-options note for a target without options', async () => {
    await renderStudio(mockFetch(), { initialTarget: 'openapi' });
    fireEvent.click(screen.getByRole('button', { name: /choose target/i }));
    fireEvent.click(screen.getByRole('button', { name: /^continue$/i })); // → options
    expect(screen.getByTestId('export-studio-no-options')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^continue$/i })).toBeEnabled();
  });

  it('preserves the selected target and option values across back/forward navigation', async () => {
    await renderStudio(mockFetch(), { initialTarget: 'proto' });
    fireEvent.click(screen.getByRole('button', { name: /choose target/i }));
    fireEvent.click(screen.getByRole('button', { name: /^continue$/i })); // → options
    fireEvent.change(screen.getByLabelText(/Package/i), { target: { value: 'com.example' } });

    // Back to Target, then forward to Options again: the value survives.
    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));
    expect(screen.getByTestId('export-fidelity-headline')).toHaveTextContent('gRPC / Protobuf');
    fireEvent.click(screen.getByRole('button', { name: /^continue$/i }));
    expect(screen.getByLabelText(/Package/i)).toHaveValue('com.example');
  });
});

describe('ExportStudio — verify gate + generate (MFX-41.1)', () => {
  /** Drive a lossless target from the grid to the Verify step. */
  async function advanceToVerify(fetchMock: jest.Mock, target: string) {
    await renderStudio(fetchMock, { initialTarget: target });
    fireEvent.click(screen.getByRole('button', { name: /choose target/i }));
    fireEvent.click(screen.getByRole('button', { name: /^continue$/i })); // → options
    if (target === 'proto') {
      fireEvent.change(screen.getByLabelText(/Package/i), { target: { value: 'com.example' } });
    }
    fireEvent.click(screen.getByRole('button', { name: /^continue$/i })); // → verify
  }

  it('runs the dry-run verify and generates a lossless target without acknowledgement', async () => {
    const fetchMock = mockFetch();
    await advanceToVerify(fetchMock, 'openapi');

    await waitFor(() =>
      expect(screen.getByTestId('export-advisory')).toHaveTextContent('Lossless export to OpenAPI 3.1'),
    );
    // Verify ran (preview settled): can proceed to review with no acknowledgement.
    const toReview = screen.getByRole('button', { name: /continue to review/i });
    await waitFor(() => expect(toReview).toBeEnabled());
    fireEvent.click(toReview);

    fireEvent.click(screen.getByTestId('export-studio-generate'));
    await waitFor(() => expect(screen.getByTestId('export-artifact-preview')).toBeInTheDocument());
    expect(screen.getByTestId('export-artifact-preview')).toHaveTextContent('petstore.json');
  });

  it('keeps a lossy target from proceeding until the loss is acknowledged', async () => {
    const fetchMock = mockFetch();
    await advanceToVerify(fetchMock, 'proto');
    await waitFor(() => expect(screen.getByTestId('export-advisory')).toBeInTheDocument());

    const toReview = screen.getByRole('button', { name: /continue to review/i });
    expect(toReview).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox'));
    expect(toReview).toBeEnabled();
  });

  it('generates a lossy target and sends only the changed options', async () => {
    const fetchMock = mockFetch();
    await advanceToVerify(fetchMock, 'proto');
    await waitFor(() => expect(screen.getByTestId('export-advisory')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: /continue to review/i }));

    expect(screen.getByTestId('export-studio-review-summary')).toHaveTextContent('gRPC / Protobuf');
    fireEvent.click(screen.getByTestId('export-studio-generate'));

    await waitFor(() => expect(screen.getByTestId('export-artifact-preview')).toBeInTheDocument());
    const documentCall = fetchMock.mock.calls.find(([url]) =>
      String(url).includes('/api/export/document'),
    );
    expect(documentCall).toBeDefined();
    const body = JSON.parse((documentCall![1] as { body: string }).body);
    expect(body).toEqual({
      artifact: 'proj-petstore',
      version: 'rev-1',
      target: 'proto',
      options: { package: 'com.example' },
    });
  });

  it('reports the generated artifact via onGenerated', async () => {
    const onGenerated = jest.fn();
    const fetchMock = mockFetch();
    await renderStudio(fetchMock, { initialTarget: 'openapi', onGenerated });
    fireEvent.click(screen.getByRole('button', { name: /choose target/i }));
    fireEvent.click(screen.getByRole('button', { name: /^continue$/i })); // → options
    fireEvent.click(screen.getByRole('button', { name: /^continue$/i })); // → verify
    await waitFor(() => expect(screen.getByTestId('export-advisory')).toBeInTheDocument());
    const toReview = screen.getByRole('button', { name: /continue to review/i });
    await waitFor(() => expect(toReview).toBeEnabled());
    fireEvent.click(toReview);
    fireEvent.click(screen.getByTestId('export-studio-generate'));

    await waitFor(() => expect(onGenerated).toHaveBeenCalledTimes(1));
    expect(onGenerated).toHaveBeenCalledWith({
      targetKey: 'openapi',
      targetLabel: 'OpenAPI 3.1',
      tier: 'lossless',
      preservedPercent: 100,
      filename: 'petstore.json',
    });
  });

  it('downloads the generated file and a .zip from the Review step', async () => {
    const downloads: string[] = [];
    jest
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(function (this: HTMLAnchorElement) {
        downloads.push(this.download);
      });
    const fetchMock = mockFetch();
    await renderStudio(fetchMock, { initialTarget: 'openapi' });
    fireEvent.click(screen.getByRole('button', { name: /choose target/i }));
    fireEvent.click(screen.getByRole('button', { name: /^continue$/i }));
    fireEvent.click(screen.getByRole('button', { name: /^continue$/i }));
    await waitFor(() => expect(screen.getByTestId('export-advisory')).toBeInTheDocument());
    const toReview = screen.getByRole('button', { name: /continue to review/i });
    await waitFor(() => expect(toReview).toBeEnabled());
    fireEvent.click(toReview);
    fireEvent.click(screen.getByTestId('export-studio-generate'));
    await waitFor(() => expect(screen.getByTestId('export-artifact-preview')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /download petstore\.json/i }));
    fireEvent.click(screen.getByRole('button', { name: /download \.zip/i }));
    expect(downloads).toEqual(['petstore.json', 'petstore.zip']);
  });
});
