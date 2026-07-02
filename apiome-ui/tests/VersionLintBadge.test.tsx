/**
 * Server-backed version lint badge (#3609).
 */
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';

import { VersionLintBadge } from '../src/app/components/ade/dashboard/VersionLintBadge';

const REPORT = {
  success: true,
  projectId: 'p1',
  versionRecordId: 'v1',
  versionId: '1.0.0',
  score: 72,
  grade: 'C',
  findings: [
    {
      id: 'lint-1',
      path: 'components.schemas.payment',
      category: 'naming',
      rule: 'naming.schema-pascal-case',
      severity: 'warning',
      message: "Schema 'payment' is not PascalCase.",
    },
  ],
  ruleHits: { 'naming.schema-pascal-case': 1 },
  severityCounts: { error: 0, warning: 1, info: 0 },
  reportFingerprint: 'abc',
  baseRevisionId: null,
  compatibilityOverall: null,
};

describe('VersionLintBadge', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('fetches the server report and shows the grade and score', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(REPORT) });

    render(<VersionLintBadge projectId="p1" versionId="v1" versionLabel="1.0.0" />);

    await waitFor(() => expect(screen.getByTestId('version-lint-badge')).toBeInTheDocument());
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/projects/p1/versions/v1/lint',
      expect.objectContaining({ method: 'GET' })
    );
    expect(screen.getByTestId('version-lint-badge')).toHaveTextContent('C · 72');
  });

  it('opens the report dialog with itemized findings on click', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(REPORT) });

    render(<VersionLintBadge projectId="p1" versionId="v1" versionLabel="1.0.0" />);
    await waitFor(() => expect(screen.getByTestId('version-lint-badge')).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('version-lint-badge'));

    await waitFor(() =>
      expect(screen.getByText(/Quality & Lint report/)).toBeInTheDocument()
    );
    expect(screen.getByText('naming.schema-pascal-case')).toBeInTheDocument();
    expect(screen.getByText("Schema 'payment' is not PascalCase.")).toBeInTheDocument();
  });

  it('shows a stale-score note in the dialog when the persisted score is out of date', async () => {
    const staleReport = {
      ...REPORT,
      capturedScore: 55,
      capturedGrade: 'D',
      capturedReportFingerprint: 'old',
      scoreIsStale: true,
    };
    global.fetch = jest
      .fn()
      .mockResolvedValue({ ok: true, json: () => Promise.resolve(staleReport) });

    render(<VersionLintBadge projectId="p1" versionId="v1" versionLabel="1.0.0" />);
    await waitFor(() => expect(screen.getByTestId('version-lint-badge')).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('version-lint-badge'));

    await waitFor(() =>
      expect(screen.getByTestId('version-lint-stale-note')).toBeInTheDocument()
    );
    expect(screen.getByTestId('version-lint-stale-note')).toHaveTextContent('D · 55');
    expect(screen.getByTestId('version-lint-stale-note')).toHaveTextContent('out of date');
  });

  it('omits the stale-score note when the persisted score is current', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(REPORT) });

    render(<VersionLintBadge projectId="p1" versionId="v1" versionLabel="1.0.0" />);
    await waitFor(() => expect(screen.getByTestId('version-lint-badge')).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('version-lint-badge'));
    await waitFor(() => expect(screen.getByText(/Quality & Lint report/)).toBeInTheDocument());
    expect(screen.queryByTestId('version-lint-stale-note')).not.toBeInTheDocument();
  });

  it('shows a retry affordance when the fetch fails', async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValue({ ok: false, status: 500, json: () => Promise.resolve({ success: false, error: 'boom' }) });

    render(<VersionLintBadge projectId="p1" versionId="v1" />);

    await waitFor(() => expect(screen.getByTestId('version-lint-badge-error')).toBeInTheDocument());
  });
});
