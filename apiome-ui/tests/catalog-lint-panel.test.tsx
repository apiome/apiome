/**
 * Render/interaction tests for the inline Lint & Score panel (MFI-25.5, #4090).
 *
 * The panel must fetch the server lint report lazily on first activation, render the grade gauge
 * (letter + score), the findings list (severity + rule + message + MUST/SHOULD), and the category
 * bars — real per-category scores when the report carries them (MFI-25.6), else a severity
 * breakdown derived from the findings. It also exposes the full-report / quality-history actions and
 * a retry on failure.
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import { CatalogLintPanel } from '../src/app/components/ade/dashboard/catalog/CatalogLintPanel';
import type { VersionLintReport } from '../src/app/utils/version-lint-report';

const ITEM_ID = 'item-1';

const BASE_REPORT: VersionLintReport = {
  projectId: ITEM_ID,
  versionRecordId: 'rev-1',
  versionId: '1.0.0',
  score: 72,
  grade: 'B',
  findings: [
    {
      id: 'f-err',
      path: 'components.schemas.Payment',
      category: 'structure',
      rule: 'structure.operation-missing-id',
      severity: 'error',
      message: 'Operation is missing an operationId.',
    },
    {
      id: 'f-warn',
      path: 'components.schemas.Order',
      category: 'documentation',
      rule: 'documentation.schema-missing-description',
      severity: 'warning',
      message: 'Schema is missing a description.',
    },
  ],
  ruleHits: {},
  severityCounts: { error: 1, warning: 1, info: 0 },
  reportFingerprint: 'fp',
  baseRevisionId: null,
  compatibilityOverall: null,
};

/** Mock `fetch` to resolve the given report (ok) or a JSON error (not ok). */
function mockLintFetch(report: unknown, ok = true) {
  global.fetch = jest.fn().mockResolvedValue({
    ok,
    status: ok ? 200 : 500,
    json: async () => (ok ? { success: true, ...(report as object) } : { success: false, error: 'boom' }),
  }) as unknown as typeof fetch;
}

function renderPanel(
  overrides: Partial<React.ComponentProps<typeof CatalogLintPanel>> = {},
) {
  const onOpenReport = jest.fn();
  const onOpenQualityHistory = jest.fn();
  const utils = render(
    <CatalogLintPanel
      itemId={ITEM_ID}
      active
      onOpenReport={onOpenReport}
      onOpenQualityHistory={onOpenQualityHistory}
      qualityAvailable
      {...overrides}
    />,
  );
  return { ...utils, onOpenReport, onOpenQualityHistory };
}

