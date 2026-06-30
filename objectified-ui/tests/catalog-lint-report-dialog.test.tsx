/**
 * Tests for the server-backed catalog lint report dialog (MFI-23.10, #4019).
 *
 * The dialog fetches lazily (only when open) and renders the same report surface Projects use via
 * the shared LintReportDialog, with an error + retry affordance when the fetch fails.
 */
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';

import { CatalogLintReportDialog } from '../src/app/components/ade/dashboard/catalog/CatalogLintReportDialog';

const REPORT = {
  success: true,
  projectId: 'cat-1',
  versionRecordId: 'rev-1',
  versionId: '1.0.0',
  score: 81,
  grade: 'B',
  findings: [
    {
      id: 'f1',
      path: 'components.schemas.Order',
      category: 'naming',
      rule: 'naming.schema-pascal-case',
      severity: 'warning',
      message: "Schema 'order' is not PascalCase.",
    },
  ],
  ruleHits: { 'naming.schema-pascal-case': 1 },
  severityCounts: { error: 0, warning: 1, info: 0 },
  reportFingerprint: 'fp',
  baseRevisionId: null,
  compatibilityOverall: null,
};

describe('CatalogLintReportDialog', () => {
  afterEach(() => jest.restoreAllMocks());

  it('does not fetch while closed', () => {
    global.fetch = jest.fn() as unknown as typeof fetch;
    render(
      <CatalogLintReportDialog itemId={null} itemName="Acme" open={false} onOpenChange={() => {}} />
    );
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('fetches lazily on open and renders the server findings', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(REPORT) });
    render(
      <CatalogLintReportDialog itemId="cat-1" itemName="Acme" open onOpenChange={() => {}} />
    );

    await waitFor(() =>
      expect(screen.getByText('naming.schema-pascal-case')).toBeInTheDocument()
    );
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/catalog/cat-1/lint',
      expect.objectContaining({ method: 'GET' })
    );
    expect(screen.getByText("Schema 'order' is not PascalCase.")).toBeInTheDocument();
  });

  it('shows an error with a retry that re-fetches successfully', async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 404,
        json: () => Promise.resolve({ success: false, detail: 'No revision to lint' }),
      })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(REPORT) });
    global.fetch = fetchMock as unknown as typeof fetch;

    render(
      <CatalogLintReportDialog itemId="cat-1" itemName="Acme" open onOpenChange={() => {}} />
    );

    await waitFor(() => expect(screen.getByTestId('lint-report-error')).toBeInTheDocument());
    expect(screen.getByText('No revision to lint')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Retry'));

    await waitFor(() =>
      expect(screen.getByText('naming.schema-pascal-case')).toBeInTheDocument()
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
