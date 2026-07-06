/**
 * VerifyWorkbench — the Studio's Verify step orchestration UI (MFX-42.1, #4354).
 *
 * Covers the ticket's acceptance surface at the component level:
 *  1. A single "Run verification" action (before a run) triggers the dry-run.
 *  2. While running, a per-lens progress state shows.
 *  3. One settled result yields all three lenses + a single verdict banner.
 *  4. An invalid result blocks with the validator's detail; a lossy one exposes the acknowledgement.
 *  5. Lenses lay out as tabs-with-badges (desktop) and an accordion (narrow), with per-lens counts.
 */

import React from 'react';
import { render, screen, fireEvent, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import { VerifyWorkbench } from '../src/app/components/ade/dashboard/export/VerifyWorkbench';
import type {
  ExportVerifyResponse,
} from '../src/app/components/ade/dashboard/export/exportVerify';
import type {
  ExportFidelityEnvelope,
  ExportFidelityTier,
} from '../src/app/components/ade/dashboard/export/exportFidelityPreview';
import type { TargetFidelitySummary } from '../src/app/components/ade/dashboard/export/exportTargetCatalog';

const SUMMARY: Record<ExportFidelityTier, TargetFidelitySummary> = {
  lossless: { tier: 'lossless', preserved_percent: 100, total: 10, preserved: 10, dropped: 0, approximated: 0, synthesized: 0 },
  lossy: { tier: 'lossy', preserved_percent: 64, total: 10, preserved: 6, dropped: 2, approximated: 1, synthesized: 1 },
  'types-only': { tier: 'types-only', preserved_percent: 31, total: 10, preserved: 3, dropped: 6, approximated: 1, synthesized: 0 },
};

function fidelity(tier: ExportFidelityTier): ExportFidelityEnvelope {
  const summary = SUMMARY[tier];
  return {
    target: {
      key: 'proto', format: 'proto-3', label: 'gRPC / Protobuf', description: 'A .proto file.',
      icon: 'binary', paradigm: 'rpc', multi_file: false, needs_toolchain: false, available: true, unavailable_reason: null,
    },
    summary,
    report: {
      items:
        tier === 'lossless'
          ? [{ construct: 'User.name', kind: 'ok', severity: 'info', message: 'Carried faithfully.', target_mapping: null }]
          : [{ construct: 'User.email', kind: 'drop', severity: 'warn', message: 'Unrepresentable in proto3.', target_mapping: null }],
      kind_counts: { drop: summary.dropped, approx: summary.approximated, synth: summary.synthesized, ok: summary.preserved },
      severity_counts: { info: 0, warn: tier === 'lossless' ? 0 : 1, critical: 0 },
    },
    advisory: {
      show: tier !== 'lossless', severity: tier === 'lossless' ? null : 'warn', requires_ack: tier !== 'lossless',
      target_format: 'gRPC / Protobuf', dropped: summary.dropped, approximated: summary.approximated, synthesized: summary.synthesized,
      affected: summary.dropped + summary.approximated + summary.synthesized,
      headline: tier === 'lossless' ? 'Lossless export to gRPC / Protobuf' : 'This export loses fidelity',
      message: 'advisory copy',
    },
  };
}

/** A clean / lossy / severe / invalid verify result, with an optional lint report. */
function makeResult(kind: 'clean' | 'lossy' | 'severe' | 'invalid', withLint = true): ExportVerifyResponse {
  const fid = fidelity(kind === 'clean' ? 'lossless' : kind === 'severe' ? 'types-only' : 'lossy');
  return {
    artifact: 'proj-1', version: null, version_record_id: 'rev-1', version_label: '1.0.0',
    fidelity: fid,
    guard:
      kind === 'severe'
        ? {
            verdict: 'near-empty', requires_confirmation: false, target_format: 'gRPC / Protobuf',
            preserved_percent: 31, dropped_operations: 6, dropped_events: 0,
            headline: 'Only schemas will be exported.', message: 'A types-only reduction.', reasons: [],
          }
        : null,
    validation:
      kind === 'invalid'
        ? {
            verdict: 'invalid', target: 'proto-3', blocks_delivery: true, warns: false, valid: false,
            findings: [
              { message: 'Field number 0 is not allowed.', file: 'petstore.proto', line: 12, column: 3, keyword: 'buf.field-number' },
            ],
            detail: null, headline: 'Invalid — export blocked', message: 'The export was blocked before delivery.',
          }
        : {
            verdict: 'valid', target: 'proto-3', blocks_delivery: false, warns: false, valid: true,
            findings: [], detail: null, headline: 'Valid', message: 'The emitted artifact re-parsed cleanly.',
          },
    lint: withLint
      ? { applicable: true, pack: 'buf-lint', score: 88, grade: 'B', findings: [{ severity: 'warning', rule: 'PACKAGE_LOWER_SNAKE_CASE', message: 'Package should be lower_snake_case.', file: 'petstore.proto', line: 1 }] }
      : { applicable: false, findings: [] },
  };
}

/** Render the workbench with sensible defaults; override any prop. */
function renderWorkbench(props: Partial<React.ComponentProps<typeof VerifyWorkbench>> = {}) {
  const onRun = jest.fn();
  const onAck = jest.fn();
  const utils = render(
    <VerifyWorkbench
      targetLabel="gRPC / Protobuf"
      targetDescription="Export services as a .proto file."
      fidelitySummary={SUMMARY.lossy}
      running={false}
      hasRun={false}
      error={null}
      result={null}
      verdict={null}
      acknowledged={false}
      onAcknowledgedChange={onAck}
      onRun={onRun}
      {...props}
    />,
  );
  return { ...utils, onRun, onAck };
}

describe('VerifyWorkbench — run action + progress (MFX-42.1)', () => {
  it('shows a single Run verification action before the first run', () => {
    const { onRun } = renderWorkbench();
    const run = screen.getByTestId('verify-run');
    expect(run).toHaveTextContent(/run verification/i);
    fireEvent.click(run);
    expect(onRun).toHaveBeenCalledTimes(1);
    // No verdict/lenses yet.
    expect(screen.queryByTestId('verify-verdict')).not.toBeInTheDocument();
  });

  it('shows a per-lens progress state while running', () => {
    renderWorkbench({ running: true, hasRun: false });
    expect(screen.getByTestId('verify-progress')).toBeInTheDocument();
    expect(screen.getByTestId('verify-progress-fidelity')).toBeInTheDocument();
    expect(screen.getByTestId('verify-progress-validation')).toBeInTheDocument();
    expect(screen.getByTestId('verify-progress-lint')).toBeInTheDocument();
    // The run button is gone while a run is in flight.
    expect(screen.queryByTestId('verify-run')).not.toBeInTheDocument();
  });

  it('surfaces a run error with a retry', () => {
    const { onRun } = renderWorkbench({ hasRun: true, error: 'Verify service is down.' });
    expect(screen.getByTestId('verify-error')).toHaveTextContent('Verify service is down.');
    fireEvent.click(screen.getByTestId('verify-rerun'));
    expect(onRun).toHaveBeenCalledTimes(1);
  });
});

describe('VerifyWorkbench — one click yields three lenses + verdict (MFX-42.1)', () => {
  it('renders the verdict banner and all three lens tabs (desktop) + accordion (narrow)', () => {
    renderWorkbench({ hasRun: true, result: makeResult('clean'), verdict: 'clean' });

    expect(screen.getByTestId('verify-verdict')).toHaveAttribute('data-verdict', 'clean');
    expect(screen.getByTestId('verify-verdict')).toHaveTextContent('Clean');

    // Tabs (desktop layout) — one per lens, each with a count badge. (The badge testid also
    // appears in the narrow accordion, so scope the lookup to the tab.)
    for (const lens of ['fidelity', 'validation', 'lint']) {
      const tab = screen.getByTestId(`verify-tab-${lens}`);
      expect(tab).toBeInTheDocument();
      expect(within(tab).getByTestId(`verify-badge-${lens}`)).toBeInTheDocument();
    }
    // Accordion (narrow layout) — the same three lenses, all bodies present.
    for (const lens of ['fidelity', 'validation', 'lint']) {
      expect(screen.getByTestId(`verify-accordion-${lens}`)).toBeInTheDocument();
    }
  });

  it('shows lens badge counts (fidelity issues, validation errors, lint findings)', () => {
    renderWorkbench({ hasRun: true, result: makeResult('invalid'), verdict: 'invalid' });
    // Lossy fidelity fixture: 2 drop + 1 approx + 1 synth = 4 non-faithful constructs.
    expect(within(screen.getByTestId('verify-tab-fidelity')).getByTestId('verify-badge-fidelity')).toHaveTextContent('4');
    // One validation error, one lint finding.
    expect(within(screen.getByTestId('verify-tab-validation')).getByTestId('verify-badge-validation')).toHaveTextContent('1');
    expect(within(screen.getByTestId('verify-tab-lint')).getByTestId('verify-badge-lint')).toHaveTextContent('1');
  });

  it('lets the user switch lenses on desktop', () => {
    renderWorkbench({ hasRun: true, result: makeResult('clean'), verdict: 'clean' });
    // Clean defaults to the fidelity panel; the validation lens is reachable by its tab.
    fireEvent.click(screen.getByTestId('verify-tab-validation'));
    expect(screen.getByTestId('verify-panel-validation')).toBeInTheDocument();
    expect(within(screen.getByTestId('verify-panel-validation')).getByTestId('verify-validation')).toBeInTheDocument();
  });
});

describe('VerifyWorkbench — invalid blocks with detail (MFX-42.1)', () => {
  it('shows the validation error detail with its location for an invalid export', () => {
    renderWorkbench({ hasRun: true, result: makeResult('invalid'), verdict: 'invalid' });
    expect(screen.getByTestId('verify-verdict')).toHaveTextContent('Invalid — export blocked');
    // An invalid verdict leads with the validation lens (its detail is what the user must act on).
    const panel = screen.getByTestId('verify-panel-validation');
    expect(within(panel).getByTestId('verify-validation-findings')).toHaveTextContent(
      'Field number 0 is not allowed.',
    );
    // The structured location renders (file · line:col · rule).
    expect(within(panel).getByTestId('verify-finding-location')).toHaveTextContent('petstore.proto');
    expect(within(panel).getByTestId('verify-finding-location')).toHaveTextContent('12:3');
    expect(within(panel).getByTestId('verify-finding-location')).toHaveTextContent('buf.field-number');
  });
});

describe('VerifyWorkbench — lens content (MFX-42.1)', () => {
  it('renders the lint score/grade and findings when a lint pack ran', () => {
    renderWorkbench({ hasRun: true, result: makeResult('lossy'), verdict: 'lossy', acknowledged: true });
    fireEvent.click(screen.getByTestId('verify-tab-lint'));
    const panel = screen.getByTestId('verify-panel-lint');
    expect(within(panel).getByTestId('verify-lint-grade')).toHaveTextContent('B · 88/100');
    expect(within(panel).getByTestId('verify-lint-findings')).toHaveTextContent('lower_snake_case');
  });

  it('shows an explicit empty state when no lint pack applies', () => {
    renderWorkbench({ hasRun: true, result: makeResult('clean', false), verdict: 'clean' });
    fireEvent.click(screen.getByTestId('verify-tab-lint'));
    expect(within(screen.getByTestId('verify-panel-lint')).getByTestId('verify-lint-empty')).toBeInTheDocument();
  });

  it('exposes the fidelity acknowledgement for a lossy conversion', () => {
    const { onAck } = renderWorkbench({
      hasRun: true,
      result: makeResult('lossy'),
      verdict: 'lossy',
      fidelitySummary: SUMMARY.lossy,
    });
    // A lossy verdict leads with the fidelity lens, where the "Export anyway" checkbox lives.
    const checkbox = within(screen.getByTestId('verify-panel-fidelity')).getByRole('checkbox');
    fireEvent.click(checkbox);
    expect(onAck).toHaveBeenCalledWith(true);
  });

  it('gates a severe (types-only) conversion behind the typed acknowledgement (MFX-42.4)', () => {
    const { onAck } = renderWorkbench({
      hasRun: true,
      result: makeResult('severe'),
      verdict: 'severe',
      fidelitySummary: SUMMARY['types-only'],
    });
    // The severe banner leads to the fidelity lens with the typed acknowledgement — no checkbox.
    expect(screen.getByTestId('verify-verdict')).toHaveAttribute('data-verdict', 'severe');
    expect(screen.getByTestId('verify-verdict')).toHaveTextContent('Severe — acknowledge to continue');
    const panel = screen.getByTestId('verify-panel-fidelity');
    expect(within(panel).queryByRole('checkbox')).not.toBeInTheDocument();
    const input = within(panel).getByTestId('export-ack-typed-input');
    fireEvent.change(input, { target: { value: 'export produces a types-only artifact' } });
    expect(onAck).toHaveBeenLastCalledWith(true);
  });
});
