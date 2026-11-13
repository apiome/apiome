/**
 * Pure model for change-report review, PDF export and the audit trail (#2705).
 *
 * A publication change report moves `draft → pending_review → approved`; only an approved
 * report can be exported as PDF, and an edit or a regeneration returns it to draft. The REST
 * layer enforces all of that (`change_report_approval.py`). What lives here is how the panel
 * *shows* it: the badge, which buttons are offered to whom and why a button is unavailable,
 * and the words of the audit list. Side-effect free, so it is tested without React.
 */

import type { StatusTone } from '@/app/components/ui/statusVocabulary';

/** The three review states, as the API names them. */
export type ApprovalState = 'draft' | 'pending_review' | 'approved';

/** The review and export fields of a change report, as `GET …/change-report` returns them. */
export interface ChangeReportApproval {
  approvalState?: string | null;
  submittedBy?: string | null;
  submittedAt?: string | null;
  approvedBy?: string | null;
  approvedAt?: string | null;
  reviewNote?: string | null;
  lastPdfSha256?: string | null;
  lastPdfExportedAt?: string | null;
}

/**
 * Read a report's review state, treating a missing or unknown value as `draft` — what an older
 * API build (no approval fields) means.
 *
 * @param raw The `approvalState` field.
 * @returns One of the three states.
 */
export function approvalStateOf(raw: string | null | undefined): ApprovalState {
  return raw === 'pending_review' || raw === 'approved' ? raw : 'draft';
}

/** The badge beside the report's title. */
export interface ApprovalBadge {
  label: 'Draft' | 'Pending review' | 'Approved';
  tone: StatusTone;
}

/**
 * The badge for a review state.
 *
 * @param state The report's review state.
 * @returns Its label and tone.
 */
export function approvalBadge(state: ApprovalState): ApprovalBadge {
  if (state === 'approved') return { label: 'Approved', tone: 'ok' };
  if (state === 'pending_review') return { label: 'Pending review', tone: 'warn' };
  return { label: 'Draft', tone: 'neutral' };
}

/** One button of the review bar. */
export interface ApprovalAction {
  /** Whether the button is drawn at all. */
  show: boolean;
  /** Whether it is drawn but cannot be pressed. */
  disabled: boolean;
  /** The tooltip: what it does, or — when disabled — why it cannot be used. */
  title: string;
}

/** Every button of the review bar. */
export interface ApprovalActions {
  submit: ApprovalAction;
  approve: ApprovalAction;
  reject: ApprovalAction;
  download: ApprovalAction;
}

/** Who is looking at the report. */
export interface ApprovalViewer {
  /** The signed-in user's id, when known. */
  currentUserId?: string;
  /** Whether they may edit the report (the version's creator, or a tenant administrator). */
  canEdit: boolean;
  /** Whether they administer the tenant. */
  isAdmin: boolean;
}

/** Why Download PDF is unavailable before approval, worded once. */
export const PDF_NEEDS_APPROVAL = 'Only an approved change report can be exported as PDF';

/** Why the submitter cannot approve, worded once. */
export const APPROVER_MUST_DIFFER = 'A change report must be approved by someone other than its submitter';

/**
 * Which review buttons to offer, and whether each can be pressed.
 *
 * Mirrors the server's rules so the bar never offers a button the API would refuse — except
 * where showing a disabled button with its reason is the clearer answer (Download PDF before
 * approval, Approve to the person who submitted).
 *
 * @param approval The report's review fields.
 * @param viewer Who is looking.
 * @returns The four buttons.
 */
export function approvalActions(
  approval: ChangeReportApproval,
  viewer: ApprovalViewer
): ApprovalActions {
  const state = approvalStateOf(approval.approvalState);
  const isSubmitter =
    Boolean(viewer.currentUserId) && approval.submittedBy === viewer.currentUserId;
  const pending = state === 'pending_review';

  return {
    submit: {
      show: state === 'draft' && viewer.canEdit,
      disabled: false,
      title: 'Send this report to a tenant administrator for review',
    },
    approve: {
      show: pending && viewer.isAdmin,
      disabled: isSubmitter,
      title: isSubmitter ? APPROVER_MUST_DIFFER : 'Approve this report so it can be exported as PDF',
    },
    reject: {
      show: pending && viewer.isAdmin,
      disabled: false,
      title: 'Send this report back to draft, with a note',
    },
    download: {
      show: true,
      disabled: state !== 'approved',
      title: state === 'approved' ? 'Download this report as a PDF' : PDF_NEEDS_APPROVAL,
    },
  };
}

/**
 * A timestamp as `YYYY-MM-DD HH:MM UTC`, or `null` when there is none or it cannot be read.
 *
 * @param iso An ISO 8601 timestamp.
 * @returns The formatted time.
 */
