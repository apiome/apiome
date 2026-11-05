import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { PublicFidelityWarningPanel } from '../../src/app/components/export/PublicFidelityWarningPanel';
import { advisoryPresentation } from '../export/export-advisory';
import {
  fidelityChips,
  sortReportItemsWorstFirst,
  type ExportFidelityEnvelope,
} from '../export/exportFidelityPreview';
import { requiresExportAcknowledgement } from '../export/publicExport';

/**
 * Export surface parity for the public browse export — MFX-40.3 (#4341).
 *
 * The browse leg of the four-surface parity contract (UI, browse, CLI, MCP): fed the very previews
 * apiome-rest answers for each fixture source, the public export dialog's fidelity step
 * (`PublicFidelityWarningPanel`) must render the server's advisory **verbatim** — the headline and
 * message the Export dialog, `apiome export` and the MCP `version.export` `advisory` carry — read the
 * report shape (every construct sorted, chips equal to the summary), and ask for the acknowledgement
 * exactly where MCP needs `allow_lossy` and the CLI `--force`.
 *
 * Fixture: `fixtures/exportSurfaceParity.json`, a checked-in copy of apiome-rest's golden
 * `tests/fixtures/export_surface_parity.json`; apiome-rest fails CI when the copy is stale. Regenerate
 * every copy together in apiome-rest with `pytest tests/test_export_surface_parity.py --update-golden`.
 */

interface Golden {
  sources: Record<string, { previews: Record<string, ExportFidelityEnvelope> }>;
}

const golden: Golden = JSON.parse(readFileSync(join(__dirname, 'fixtures', 'exportSurfaceParity.json'), 'utf8'));

const cases: [string, string, ExportFidelityEnvelope][] = Object.entries(golden.sources).flatMap(([source, entry]) =>
  Object.entries(entry.previews).map(
    ([target, fidelity]) => [source, target, fidelity] as [string, string, ExportFidelityEnvelope],
  ),
);

/** The panel, server-rendered. */
function panelMarkup(fidelity: ExportFidelityEnvelope): string {
  return renderToStaticMarkup(
    createElement(PublicFidelityWarningPanel, {
      targetLabel: fidelity.target.label,
      targetDescription: fidelity.target.description ?? '',
      fidelity: fidelity.summary,
      preview: {
        tenant_slug: 'acme',
        project_slug: 'p',
        version_slug: '1.0.0',
        version_record_id: 'rev-parity',
        version_label: '1.0.0',
        fidelity,
      },
      previewLoading: false,
      previewError: null,
      acknowledged: false,
      onAcknowledgedChange: () => {},
    }),
  );
}

/** The panel's visible text: tags stripped, entities decoded. */
function panelText(fidelity: ExportFidelityEnvelope): string {
  return panelMarkup(fidelity)
    .replace(/<[^>]+>/g, ' ')
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ');
}

it('covers every fidelity tier', () => {
  expect(new Set(cases.map(([, , fidelity]) => fidelity.summary.tier))).toEqual(
    new Set(['lossless', 'lossy', 'types-only']),
  );
});

describe.each(cases)('%s → %s', (_source, _target, fidelity) => {
  it('renders the server advisory verbatim', () => {
    const text = panelText(fidelity);
    expect(text).toContain(fidelity.advisory.headline);
    if (fidelity.advisory.show) expect(text).toContain(fidelity.advisory.message);
    else expect(text).not.toContain(fidelity.advisory.message);
  });

  it('reads the report shape', () => {
    const sorted = sortReportItemsWorstFirst(fidelity.report.items);
    expect(sorted).toHaveLength(fidelity.report.items.length);
    expect(new Set(sorted.map((item) => item.construct))).toEqual(
      new Set(fidelity.report.items.map((item) => item.construct)),
    );
    // Zero-count loss chips are omitted.
    const chips: Record<string, number> = Object.fromEntries(fidelityChips(fidelity.summary).map((chip) => [chip.key, chip.count]));
    expect(chips.dropped ?? 0).toBe(fidelity.summary.dropped);
    expect(chips.approximated ?? 0).toBe(fidelity.summary.approximated);
    expect(chips.synthesized ?? 0).toBe(fidelity.summary.synthesized);
    expect(advisoryPresentation(fidelity.advisory).requiresAck).toBe(fidelity.advisory.requires_ack);
  });

  it('asks for the acknowledgement exactly where MCP needs allow_lossy', () => {
    expect(requiresExportAcknowledgement(fidelity.summary.tier)).toBe(fidelity.summary.tier !== 'lossless');
    expect(panelMarkup(fidelity).includes('data-testid="export-ack"')).toBe(fidelity.summary.tier !== 'lossless');
  });
});
