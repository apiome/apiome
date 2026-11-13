/**
 * The pure model behind change-report review, PDF export and the audit log (#2705): the badge,
 * which buttons are offered to whom, and the audit list's words.
 */

import {
  APPROVER_MUST_DIFFER,
  AUDIT_ACTIONS,
  PDF_NEEDS_APPROVAL,
  approvalActions,
  approvalBadge,
  approvalStateOf,
  approvalSummary,
  auditActionLabel,
  auditDetailSummary,
  buildAuditQuery,
  formatAuditTime,
  shortHash,
  type ChangeReportAuditEntry,
} from '../src/app/components/ade/versions/changeReport/changeReportApprovalModel';

const CREATOR = { currentUserId: 'user-a', canEdit: true, isAdmin: false };
const ADMIN = { currentUserId: 'admin-b', canEdit: true, isAdmin: true };
const MEMBER = { currentUserId: 'member-c', canEdit: false, isAdmin: false };

describe('approvalStateOf', () => {
  it('keeps the two non-draft states and reads everything else as draft', () => {
    expect(approvalStateOf('pending_review')).toBe('pending_review');
    expect(approvalStateOf('approved')).toBe('approved');
    expect(approvalStateOf('draft')).toBe('draft');
    expect(approvalStateOf(undefined)).toBe('draft');
    expect(approvalStateOf(null)).toBe('draft');
    expect(approvalStateOf('published')).toBe('draft');
  });
});

describe('approvalBadge', () => {
  it('names each state and gives it a tone', () => {
    expect(approvalBadge('draft')).toEqual({ label: 'Draft', tone: 'neutral' });
    expect(approvalBadge('pending_review')).toEqual({ label: 'Pending review', tone: 'warn' });
    expect(approvalBadge('approved')).toEqual({ label: 'Approved', tone: 'ok' });
  });
});

describe('approvalActions', () => {
  it('offers Submit on a draft to someone who can edit it, and nothing else to review', () => {
    const actions = approvalActions({ approvalState: 'draft' }, CREATOR);

    expect(actions.submit).toMatchObject({ show: true, disabled: false });
    expect(actions.approve.show).toBe(false);
    expect(actions.reject.show).toBe(false);
  });

  it('offers no Submit to someone who cannot edit the report', () => {
    expect(approvalActions({ approvalState: 'draft' }, MEMBER).submit.show).toBe(false);
  });

  it('offers Approve and Reject on a pending report to an administrator', () => {
    const actions = approvalActions(
      { approvalState: 'pending_review', submittedBy: 'user-a' },
      ADMIN
    );

    expect(actions.submit.show).toBe(false);
    expect(actions.approve).toMatchObject({ show: true, disabled: false });
    expect(actions.reject).toMatchObject({ show: true, disabled: false });
  });

  it('shows Approve disabled, with the reason, to the administrator who submitted it', () => {
    const actions = approvalActions(
      { approvalState: 'pending_review', submittedBy: 'admin-b' },
      ADMIN
    );

    expect(actions.approve).toEqual({ show: true, disabled: true, title: APPROVER_MUST_DIFFER });
    // They may still withdraw their own submission.
    expect(actions.reject.disabled).toBe(false);
  });

  it('offers no review buttons on a pending report to its non-admin creator', () => {
    const actions = approvalActions(
      { approvalState: 'pending_review', submittedBy: 'user-a' },
      CREATOR
    );

    expect(actions.submit.show).toBe(false);
    expect(actions.approve.show).toBe(false);
    expect(actions.reject.show).toBe(false);
  });

  it('always shows Download PDF, enabled only once the report is approved', () => {
    for (const state of ['draft', 'pending_review']) {
      expect(approvalActions({ approvalState: state }, MEMBER).download).toEqual({
        show: true,
        disabled: true,
        title: PDF_NEEDS_APPROVAL,
      });
    }
    expect(approvalActions({ approvalState: 'approved' }, MEMBER).download).toMatchObject({
      show: true,
      disabled: false,
    });
  });

  it('offers nothing to review on an approved report', () => {
    const actions = approvalActions({ approvalState: 'approved' }, ADMIN);

    expect(actions.submit.show || actions.approve.show || actions.reject.show).toBe(false);
  });
});