export function formatAuditTime(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return `${date.toISOString().slice(0, 16).replace('T', ' ')} UTC`;
}

/**
 * The line under the badge: where the report is in its review, in words.
 *
 * @param approval The report's review fields.
 * @returns One sentence.
 */
export function approvalSummary(approval: ChangeReportApproval): string {
  const state = approvalStateOf(approval.approvalState);
  if (state === 'approved') {
    const when = formatAuditTime(approval.approvedAt);
    return when ? `Approved ${when}. It can be exported as PDF.` : 'Approved. It can be exported as PDF.';
  }
  if (state === 'pending_review') {
    const when = formatAuditTime(approval.submittedAt);
    return when
      ? `Submitted ${when}. Waiting for a tenant administrator to approve it.`
      : 'Waiting for a tenant administrator to approve it.';
  }
  return 'Not reviewed yet. Submit it for review before exporting it as PDF.';
}

/**
 * The first twelve characters of a SHA-256, for display beside the full value in a tooltip.
 *
 * @param sha256 The full hex digest.
 * @returns The short form, or `null` when there is no digest.
 */
export function shortHash(sha256: string | null | undefined): string | null {
  return sha256 ? sha256.slice(0, 12) : null;
}

// ---------------------------------------------------------------------------------------
// The audit trail
// ---------------------------------------------------------------------------------------

/** One entry of `GET /api/change-report-audit`. */
export interface ChangeReportAuditEntry {
  id: string;
  action: string;
  actorId?: string | null;
  projectId?: string | null;
  publishedRevisionId?: string | null;
  templateVersionId?: string | null;
  detail?: Record<string, unknown> | null;
  createdAt: string;
}

/** Every audit verb, with the words the list shows for it — in the filter's order. */
export const AUDIT_ACTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: 'report.edit', label: 'Report edited' },
  { value: 'report.regenerate', label: 'Report regenerated' },
  { value: 'report.submit', label: 'Submitted for review' },
  { value: 'report.approve', label: 'Approved' },
  { value: 'report.reject', label: 'Rejected' },
  { value: 'report.export_pdf', label: 'PDF exported' },
  { value: 'template.create', label: 'Template created' },
  { value: 'template.default_tenant', label: 'Tenant default template changed' },
  { value: 'template.default_project', label: 'Project default template changed' },
];

/**
 * The words for an audit verb; an unknown verb (a newer API build) is shown as it is.
 *
 * @param action The audit verb.
 * @returns Its label.
 */
export function auditActionLabel(action: string): string {
  return AUDIT_ACTIONS.find((entry) => entry.value === action)?.label ?? action;
}

/**
 * The one-line detail of an audit entry: the note, the hash, what was reset.
 *
 * @param entry The audit entry.
 * @returns The detail, or `''` when the verb says it all.
 */
export function auditDetailSummary(entry: ChangeReportAuditEntry): string {
  const detail = entry.detail ?? {};
  const text = (key: string): string | null =>
    typeof detail[key] === 'string' && (detail[key] as string).trim() ? (detail[key] as string) : null;

  switch (entry.action) {
    case 'report.approve':
    case 'report.reject':
      return text('note') ? `Note: ${text('note')}` : '';
    case 'report.export_pdf':
      return text('sha256') ? `SHA-256 ${shortHash(text('sha256'))}…` : '';
    case 'report.edit':
    case 'report.regenerate':
      return detail.approval_reset === true
        ? `Returned to draft (was ${String(detail.approval_state_before).replace('_', ' ')})`
        : '';
    case 'template.create':
      return text('semver') ? `Version ${text('semver')}` : '';
    case 'template.default_tenant':
    case 'template.default_project':
      return detail.cleared === true ? 'Default cleared' : '';
    default:
      return '';
  }
}

/** The audit dialog's filters. */
export interface AuditFilters {
  /** One audit verb, or `''` for all of them. */
  action: string;
  /** Narrow to one published version's report, when set. */
  versionId?: string;
  /** Narrow to one project, when set. */
  projectId?: string;
}

/**
 * Build the query string of `GET /api/change-report-audit`.
 *
 * @param filters The dialog's filters.
 * @param cursor The previous page's `nextCursor`, for the next (older) page.
 * @param limit Page size.
 * @returns The query string, without the leading `?`.
 */
export function buildAuditQuery(filters: AuditFilters, cursor?: string | null, limit = 25): string {
  const query = new URLSearchParams();
  if (filters.action) query.set('action', filters.action);
  if (filters.projectId) query.set('projectId', filters.projectId);
  if (filters.versionId) query.set('versionId', filters.versionId);
  query.set('limit', String(limit));
  if (cursor) query.set('cursor', cursor);
  return query.toString();
}