describe('CatalogLintPanel (MFI-25.5)', () => {
  afterEach(() => jest.restoreAllMocks());

  it('does not fetch until the tab is active', () => {
    mockLintFetch(BASE_REPORT);
    renderPanel({ active: false });
    expect(global.fetch).not.toHaveBeenCalled();
    expect(screen.getByTestId('catalog-lint-loading')).toBeInTheDocument();
  });

  it('fetches the report lazily on activation and renders the gauge + findings', async () => {
    mockLintFetch(BASE_REPORT);
    renderPanel();

    await screen.findByTestId('catalog-lint-gauge');
    expect(global.fetch).toHaveBeenCalledWith(
      `/api/catalog/${ITEM_ID}/lint`,
      expect.objectContaining({ method: 'GET' }),
    );
    // Gauge shows the server letter grade + score/100.
    expect(screen.getByTestId('catalog-lint-gauge-grade')).toHaveTextContent('B');
    expect(screen.getByTestId('catalog-lint-gauge')).toHaveTextContent('72/100');

    // Findings carry rule + message and are grouped into MUST/SHOULD/advisory tiers (MFI-28.2).
    const findings = screen.getByTestId('catalog-lint-findings');
    expect(findings).toHaveTextContent('structure.operation-missing-id');
    expect(findings).toHaveTextContent('Operation is missing an operationId.');

    const mustSection = screen.getByTestId('catalog-lint-tier-must');
    expect(mustSection).toHaveTextContent('MUST');
    expect(mustSection).toHaveTextContent('structure.operation-missing-id'); // error → MUST
    expect(screen.getByTestId('catalog-lint-tier-count-must')).toHaveTextContent('1');

    const shouldSection = screen.getByTestId('catalog-lint-tier-should');
    expect(shouldSection).toHaveTextContent('SHOULD');
    expect(shouldSection).toHaveTextContent('documentation.schema-missing-description'); // warning → SHOULD
    expect(screen.getByTestId('catalog-lint-tier-count-should')).toHaveTextContent('1');

    // No advisory (info) findings → the advisory section is not rendered.
    expect(screen.queryByTestId('catalog-lint-tier-advisory')).not.toBeInTheDocument();
  });

  it('groups info findings into the advisory tier', async () => {
    mockLintFetch({
      ...BASE_REPORT,
      findings: [
        {
          id: 'f-info',
          path: 'info.contact',
          category: 'documentation',
          rule: 'documentation.missing-contact',
          severity: 'info',
          message: 'No contact information.',
        },
      ],
      severityCounts: { error: 0, warning: 0, info: 1 },
    });
    renderPanel();
    const advisory = await screen.findByTestId('catalog-lint-tier-advisory');
    expect(advisory).toHaveTextContent('Advisory');
    expect(advisory).toHaveTextContent('documentation.missing-contact');
    expect(screen.getByTestId('catalog-lint-tier-count-advisory')).toHaveTextContent('1');
    expect(screen.queryByTestId('catalog-lint-tier-must')).not.toBeInTheDocument();
  });

  it('renders the provenance strip (version, source, fingerprint)', async () => {
    mockLintFetch(BASE_REPORT);
    renderPanel({ scoredAt: '2026-06-30T12:00:00Z' });

    const strip = await screen.findByTestId('catalog-lint-provenance');
    expect(strip).toHaveTextContent('1.0.0'); // version label
    expect(strip).toHaveTextContent('fp'); // report fingerprint
    // No captured score on the base report → the score is a live computation.
    expect(screen.getByTestId('catalog-lint-provenance-source')).toHaveTextContent('Computed live');
  });

  it('marks the source "Stored report" when a fresh captured score is present', async () => {
    mockLintFetch({ ...BASE_REPORT, capturedScore: 72, capturedGrade: 'B', scoreIsStale: false });
    renderPanel();
    await screen.findByTestId('catalog-lint-provenance-source');
    expect(screen.getByTestId('catalog-lint-provenance-source')).toHaveTextContent('Stored report');
  });

  it('flags a stale stored score in the provenance strip', async () => {
    mockLintFetch({ ...BASE_REPORT, capturedScore: 40, capturedGrade: 'F', scoreIsStale: true });
    renderPanel();
    await screen.findByTestId('catalog-lint-provenance-source');
    expect(screen.getByTestId('catalog-lint-provenance-source')).toHaveTextContent(/stale/i);
  });

  it('deep-links an entity-scoped finding to its Overview entity', async () => {
    mockLintFetch(BASE_REPORT);
    const onNavigateToEntity = jest.fn();
    // Both BASE_REPORT findings target components.schemas.{Payment,Order}.
    renderPanel({ entityNames: ['Payment', 'Order'], onNavigateToEntity });
    await screen.findByTestId('catalog-lint-gauge');

    const links = screen.getAllByTestId('catalog-lint-finding-link');
    expect(links).toHaveLength(2);
    // Most-severe first: the error (Payment) leads.
    fireEvent.click(links[0]);
    expect(onNavigateToEntity).toHaveBeenCalledWith('Payment');
  });

  it('renders finding paths as plain text when no parsed entity matches', async () => {
    mockLintFetch(BASE_REPORT);
    renderPanel({ entityNames: [], onNavigateToEntity: jest.fn() });
    await screen.findByTestId('catalog-lint-gauge');
    expect(screen.queryByTestId('catalog-lint-finding-link')).not.toBeInTheDocument();
    // The path still renders, just not as a link.
    expect(screen.getByTestId('catalog-lint-findings')).toHaveTextContent('components.schemas.Payment');
  });

  it('fetches only once even when re-activated', async () => {
    mockLintFetch(BASE_REPORT);
    const { rerender } = renderPanel();
    await screen.findByTestId('catalog-lint-gauge');
    expect(global.fetch).toHaveBeenCalledTimes(1);

    rerender(
      <CatalogLintPanel
        itemId={ITEM_ID}
        active={false}
        onOpenReport={jest.fn()}
        onOpenQualityHistory={jest.fn()}
        qualityAvailable
      />,
    );
    rerender(
      <CatalogLintPanel
        itemId={ITEM_ID}
        active
        onOpenReport={jest.fn()}
        onOpenQualityHistory={jest.fn()}
        qualityAvailable
      />,
    );
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  it('falls back to a severity breakdown when no category scores are present', async () => {
    mockLintFetch(BASE_REPORT);
    renderPanel();

    await screen.findByTestId('catalog-lint-categories');
    // No real score bars…
    expect(screen.queryByTestId('catalog-lint-category-bar')).not.toBeInTheDocument();
    // …but a severity breakdown per category, structure (error) ranked first.
    const rows = screen.getAllByTestId('catalog-lint-category-breakdown');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('Structure');
    expect(screen.getByTestId('catalog-lint-categories')).toHaveTextContent(/MFI-25.6/);
  });

  it('renders real category score bars when the report carries them (MFI-25.6)', async () => {
    mockLintFetch({
      ...BASE_REPORT,
      categories: [
        { name: 'documentation', score: 90 },
        { name: 'structure', score: 55 },
      ],
    });
    renderPanel();

    const bars = await screen.findAllByTestId('catalog-lint-category-bar');
    expect(bars).toHaveLength(2);
    expect(bars[0]).toHaveTextContent('Documentation');
    expect(bars[0]).toHaveTextContent('90');
    // The severity-breakdown fallback is not used when real scores exist.
    expect(screen.queryByTestId('catalog-lint-category-breakdown')).not.toBeInTheDocument();
  });

  it('shows the clean-bill message when there are no findings', async () => {
    mockLintFetch({ ...BASE_REPORT, findings: [], severityCounts: { error: 0, warning: 0, info: 0 } });
    renderPanel();
    await screen.findByTestId('catalog-lint-no-findings');
    expect(screen.getByTestId('catalog-lint-no-findings')).toHaveTextContent('clean bill of health');
  });

  it('surfaces an error with a working retry', async () => {
    mockLintFetch(null, false);
    renderPanel();

    await screen.findByTestId('catalog-lint-error');
    expect(screen.getByTestId('catalog-lint-error')).toHaveTextContent('boom');

    // Retry now succeeds and renders the report.
    mockLintFetch(BASE_REPORT);
    fireEvent.click(screen.getByTestId('catalog-lint-retry'));
    await screen.findByTestId('catalog-lint-gauge');
  });

  it('wires the full-report and quality-history actions', async () => {
    mockLintFetch(BASE_REPORT);
    const { onOpenReport, onOpenQualityHistory } = renderPanel();
    await screen.findByTestId('catalog-lint-gauge');

    fireEvent.click(screen.getByTestId('catalog-detail-lint-report'));
    expect(onOpenReport).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId('catalog-detail-quality-history'));
    expect(onOpenQualityHistory).toHaveBeenCalledTimes(1);
  });

  it('disables the quality-history action when no score exists', async () => {
    mockLintFetch(BASE_REPORT);
    renderPanel({ qualityAvailable: false });
    await screen.findByTestId('catalog-lint-gauge');
    expect(screen.getByTestId('catalog-detail-quality-history')).toBeDisabled();
  });
});
