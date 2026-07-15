/**
 * Render/interaction tests for the workspace queue table and bulk action bar (CLX-4.1, #4859):
 * row rendering (severity/decision badges, New pill), checkbox multi-select, pagination
 * controls, and the bulk bar's action payloads including the waiver rationale dialog.
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import LintWorkspaceQueueTable from '../src/app/components/ade/dashboard/lint/workspace/LintWorkspaceQueueTable';
import LintWorkspaceBulkActionBar from '../src/app/components/ade/dashboard/lint/workspace/LintWorkspaceBulkActionBar';
import { selectionKey, type LintWorkspaceFinding } from '../src/app/utils/lint-workspace';

function finding(overrides: Partial<LintWorkspaceFinding> = {}): LintWorkspaceFinding {
  return {
    sourceFingerprint: 'f1',
    ruleId: 'security.rule-1',
    message: 'Something risky.',
    severity: 'error',
    confidence: 'high',
    category: 'security',
    axisKey: 'security',
    location: { path: '/pets' },
    remediation: null,
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
    evidenceRunId: 'run-1',
    evidenceCreatedAt: '2026-07-14T00:00:00Z',
    isNew: true,
    effectiveState: 'open',
    waived: false,
    decision: null,
    latestPolicyEvaluationId: 'pe-1',
    policyPassed: false,
    ...overrides,
  };
}

describe('LintWorkspaceQueueTable', () => {
  const rows = [
    finding(),
    finding({ sourceFingerprint: 'f2', ruleId: 'doc.rule-2', severity: 'warning', isNew: false, effectiveState: 'acknowledged' }),
  ];

  function renderTable(props: Partial<React.ComponentProps<typeof LintWorkspaceQueueTable>> = {}) {
    const onSelectionChange = jest.fn();
    const onOpenDetail = jest.fn();
    const onPageChange = jest.fn();
    render(
      <LintWorkspaceQueueTable
        findings={rows}
        total={120}
        limit={50}
        offset={50}
        selected={new Set()}
        onSelectionChange={onSelectionChange}
        onOpenDetail={onOpenDetail}
        onPageChange={onPageChange}
        {...props}
      />,
    );
    return { onSelectionChange, onOpenDetail, onPageChange };
  }

  it('renders rows with severity, decision state, New pill, and subject context', () => {
    renderTable();
    expect(screen.getAllByTestId('workspace-finding-row')).toHaveLength(2);
    expect(screen.getByText('security.rule-1')).toBeInTheDocument();
    expect(screen.getByTestId('finding-new-pill')).toBeInTheDocument();
    expect(screen.getByText('Acknowledged')).toBeInTheDocument();
    expect(screen.getAllByText('Petstore')).toHaveLength(2);
    expect(screen.getByTestId('queue-pagination-summary')).toHaveTextContent('51–100 of 120');
  });

  it('selects rows individually and via the header checkbox', () => {
    const { onSelectionChange } = renderTable();
    fireEvent.click(screen.getAllByTestId('queue-select-row')[0]);
    expect(onSelectionChange).toHaveBeenCalledWith(new Set([selectionKey(rows[0])]));
    fireEvent.click(screen.getByTestId('queue-select-all'));
    expect(onSelectionChange).toHaveBeenLastCalledWith(new Set(rows.map(selectionKey)));
  });

  it('opens the detail on row click and pages with offset math', () => {
    const { onOpenDetail, onPageChange } = renderTable();
    fireEvent.click(screen.getByText('security.rule-1'));
    expect(onOpenDetail).toHaveBeenCalledWith(rows[0]);
    fireEvent.click(screen.getByTestId('queue-prev-page'));
    expect(onPageChange).toHaveBeenCalledWith(0);
    fireEvent.click(screen.getByTestId('queue-next-page'));
    expect(onPageChange).toHaveBeenCalledWith(100);
  });
});

describe('LintWorkspaceBulkActionBar', () => {
  it('renders nothing without a selection', () => {
    render(
      <LintWorkspaceBulkActionBar selectedCount={0} onApply={jest.fn()} onClearSelection={jest.fn()} />,
    );
    expect(screen.queryByTestId('lint-workspace-bulk-bar')).not.toBeInTheDocument();
  });

  it('fires simple actions with the target state', () => {
    const onApply = jest.fn();
    render(
      <LintWorkspaceBulkActionBar selectedCount={3} onApply={onApply} onClearSelection={jest.fn()} />,
    );
    fireEvent.click(screen.getByTestId('bulk-acknowledge'));
    expect(onApply).toHaveBeenCalledWith({ state: 'acknowledged' });
    fireEvent.click(screen.getByTestId('bulk-false-positive'));
    expect(onApply).toHaveBeenCalledWith({ state: 'false_positive' });
    fireEvent.click(screen.getByTestId('bulk-reject-waiver'));
    expect(onApply).toHaveBeenCalledWith({ state: 'open' });
  });

  it('assigns an owner without changing state', () => {
    const onApply = jest.fn();
    render(
      <LintWorkspaceBulkActionBar selectedCount={2} onApply={onApply} onClearSelection={jest.fn()} />,
    );
    fireEvent.change(screen.getByTestId('bulk-owner-input'), { target: { value: 'user-9' } });
    fireEvent.click(screen.getByTestId('bulk-assign-owner'));
    expect(onApply).toHaveBeenCalledWith({ ownerUserId: 'user-9' });
  });

  it('requires a rationale to submit a waiver request', () => {
    const onApply = jest.fn();
    render(
      <LintWorkspaceBulkActionBar selectedCount={1} onApply={onApply} onClearSelection={jest.fn()} />,
    );
    fireEvent.click(screen.getByTestId('bulk-request-waiver'));
    expect(screen.getByTestId('waiver-dialog')).toBeInTheDocument();
    expect(screen.getByTestId('waiver-submit')).toBeDisabled();
    fireEvent.change(screen.getByTestId('waiver-rationale'), {
      target: { value: 'Vendor accepts the risk until Q4.' },
    });
    fireEvent.click(screen.getByTestId('waiver-submit'));
    expect(onApply).toHaveBeenCalledWith({
      state: 'waiver_requested',
      rationale: 'Vendor accepts the risk until Q4.',
    });
  });

  it('requires rationale AND expiry to approve a waiver', () => {
    const onApply = jest.fn();
    render(
      <LintWorkspaceBulkActionBar selectedCount={1} onApply={onApply} onClearSelection={jest.fn()} />,
    );
    fireEvent.click(screen.getByTestId('bulk-approve-waiver'));
    fireEvent.change(screen.getByTestId('waiver-rationale'), { target: { value: 'Approved.' } });
    expect(screen.getByTestId('waiver-submit')).toBeDisabled();
    fireEvent.change(screen.getByTestId('waiver-expires'), { target: { value: '2026-09-01' } });
    fireEvent.click(screen.getByTestId('waiver-submit'));
    expect(onApply).toHaveBeenCalledWith({
      state: 'waived',
      rationale: 'Approved.',
      expiresAt: new Date('2026-09-01').toISOString(),
    });
  });
});
