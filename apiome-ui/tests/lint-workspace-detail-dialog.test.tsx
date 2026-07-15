/**
 * Render tests for the workspace finding detail dialog (CLX-4.1, #4859): the acceptance
 * criterion 2 linkage — evidence run, revision link, policy decision, source location —
 * plus the lazily fetched remediation history and its error state.
 */

import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import LintWorkspaceFindingDetailDialog from '../src/app/components/ade/dashboard/lint/workspace/LintWorkspaceFindingDetailDialog';
import type { LintWorkspaceFinding } from '../src/app/utils/lint-workspace';

const FINDING: LintWorkspaceFinding = {
  sourceFingerprint: 'lint-abc123',
  ruleId: 'security.api-key-in-url',
  message: 'API key transmitted in the URL.',
  severity: 'error',
  confidence: 'high',
  category: 'security',
  axisKey: 'security',
  location: { path: '/pets', line: 12 },
  remediation: { fix: 'Move the key to an Authorization header.' },
  scannerId: 'apiome.native-lint',
  profile: 'import-capture',
  subjectType: 'catalog_revision',
  versionRecordId: 'v1',
  mcpVersionId: null,
  projectId: 'p1',
  projectName: 'Petstore',
  subjectLabel: '1.0.0',
  compositeGrade: 'B',
  requiredCoverageMet: true,
  evidenceRunId: 'run-42',
  evidenceCreatedAt: '2026-07-14T00:00:00Z',
  isNew: true,
  effectiveState: 'waiver_requested',
  waived: false,
  decision: {
    id: 'd1',
    projectId: 'p1',
    state: 'waiver_requested',
    ownerUserId: 'u9',
    rationale: 'Vendor limitation.',
    linkedTicket: 'https://tracker.example/TICKET-7',
    expiresAt: null,
  },
  latestPolicyEvaluationId: 'pe-9',
  policyPassed: false,
};

function mockEventsFetch(payload: unknown, ok = true) {
  global.fetch = jest.fn(() =>
    Promise.resolve({
      ok,
      status: ok ? 200 : 500,
      json: async () => payload,
    }),
  ) as jest.Mock;
}

describe('LintWorkspaceFindingDetailDialog', () => {
  it('renders evidence, links, policy state, and remediation history', async () => {
    mockEventsFetch({
      success: true,
      events: [
        {
          id: 'ev1',
          beforeState: null,
          afterState: 'waiver_requested',
          rationale: 'Vendor limitation.',
          actorLabel: 'kenji',
          createdAt: '2026-07-10T00:00:00Z',
        },
      ],
    });
    render(<LintWorkspaceFindingDetailDialog finding={FINDING} onClose={jest.fn()} />);

    // Evidence section (criterion 2: evidence run + source location).
    expect(screen.getByTestId('detail-evidence-run')).toHaveTextContent('run-42');
    expect(screen.getByTestId('detail-location')).toHaveTextContent('path: /pets');
    expect(screen.getByText('Move the key to an Authorization header.')).toBeInTheDocument();

    // Links section: revision + policy + linked ticket.
    expect(screen.getByTestId('detail-subject-link')).toHaveAttribute(
      'href',
      '/ade/dashboard/versions?projectId=p1',
    );
    expect(screen.getByTestId('detail-policy')).toHaveTextContent('Failed (evaluation pe-9)');
    expect(screen.getByTestId('detail-linked-ticket')).toHaveAttribute(
      'href',
      'https://tracker.example/TICKET-7',
    );

    // Remediation history is fetched from the decision's audit events.
    await waitFor(() => {
      expect(screen.getByTestId('detail-history-event')).toHaveTextContent(
        'created → waiver_requested',
      );
    });
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/lint/decisions/d1/events',
      expect.objectContaining({ signal: expect.anything() }),
    );
  });

  it('shows an empty-history note when the finding has no decision', () => {
    global.fetch = jest.fn() as jest.Mock;
    render(
      <LintWorkspaceFindingDetailDialog
        finding={{ ...FINDING, decision: null, effectiveState: 'open' }}
        onClose={jest.fn()}
      />,
    );
    expect(screen.getByText('No decisions recorded for this finding yet.')).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('surfaces a history fetch failure without breaking the dialog', async () => {
    mockEventsFetch({ success: false, error: 'nope' }, false);
    render(<LintWorkspaceFindingDetailDialog finding={FINDING} onClose={jest.fn()} />);
    await waitFor(() => {
      expect(screen.getByText('nope')).toBeInTheDocument();
    });
    expect(screen.getByTestId('detail-evidence-run')).toHaveTextContent('run-42');
  });
});