describe('approvalSummary', () => {
  it('tells a draft what to do next', () => {
    expect(approvalSummary({})).toBe(
      'Not reviewed yet. Submit it for review before exporting it as PDF.'
    );
  });

  it('says when a pending report was submitted', () => {
    expect(
      approvalSummary({ approvalState: 'pending_review', submittedAt: '2026-11-13T12:05:00Z' })
    ).toBe('Submitted 2026-11-13 12:05 UTC. Waiting for a tenant administrator to approve it.');
    expect(approvalSummary({ approvalState: 'pending_review' })).toBe(
      'Waiting for a tenant administrator to approve it.'
    );
  });

  it('says when an approved report was approved', () => {
    expect(
      approvalSummary({ approvalState: 'approved', approvedAt: '2026-11-13T13:00:00Z' })
    ).toBe('Approved 2026-11-13 13:00 UTC. It can be exported as PDF.');
  });
});

describe('formatAuditTime and shortHash', () => {
  it('formats in UTC and refuses what it cannot read', () => {
    expect(formatAuditTime('2026-11-13T23:59:30+02:00')).toBe('2026-11-13 21:59 UTC');
    expect(formatAuditTime('not a date')).toBeNull();
    expect(formatAuditTime(null)).toBeNull();
  });

  it('shortens a digest to twelve characters', () => {
    expect(shortHash('ab'.repeat(32))).toBe('abababababab');
    expect(shortHash(null)).toBeNull();
  });
});

describe('the audit list', () => {
  const entry = (action: string, detail: Record<string, unknown> = {}): ChangeReportAuditEntry => ({
    id: 'e1',
    action,
    detail,
    createdAt: '2026-11-13T12:00:00Z',
  });

  it('has a label for every verb the API writes', () => {
    expect(AUDIT_ACTIONS.map((a) => a.value)).toEqual([
      'report.edit',
      'report.regenerate',
      'report.submit',
      'report.approve',
      'report.reject',
      'report.export_pdf',
      'template.create',
      'template.default_tenant',
      'template.default_project',
    ]);
    expect(auditActionLabel('report.export_pdf')).toBe('PDF exported');
  });

  it('shows an unknown verb as it is', () => {
    expect(auditActionLabel('report.archive')).toBe('report.archive');
  });

  it('summarizes each kind of entry', () => {
    expect(auditDetailSummary(entry('report.reject', { note: 'Name the field.' }))).toBe(
      'Note: Name the field.'
    );
    expect(auditDetailSummary(entry('report.approve', { note: null }))).toBe('');
    expect(auditDetailSummary(entry('report.export_pdf', { sha256: 'cd'.repeat(32) }))).toBe(
      'SHA-256 cdcdcdcdcdcd…'
    );
    expect(
      auditDetailSummary(
        entry('report.edit', { approval_reset: true, approval_state_before: 'pending_review' })
      )
    ).toBe('Returned to draft (was pending review)');
    expect(auditDetailSummary(entry('report.regenerate', { approval_reset: false }))).toBe('');
    expect(auditDetailSummary(entry('template.create', { semver: '1.2.0' }))).toBe('Version 1.2.0');
    expect(auditDetailSummary(entry('template.default_tenant', { cleared: true }))).toBe(
      'Default cleared'
    );
    expect(auditDetailSummary(entry('report.submit'))).toBe('');
    expect(auditDetailSummary({ ...entry('report.approve'), detail: null })).toBe('');
  });

  it('builds the query from the filters that are set', () => {
    expect(buildAuditQuery({ action: '' })).toBe('limit=25');
    expect(
      buildAuditQuery({ action: 'report.approve', versionId: 'v1', projectId: 'p1' }, 'CUR', 10)
    ).toBe('action=report.approve&projectId=p1&versionId=v1&limit=10&cursor=CUR');
  });
});
