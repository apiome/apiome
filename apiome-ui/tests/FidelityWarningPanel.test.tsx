/**
 * FidelityWarningPanel — the ExportDialog Fidelity step body (MFX-6.2, #3856).
 *
 * Covers the ticket's acceptance criteria at the component level:
 *  1. The advisory message (MFX-2.4) renders prominently and **verbatim** from the preview.
 *  2. The preserved-% ring and count chips show the real summary counts.
 *  3. The per-construct report expands, listing DROP/APPROX/SYNTH/OK with the source
 *     construct path and how it degrades in the target.
 *  4. A lossy conversion asks for the explicit "Export anyway" acknowledgement; a lossless
 *     one shows the quiet reassurance and no acknowledgement.
 *  5. A failed preview degrades to the summary and keeps the acknowledgement available.
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import { FidelityWarningPanel } from '../src/app/components/ade/dashboard/export/FidelityWarningPanel';
import type { ExportPreviewResponse } from '../src/app/components/ade/dashboard/export/exportFidelityPreview';
import type { TargetFidelitySummary } from '../src/app/components/ade/dashboard/export/exportTargetCatalog';

const LOSSY_SUMMARY: TargetFidelitySummary = {
  tier: 'lossy',
  preserved_percent: 64,
  total: 58,
  preserved: 51,
  dropped: 3,
  approximated: 2,
  synthesized: 2,
};

const LOSSLESS_SUMMARY: TargetFidelitySummary = {
  tier: 'lossless',
  preserved_percent: 100,
  total: 58,
  preserved: 58,
  dropped: 0,
  approximated: 0,
  synthesized: 0,
};

/** A lossy proto preview: warn advisory + a small worst-first-sortable report. */
const LOSSY_PREVIEW: ExportPreviewResponse = {
  artifact: 'proj-petstore',
  version: null,
  version_record_id: 'rev-1',
  version_label: '1.2.0',
  fidelity: {
    target: {
      key: 'proto',
      format: 'proto-3',
      label: 'gRPC / Protobuf',
      description: 'Export services and messages as a .proto file.',
      icon: 'binary',
      paradigm: 'rpc',
      multi_file: false,
      needs_toolchain: false,
    },
    summary: LOSSY_SUMMARY,
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
          construct: 'acme.PetService.GetPet',
          kind: 'synth',
          severity: 'info',
          message: 'Protobuf requires a field number; one was invented.',
          target_mapping: 'synthesized field number 3',
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
      kind_counts: { drop: 1, approx: 1, synth: 1, ok: 1 },
      severity_counts: { info: 2, warn: 2, critical: 0 },
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
      message:
        'Exporting to gRPC / Protobuf may lose some fidelity: 3 constructs dropped, 2 approximated, 2 synthesized.',
    },
  },
};

