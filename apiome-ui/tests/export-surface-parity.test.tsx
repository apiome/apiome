/**
 * Export surface parity for the Export dialog — MFX-40.3 (#4341).
 *
 * The UI leg of the four-surface parity contract (UI, browse, CLI, MCP): fed the very previews
 * apiome-rest answers for each fixture source, the dialog's Fidelity step (`FidelityWarningPanel`) must
 *
 * - render the server's advisory **verbatim** — the headline and message the browse page, `apiome
 *   export` and the MCP `version.export` `advisory` carry — and only the quiet headline when lossless;
 * - read the report shape: every construct of the report is listed, with its kind badge;
 * - ask for the "Export anyway" acknowledgement exactly where MCP needs `allow_lossy` and the CLI
 *   `--force`: any tier other than `lossless`.
 *
 * Fixture: `tests/fixtures/exportSurfaceParity.json`, a checked-in copy of apiome-rest's golden
 * `tests/fixtures/export_surface_parity.json`; apiome-rest fails CI when the copy is stale. Regenerate
 * every copy together in apiome-rest with `pytest tests/test_export_surface_parity.py --update-golden`.
 */

import React from 'react';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import { FidelityWarningPanel } from '../src/app/components/ade/dashboard/export/FidelityWarningPanel';
import type {
  ExportFidelityEnvelope,
  ExportPreviewResponse,
} from '../src/app/components/ade/dashboard/export/exportFidelityPreview';

interface Golden {
  sources: Record<string, { previews: Record<string, ExportFidelityEnvelope> }>;
}

const golden: Golden = JSON.parse(readFileSync(join(__dirname, 'fixtures', 'exportSurfaceParity.json'), 'utf8'));

const cases: [string, string, ExportFidelityEnvelope][] = Object.entries(golden.sources).flatMap(([source, entry]) =>
  Object.entries(entry.previews).map(([target, fidelity]) => [source, target, fidelity] as [string, string, ExportFidelityEnvelope]),
);

function renderPreview(fidelity: ExportFidelityEnvelope) {
  const preview: ExportPreviewResponse = {
    artifact: 'artifact-parity',
    version: null,
    version_record_id: 'rev-parity',
    version_label: '1.0.0',
    fidelity,
  };
  render(
    <FidelityWarningPanel
      targetLabel={fidelity.target.label}
      targetDescription={fidelity.target.description ?? ''}
      fidelity={fidelity.summary}
      preview={preview}
      previewLoading={false}
      previewError={null}
      acknowledged={false}
      onAcknowledgedChange={jest.fn()}
    />,
  );
}

it('covers every fidelity tier', () => {
  expect(new Set(cases.map(([, , fidelity]) => fidelity.summary.tier))).toEqual(new Set(['lossless', 'lossy', 'types-only']));
});

describe.each(cases)('%s → %s', (_source, _target, fidelity) => {
  it('renders the server advisory verbatim', () => {
    renderPreview(fidelity);
    const advisory = screen.getByTestId('export-advisory');
    expect(advisory).toHaveTextContent(fidelity.advisory.headline);
    if (fidelity.advisory.show) {
      expect(advisory).toHaveTextContent(fidelity.advisory.message);
    } else {
      expect(advisory).not.toHaveTextContent(fidelity.advisory.message);
    }
  });

  it('lists every construct of the report with its kind', () => {
    renderPreview(fidelity);
    if (fidelity.report.items.length === 0) return;
    fireEvent.click(screen.getByTestId('export-report-toggle'));
    const report = screen.getByTestId('export-fidelity-report');
    expect(report.querySelectorAll('li')).toHaveLength(fidelity.report.items.length);
    for (const item of fidelity.report.items) {
      expect(within(report).getAllByText(item.construct).length).toBeGreaterThan(0);
    }
  });

  it('asks for the acknowledgement exactly where MCP needs allow_lossy', () => {
    renderPreview(fidelity);
    const asked = screen.queryByTestId('export-ack') ?? screen.queryByTestId('export-ack-typed');
    if (fidelity.summary.tier === 'lossless') {
      expect(asked).toBeNull();
    } else {
      expect(asked).not.toBeNull();
    }
  });
});
