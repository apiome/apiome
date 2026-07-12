/**
 * Publish dialog style-guide panel (GOV-2.5, #4437).
 *
 * Regression: an unstable `onReportChange` callback must not retrigger the lint fetch in a loop
 * (which left "Checking style-guide violations…" spinning forever despite HTTP 200).
 */

import React, { useState } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { PublishGuideViolationsPanel } from '../src/app/components/ade/dashboard/PublishGuideViolationsPanel';
import type { VersionLintReport } from '../src/app/utils/version-lint-report';

const PROJECT_ID = 'e8d8179b-66f4-4ad4-b462-f7d1c782f8cf';
const VERSION_ID = '71ff5cc0-df6c-48e7-aeb8-32d98df416d1';

const LINT_REPORT: VersionLintReport = {
  projectId: PROJECT_ID,
  versionRecordId: VERSION_ID,
  versionId: '1.0.0',
  score: 95,
  grade: 'A',
  findings: [],
  ruleHits: {},
  severityCounts: { error: 0, warning: 0, info: 0 },
  reportFingerprint: 'fp',
  baseRevisionId: null,
  compatibilityOverall: null,
  guideName: 'Default guide',
};

function mockLintFetch() {
  global.fetch = jest.fn(() =>
    Promise.resolve({
      ok: true,
      status: 200,
      json: async () => ({ success: true, ...LINT_REPORT }),
    })
  ) as unknown as typeof fetch;
}

/** Parent that recreates `onReportChange` every render (matches publish dialog usage). */
function UnstableCallbackParent() {
  const [, setReport] = useState<VersionLintReport | null>(null);
  return (
    <PublishGuideViolationsPanel
      projectId={PROJECT_ID}
      versionId={VERSION_ID}
      onReportChange={(report) => setReport(report)}
    />
  );
}

describe('PublishGuideViolationsPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockLintFetch();
  });

  it('finishes loading when onReportChange is unstable across parent re-renders', async () => {
    render(<UnstableCallbackParent />);

    await waitFor(() => {
      expect(screen.getByTestId('publish-guide-violations-panel')).toBeInTheDocument();
    });

    expect(screen.queryByText('Checking style-guide violations…')).not.toBeInTheDocument();
    expect(screen.getByText('No style-guide violations.')).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });
});
