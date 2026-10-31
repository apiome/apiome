/**
 * Export Studio overlays (GVM-4.2, #5877): the pure model, the Overlays step and the report panel.
 *
 * The Studio-level wiring (overlays sent on Verify and Generate, the report on both steps) is
 * pinned in `tests/ExportStudio.test.tsx` beside the backend mock the other Studio flows use.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import {
  MAX_EXPORT_OVERLAYS,
  MAX_EXPORT_OVERLAY_BYTES,
  addOverlays,
  moveOverlay,
  overlayActionCount,
  overlayReportSummary,
  overlayTitle,
  overlaysRequestField,
  parseOverlayFile,
  type ExportOverlayReport,
  type ExportStudioOverlay,
} from '../src/app/components/ade/dashboard/export/exportOverlays';
import { ExportOverlaysStep } from '../src/app/components/ade/dashboard/export/ExportOverlaysStep';
import { OverlayReportPanel } from '../src/app/components/ade/dashboard/export/OverlayReportPanel';
import { verifyConfigKey } from '../src/app/components/ade/dashboard/export/exportVerifyCache';
import { multiTargetJobBody } from '../src/app/components/ade/dashboard/export/exportBatchJob';
import { resolveResumableStep } from '../src/app/components/ade/dashboard/export/exportStudioUrlState';

const PARTNER_YAML = `overlay: 1.0.0
info:
  title: Partner edition
  version: 1.0.0
actions:
  - target: $.info
    update:
      title: Pets for Partners
  - target: $.servers
    update:
      url: https://partner.example.com
`;

function overlay(name: string, actions = 1): ExportStudioOverlay {
  return {
    name,
    document: {
      overlay: '1.0.0',
      info: { title: name, version: '1' },
      actions: Array.from({ length: actions }, () => ({ target: '$.info', update: {} })),
    },
  };
}

const REPORT: ExportOverlayReport = {
  applied: ['partner.yaml'],
  ledger: [
    {
      pointer: '/info/title',
      kind: 'replaced',
      overlay: 'partner.yaml',
      action_index: 0,
      target: '$.info',
      detail: "The value at /info/title was replaced by overlay 'partner.yaml'.",
    },
    {
      pointer: '(truncated)',
      kind: 'truncated',
      overlay: null,
      action_index: null,
      target: null,
      detail: 'The overlays changed 640 value(s) in total; only the first 500 carry itemized rows here.',
    },
  ],
  findings: [
    {
      rule: 'overlay.unmatched-target',
      severity: 'warning',
      overlay: 'partner.yaml',
      action_index: 1,
      target: "$.paths['/gone']",
      message: 'The target matched nothing in the base document.',
    },
  ],
  changes: 640,
  truncated: true,
};

/** A File whose `text()` works under jsdom (older jsdom Blobs have no `text`). */
function file(name: string, text: string): File {
  const f = new File([text], name, { type: 'application/yaml' });
  Object.defineProperty(f, 'text', { value: () => Promise.resolve(text) });
  return f;
}

describe('exportOverlays model', () => {
  it('reads a YAML or JSON overlay file', () => {
    const yaml = parseOverlayFile('partner.yaml', PARTNER_YAML);
    expect(yaml.ok).toBe(true);
    if (yaml.ok) {
      expect(yaml.overlay.name).toBe('partner.yaml');
      expect(overlayActionCount(yaml.overlay)).toBe(2);
      expect(overlayTitle(yaml.overlay)).toBe('Partner edition');
    }
    const json = parseOverlayFile('env.json', JSON.stringify(overlay('env').document));
    expect(json.ok).toBe(true);
  });

  it('refuses a file that is not an overlay, does not parse, or is too large', () => {
    expect(parseOverlayFile('base.yaml', 'openapi: 3.1.0\n')).toEqual({
      ok: false,
      error: 'base.yaml is not an overlay: it has no `overlay: 1.x` line.',
    });
    expect(parseOverlayFile('list.json', '[1, 2]').ok).toBe(false);
    expect(parseOverlayFile('bad.yaml', 'overlay: [unclosed').ok).toBe(false);
    const big = parseOverlayFile('big.yaml', PARTNER_YAML, MAX_EXPORT_OVERLAY_BYTES + 1);
    expect(big).toEqual({ ok: false, error: 'big.yaml is larger than 1 MB, the most one overlay may be.' });
  });

  it('adds overlays in order, replaces a re-upload in place, and stops at the limit', () => {
    const { chain } = addOverlays([overlay('a'), overlay('b')], [overlay('c'), overlay('a', 3)]);
    expect(chain.map((o) => o.name)).toEqual(['a', 'b', 'c']);
    expect(overlayActionCount(chain[0])).toBe(3);

    const full = Array.from({ length: MAX_EXPORT_OVERLAYS }, (_, i) => overlay(`o${i}`));
    const capped = addOverlays(full, [overlay('extra'), overlay('o0', 2)]);
    expect(capped.chain).toHaveLength(MAX_EXPORT_OVERLAYS);
    expect(capped.dropped).toBe(1);
  });

  it('moves an overlay up or down and ignores out-of-range moves', () => {
    const chain = [overlay('a'), overlay('b'), overlay('c')];
    expect(moveOverlay(chain, 2, -1).map((o) => o.name)).toEqual(['a', 'c', 'b']);
    expect(moveOverlay(chain, 0, 1).map((o) => o.name)).toEqual(['b', 'a', 'c']);
    expect(moveOverlay(chain, 0, -1).map((o) => o.name)).toEqual(['a', 'b', 'c']);
    expect(moveOverlay(chain, 2, 1).map((o) => o.name)).toEqual(['a', 'b', 'c']);
  });

  it('sends no overlays field for an empty chain', () => {
    expect(overlaysRequestField([])).toBeNull();
    expect(overlaysRequestField(null)).toBeNull();
    expect(overlaysRequestField([overlay('a')])).toHaveLength(1);
  });

  it('summarises a report in one line', () => {
    expect(overlayReportSummary(REPORT)).toBe(
      '1 overlay changed 640 values · 1 action could not be applied',
    );
    expect(overlayReportSummary({ ...REPORT, applied: ['a', 'b'], changes: 1, findings: [] })).toBe(
      '2 overlays changed 1 value',
    );
  });

  it('folds the chain into the verify key without changing overlay-free keys', () => {
    const base = { artifact: 'p', version: 'v', target: 'openapi', options: null };
    expect(verifyConfigKey({ ...base, overlays: [] })).toBe(verifyConfigKey(base));
    const one = verifyConfigKey({ ...base, overlays: [overlay('a')] });
    const two = verifyConfigKey({ ...base, overlays: [overlay('a'), overlay('b')] });
    const swapped = verifyConfigKey({ ...base, overlays: [overlay('b'), overlay('a')] });
    expect(new Set([verifyConfigKey(base), one, two, swapped]).size).toBe(4);
  });

  it('carries the chain on a multi-target job body only when there is one', () => {
    expect(multiTargetJobBody('p', null, ['openapi', 'avro'], true)).not.toHaveProperty('overlays');
    expect(multiTargetJobBody('p', null, ['openapi'], false, [overlay('a')]).overlays).toHaveLength(1);
  });

  it('resumes a link on the Overlays step, and later steps at Verify', () => {
    const reach = { hasTarget: true, optionsValid: true };
    expect(resolveResumableStep('overlays', reach)).toBe('overlays');
    expect(resolveResumableStep('review', reach)).toBe('verify');
    expect(resolveResumableStep('overlays', { hasTarget: true, optionsValid: false })).toBe('options');
  });
});