/** A lossless OpenAPI preview: suppressed advisory carrying the reassurance headline. */
const LOSSLESS_PREVIEW: ExportPreviewResponse = {
  artifact: 'proj-petstore',
  version: null,
  version_record_id: 'rev-1',
  version_label: '1.2.0',
  fidelity: {
    target: {
      key: 'openapi',
      format: 'openapi-3.1',
      label: 'OpenAPI 3.1',
      description: 'Export the canonical model as an OpenAPI 3.1 document.',
      icon: 'file-json',
      paradigm: 'rest',
      multi_file: false,
      needs_toolchain: false,
    },
    summary: LOSSLESS_SUMMARY,
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

function renderPanel(overrides: Partial<React.ComponentProps<typeof FidelityWarningPanel>> = {}) {
  const props: React.ComponentProps<typeof FidelityWarningPanel> = {
    targetLabel: 'gRPC / Protobuf',
    targetDescription: 'Export services and messages as a .proto file.',
    fidelity: LOSSY_SUMMARY,
    preview: LOSSY_PREVIEW,
    previewLoading: false,
    previewError: null,
    acknowledged: false,
    onAcknowledgedChange: jest.fn(),
    ...overrides,
  };
  render(<FidelityWarningPanel {...props} />);
  return props;
}

describe('FidelityWarningPanel — advisory (MFX-2.4 copy, verbatim)', () => {
  it('renders the server advisory headline, message, and severity pill', () => {
    renderPanel();

    const advisory = screen.getByTestId('export-advisory');
    expect(advisory).toHaveTextContent('This export loses fidelity');
    expect(advisory).toHaveTextContent(
      'Exporting to gRPC / Protobuf may lose some fidelity: 3 constructs dropped, 2 approximated, 2 synthesized.',
    );
    expect(advisory).toHaveTextContent('warn');
  });

  it('collapses to the quiet reassurance line for a lossless conversion', () => {
    renderPanel({
      targetLabel: 'OpenAPI 3.1',
      targetDescription: 'Export the canonical model as an OpenAPI 3.1 document.',
      fidelity: LOSSLESS_SUMMARY,
      preview: LOSSLESS_PREVIEW,
    });

    const advisory = screen.getByTestId('export-advisory');
    expect(advisory).toHaveTextContent('Lossless export to OpenAPI 3.1');
    // The suppressed advisory renders no warning body copy.
    expect(advisory).not.toHaveTextContent('may lose');
  });

  it('shows a loading note while the preview is in flight', () => {
    renderPanel({ preview: null, previewLoading: true });
    expect(screen.getByText(/computing the detailed fidelity report/i)).toBeInTheDocument();
  });

  it('degrades to the summary when the preview fails, without hiding the panel', () => {
    renderPanel({ preview: null, previewError: 'Preview timed out.' });

    expect(screen.getByTestId('export-advisory-error')).toHaveTextContent('Preview timed out.');
    // The summary counts and the acknowledgement remain available.
    expect(screen.getByTestId('export-preserved-percent')).toHaveTextContent('64%');
    expect(screen.getByTestId('export-ack')).toBeInTheDocument();
  });
});

describe('FidelityWarningPanel — preserved-% ring and count chips', () => {
  it('shows the real preserved-% and the four count chips', () => {
    renderPanel();

    expect(screen.getByTestId('export-preserved-percent')).toHaveTextContent('64%');
    expect(screen.getByText('3 dropped')).toBeInTheDocument();
    expect(screen.getByText('2 approximated')).toBeInTheDocument();
    expect(screen.getByText('2 synthesized')).toBeInTheDocument();
    expect(screen.getByText('51 clean')).toBeInTheDocument();
    expect(screen.getByText(/58 constructs considered/i)).toBeInTheDocument();
  });
});

describe('FidelityWarningPanel — expandable per-construct report', () => {
  it('is collapsed by default and expands to the worst-first construct list', () => {
    renderPanel();

    expect(screen.queryByTestId('export-fidelity-report')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('export-report-toggle'));

    const report = screen.getByTestId('export-fidelity-report');
    expect(report).toBeInTheDocument();

    // Every kind badge is present, and the rows read worst-first: DROP → APPROX → SYNTH → OK.
    const rows = report.querySelectorAll('li');
    expect(rows).toHaveLength(4);
    expect(rows[0]).toHaveTextContent('DROP');
    expect(rows[0]).toHaveTextContent('User.email');
    expect(rows[0]).toHaveTextContent('unrepresentable in proto3');
    expect(rows[1]).toHaveTextContent('APPROX');
    expect(rows[1]).toHaveTextContent('GET /pets/{id}');
    // "How it degrades": the target mapping is spelled out.
    expect(rows[1]).toHaveTextContent('query parameter → request message field');
    expect(rows[2]).toHaveTextContent('SYNTH');
    expect(rows[3]).toHaveTextContent('OK');
    expect(rows[3]).toHaveTextContent('User.name');
  });

  it('collapses again on a second toggle', () => {
    renderPanel();

    fireEvent.click(screen.getByTestId('export-report-toggle'));
    expect(screen.getByTestId('export-fidelity-report')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('export-report-toggle'));
    expect(screen.queryByTestId('export-fidelity-report')).not.toBeInTheDocument();
  });
});

describe('FidelityWarningPanel — "Export anyway" acknowledgement', () => {
  it('asks for the acknowledgement on a lossy conversion and reports toggles', () => {
    const props = renderPanel();

    const checkbox = screen.getByRole('checkbox');
    expect(checkbox).not.toBeChecked();
    fireEvent.click(checkbox);
    expect(props.onAcknowledgedChange).toHaveBeenCalledWith(true);
  });

  it('reflects an already-given acknowledgement', () => {
    renderPanel({ acknowledged: true });
    expect(screen.getByRole('checkbox')).toBeChecked();
  });

  it('is absent for a lossless conversion', () => {
    renderPanel({
      targetLabel: 'OpenAPI 3.1',
      targetDescription: 'Export the canonical model as an OpenAPI 3.1 document.',
      fidelity: LOSSLESS_SUMMARY,
      preview: LOSSLESS_PREVIEW,
    });
    expect(screen.queryByTestId('export-ack')).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });

  it('honours an explicit acknowledgementMode over the tier default', () => {
    // A lossy tier, but the workbench asked for no control (e.g. an invalid verdict).
    renderPanel({ acknowledgementMode: 'hidden' });
    expect(screen.queryByTestId('export-ack')).not.toBeInTheDocument();
    expect(screen.queryByTestId('export-ack-typed')).not.toBeInTheDocument();
  });
});

const TYPES_ONLY_SUMMARY: TargetFidelitySummary = {
  tier: 'types-only',
  preserved_percent: 31,
  total: 58,
  preserved: 18,
  dropped: 38,
  approximated: 2,
  synthesized: 0,
};

const ACK_PHRASE = 'export produces a types-only artifact';

describe('FidelityWarningPanel — typed acknowledgement for a severe conversion (MFX-42.4)', () => {
  function renderTyped(overrides: Partial<React.ComponentProps<typeof FidelityWarningPanel>> = {}) {
    return renderPanel({
      targetLabel: 'Apache Avro',
      targetDescription: 'Export the schemas as an Avro schema.',
      fidelity: TYPES_ONLY_SUMMARY,
      acknowledgementMode: 'typed',
      ...overrides,
    });
  }

  it('shows the typed acknowledgement (not the checkbox) and quotes the phrase', () => {
    renderTyped();
    const block = screen.getByTestId('export-ack-typed');
    expect(block).toBeInTheDocument();
    expect(block).toHaveTextContent(ACK_PHRASE);
    // The lossy checkbox is not used for a severe conversion.
    expect(screen.queryByTestId('export-ack')).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });

  it('acknowledges only once the phrase is typed exactly (case-insensitively)', () => {
    const props = renderTyped();
    const input = screen.getByTestId('export-ack-typed-input');

    // A partial phrase does not acknowledge.
    fireEvent.change(input, { target: { value: 'export produces' } });
    expect(props.onAcknowledgedChange).not.toHaveBeenCalledWith(true);
    expect(screen.queryByTestId('export-ack-typed-confirmed')).not.toBeInTheDocument();

    // The full phrase (with stray casing/spacing) acknowledges.
    fireEvent.change(input, { target: { value: '  Export Produces A Types-Only Artifact  ' } });
    expect(props.onAcknowledgedChange).toHaveBeenLastCalledWith(true);
    expect(screen.getByTestId('export-ack-typed-confirmed')).toBeInTheDocument();
  });

  it('revokes the acknowledgement when the phrase is edited away', () => {
    const props = renderTyped();
    const input = screen.getByTestId('export-ack-typed-input');
    fireEvent.change(input, { target: { value: ACK_PHRASE } });
    expect(props.onAcknowledgedChange).toHaveBeenLastCalledWith(true);
    fireEvent.change(input, { target: { value: ACK_PHRASE.slice(0, -1) } });
    expect(props.onAcknowledgedChange).toHaveBeenLastCalledWith(false);
  });

  it('seeds the input from an already-given acknowledgement', () => {
    renderTyped({ acknowledged: true });
    expect(screen.getByTestId('export-ack-typed-input')).toHaveValue(ACK_PHRASE);
    expect(screen.getByTestId('export-ack-typed-confirmed')).toBeInTheDocument();
  });
});
