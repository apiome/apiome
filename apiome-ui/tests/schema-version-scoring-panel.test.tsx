/**
 * SchemaVersionScoringPanel tests (GOV-2.4, #4436).
 */

import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { SchemaVersionScoringPanel } from '../src/app/components/ade/dashboard/SchemaVersionScoringPanel';

const REPORT = {
  projectId: 'p1',
  versionRecordId: 'rev-1',
  versionId: '1.0.0',
  score: 80,
  grade: 'B',
  guideName: 'Apiome Recommended',
  guideId: null,
  findings: [
    {
      id: 'f1',
      path: 'info',
      category: 'documentation',
      rule: 'documentation.info-missing-description',
      severity: 'info',
      message: 'Missing info description',
    },
  ],
  ruleHits: {},
  severityCounts: { info: 1 },
  reportFingerprint: 'fp',
  baseRevisionId: null,
  compatibilityOverall: null,
};

const CATALOG = {
  rules: [
    {
      ruleId: 'documentation.info-missing-description',
      pack: 'openapi',
      category: 'documentation',
      defaultSeverity: 'info',
      rationale: 'The info object should describe the API.',
      docsAnchor: 'documentation-info-missing-description',
    },
  ],
  count: 1,
  docsPage: 'docs/guide/lint-rules.md',
};

function mockPanelFetch() {
  global.fetch = jest.fn((input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString();
    if (url.includes('/api/lint/rules')) {
      return Promise.resolve({
        ok: true,
        json: async () => ({ success: true, ...CATALOG }),
      });
    }
    if (url.includes('/api/projects/p1/versions/1.0.0/lint')) {
      return Promise.resolve({
        ok: true,
        json: async () => ({ success: true, ...REPORT }),
      });
    }
    return Promise.resolve({
      ok: false,
      status: 404,
      json: async () => ({ success: false, error: 'not found' }),
    });
  }) as unknown as typeof fetch;
}

describe('SchemaVersionScoringPanel', () => {
  afterEach(() => jest.restoreAllMocks());

  it('loads the lint report and shows governance metadata on findings', async () => {
    mockPanelFetch();

    render(
      <SchemaVersionScoringPanel projectId="p1" versionId="1.0.0" versionLabel="1.0.0" active />,
    );

    await waitFor(() => {
      expect(screen.getByTestId('studio-lint-grade')).toHaveTextContent('B');
    });

    expect(screen.getByTestId('studio-lint-guide-name')).toHaveTextContent('Apiome Recommended');

    await waitFor(() => {
      expect(screen.getByTestId('lint-violation-rule-chip')).toHaveTextContent(
        'documentation.info-missing-description',
      );
    });
    expect(screen.getByTestId('lint-violation-view-rule')).toBeInTheDocument();
  });
});