describe('ExportOverlaysStep', () => {
  function renderStep(initial: ExportStudioOverlay[] = []) {
    const onChange = jest.fn<(next: ExportStudioOverlay[]) => void>();
    const utils = render(<ExportOverlaysStep overlays={initial} onChange={onChange} />);
    return { onChange, ...utils };
  }

  it('says the version exports as it is when there are no overlays', () => {
    renderStep();
    expect(screen.getByTestId('export-studio-no-overlays')).toHaveTextContent(
      'No overlays — the version exports as it is.',
    );
  });

  it('reads uploaded files into the chain and reports the ones it cannot use', async () => {
    const { onChange } = renderStep();
    fireEvent.change(screen.getByTestId('export-studio-overlay-input'), {
      target: { files: [file('partner.yaml', PARTNER_YAML), file('base.yaml', 'openapi: 3.1.0\n')] },
    });
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const [chain] = onChange.mock.calls[0];
    expect(chain.map((o) => o.name)).toEqual(['partner.yaml']);
    expect(screen.getByTestId('export-studio-overlay-errors')).toHaveTextContent(
      'base.yaml is not an overlay',
    );
  });

  it('lists the chain in order with move and remove controls', () => {
    const { onChange } = renderStep([overlay('first.yaml'), overlay('second.yaml', 2)]);
    const first = screen.getByTestId('export-studio-overlay-0');
    expect(first).toHaveTextContent('first.yaml');
    expect(screen.getByTestId('export-studio-overlay-1')).toHaveTextContent('2 actions');
    expect(within(first).getByRole('button', { name: 'Apply first.yaml earlier' })).toBeDisabled();

    fireEvent.click(within(first).getByRole('button', { name: 'Apply first.yaml later' }));
    expect(onChange.mock.calls[0][0].map((o) => o.name)).toEqual(['second.yaml', 'first.yaml']);
    fireEvent.click(within(first).getByRole('button', { name: 'Remove first.yaml' }));
    expect(onChange.mock.calls[1][0].map((o) => o.name)).toEqual(['second.yaml']);
  });

  it('disables upload at the limit and says why', () => {
    renderStep(Array.from({ length: MAX_EXPORT_OVERLAYS }, (_, i) => overlay(`o${i}.yaml`)));
    const upload = screen.getByTestId('export-studio-overlay-upload');
    expect(upload).toBeDisabled();
    expect(upload).toHaveAttribute('title', `An export applies at most ${MAX_EXPORT_OVERLAYS} overlays.`);
  });
});

describe('OverlayReportPanel', () => {
  it('shows the findings, one ledger row per changed value, and the truncation row', () => {
    render(<OverlayReportPanel report={REPORT} />);
    expect(screen.getByTestId('export-overlay-summary')).toHaveTextContent('1 overlay changed 640 values');
    expect(screen.getByTestId('export-overlay-findings')).toHaveTextContent('overlay.unmatched-target');
    expect(screen.getByTestId('export-overlay-findings')).toHaveTextContent('action 2');
    const rows = within(screen.getByTestId('export-overlay-ledger')).getAllByRole('row');
    expect(rows).toHaveLength(3); // header, one change, truncation
    expect(rows[1]).toHaveTextContent('/info/title');
    expect(rows[1]).toHaveTextContent('Replaced');
    expect(rows[1]).toHaveTextContent('partner.yaml');
    expect(rows[2]).toHaveTextContent('only the first 500');
  });

  it('omits the ledger and findings when there is nothing to list', () => {
    render(<OverlayReportPanel report={{ ...REPORT, ledger: [], findings: [], changes: 0 }} />);
    expect(screen.queryByTestId('export-overlay-ledger')).toBeNull();
    expect(screen.queryByTestId('export-overlay-findings')).toBeNull();
  });
});
