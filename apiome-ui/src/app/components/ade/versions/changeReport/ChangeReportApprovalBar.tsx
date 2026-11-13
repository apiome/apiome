'use client';

/**
 * The review bar of a publication change report (#2705).
 *
 * One strip above the report: its review state as a badge and a sentence, the reviewer's note
 * when there is one, and the buttons the viewer may use — **Submit for review**, **Approve**,
 * **Reject** (which asks for a note) and **Download PDF**, enabled only once the report is
 * approved. After an export it shows the file's SHA-256, the value stored with the report.
 *
 * Every rule about which button appears and why one is disabled is in
 * `changeReportApprovalModel.ts`; the server enforces the same rules, so a refusal that still
 * happens (another reviewer got there first, the tenant lacks the entitlement) is shown in
 * place as the server worded it.
 */

import * as React from 'react';
import { CheckCircle2, FileDown, Loader2, Send, Undo2 } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import { FormField } from '@/app/components/ui/FormField';
import { Textarea } from '@/app/components/ui/Textarea';
import {
  downloadBlob,
  filenameFromDisposition,
} from '@/app/components/ade/dashboard/export/exportDownload';

import {
  approvalActions,
  approvalBadge,
  approvalStateOf,
  approvalSummary,
  formatAuditTime,
  shortHash,
  type ChangeReportApproval,
} from './changeReportApprovalModel';

/** Longest reviewer note the API accepts (`ChangeReportReviewRequest.note`). */
export const MAX_REVIEW_NOTE = 1000;

export interface ChangeReportApprovalBarProps {
  /** The project the report belongs to. */
  projectId: string;
  /** The published version (`versions.id`) the report belongs to. */
  revisionId: string;
  /** The report's review and export fields. */
  approval: ChangeReportApproval;
  /** The signed-in user's id. */
  currentUserId: string | undefined;
  /** Whether the viewer may edit the report (version creator or tenant administrator). */
  canEdit: boolean;
  /** Whether the viewer administers the tenant. */
  isAdmin: boolean;
  /** A transition landed: the caller shows the report the server answered with. */
  onReportChange: (report: ChangeReportApproval) => void;
  /** A PDF was exported: the caller reloads the report to pick up its stored hash. */
  onExported: () => void;
}

type Busy = 'submit' | 'approve' | 'reject' | 'download' | null;

/**
 * Render the bar. See {@link ChangeReportApprovalBarProps}.
 *
 * @returns The state, the note, the buttons and — on request — the Reject dialog.
 */
export default function ChangeReportApprovalBar({
  projectId,
  revisionId,
  approval,
  currentUserId,
  canEdit,
  isAdmin,
  onReportChange,
  onExported,
}: ChangeReportApprovalBarProps) {
  const [busy, setBusy] = React.useState<Busy>(null);
  const [failure, setFailure] = React.useState<string | null>(null);
  const [rejecting, setRejecting] = React.useState(false);
  const [note, setNote] = React.useState('');

  const state = approvalStateOf(approval.approvalState);
  const badge = approvalBadge(state);
  const actions = approvalActions(approval, { currentUserId, canEdit, isAdmin });
  const base = `/api/versions/${encodeURIComponent(revisionId)}/change-report`;
  const query = new URLSearchParams({ projectId }).toString();
  const noteTooLong = note.trim().length > MAX_REVIEW_NOTE;

  /** Make one transition and hand the server's answer to the caller. */
  const transition = async (kind: 'submit' | 'approve' | 'reject', body?: { note?: string }) => {
    setBusy(kind);
    setFailure(null);
    try {
      const response = await fetch(`${base}/${kind}?${query}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body ? JSON.stringify(body) : undefined,
      });
      const data = await response.json();
      if (!response.ok || !data.success || !data.report) {
        setFailure(data.error || 'The review could not be updated.');
        return false;
      }
      onReportChange(data.report as ChangeReportApproval);
      return true;
    } catch (error) {
      setFailure(error instanceof Error ? error.message : 'The review could not be updated.');
      return false;
    } finally {
      setBusy(null);
    }
  };

  const handleReject = async () => {
    if (noteTooLong) return;
    const trimmed = note.trim();
    const done = await transition('reject', trimmed ? { note: trimmed } : {});
    if (done) {
      setRejecting(false);
      setNote('');
    }
  };

  const handleDownload = async () => {
    setBusy('download');
    setFailure(null);
    try {
      const response = await fetch(`${base}/pdf?${query}`);
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        setFailure(data?.error || 'The PDF could not be exported.');
        return;
      }
      const filename =
        filenameFromDisposition(response.headers.get('content-disposition')) ?? 'change-report.pdf';
      downloadBlob(await response.blob(), filename);
      onExported();
    } catch (error) {
      setFailure(error instanceof Error ? error.message : 'The PDF could not be exported.');
    } finally {
      setBusy(null);
    }
  };

  const exportedAt = formatAuditTime(approval.lastPdfExportedAt);

  return (
    <section
      className="crv-bar"
      aria-label="Review and export"
      data-testid="change-report-approval-bar"
      data-state={state}
    >
      <div className="crv-bar__row">
        <div className="crv-bar__status">
          <Badge variant={badge.tone} data-testid="change-report-approval-badge">
            {badge.label}
          </Badge>
          <span className="crv-bar__summary" data-testid="change-report-approval-summary">
            {approvalSummary(approval)}
          </span>
        </div>

        <div className="crv-bar__actions">
          {actions.submit.show ? (
            <Button
              type="button"
              size="sm"
              onClick={() => void transition('submit')}
              disabled={busy !== null}
              title={busy !== null ? 'Working…' : actions.submit.title}
              data-testid="change-report-submit"
            >
              {busy === 'submit' ? <Loader2 className="animate-spin" aria-hidden /> : <Send aria-hidden />}
              Submit for review
            </Button>
          ) : null}
          {actions.approve.show ? (
            <Button
              type="button"
              size="sm"
              onClick={() => void transition('approve', {})}
              disabled={actions.approve.disabled || busy !== null}
              title={actions.approve.title}
              data-testid="change-report-approve"
            >
              {busy === 'approve' ? (
                <Loader2 className="animate-spin" aria-hidden />
              ) : (
                <CheckCircle2 aria-hidden />
              )}
              Approve
            </Button>
          ) : null}
          {actions.reject.show ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => setRejecting(true)}
              disabled={busy !== null}
              title={busy !== null ? 'Working…' : actions.reject.title}
              data-testid="change-report-reject"
            >
              <Undo2 aria-hidden />
              Reject
            </Button>
          ) : null}
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => void handleDownload()}
            disabled={actions.download.disabled || busy !== null}
            title={actions.download.title}
            data-testid="change-report-download-pdf"
          >
            {busy === 'download' ? (
              <Loader2 className="animate-spin" aria-hidden />
            ) : (
              <FileDown aria-hidden />
            )}
            Download PDF
          </Button>
        </div>
      </div>

      {approval.reviewNote ? (
        <p className="crv-bar__note" data-testid="change-report-review-note">
          <span className="crv-bar__note-label">Reviewer’s note</span> {approval.reviewNote}
        </p>
      ) : null}

      {approval.lastPdfSha256 ? (
        <p className="crv-bar__export" data-testid="change-report-last-export">
          Last PDF{exportedAt ? ` exported ${exportedAt}` : ''} · SHA-256{' '}
          <span className="mono" title={approval.lastPdfSha256}>
            {shortHash(approval.lastPdfSha256)}…
          </span>
        </p>
      ) : null}

      {failure ? (
        <Alert variant="error" data-testid="change-report-approval-error">
          <span>{failure}</span>
        </Alert>
      ) : null}

      {rejecting ? (
        <Dialog open onOpenChange={(open) => (open ? undefined : setRejecting(false))}>
          <DialogContent className="prm-dialog" data-testid="change-report-reject-dialog">
            <DialogHeader>
              <DialogTitle>Reject change report</DialogTitle>
              <DialogDescription>
                The report goes back to draft. The note is shown on the report and kept in the
                audit log.
              </DialogDescription>
            </DialogHeader>
            <FormField
              label="Note"
              error={noteTooLong ? `Keep the note to ${MAX_REVIEW_NOTE} characters or fewer.` : undefined}
              helperText="Optional. Say what needs to change."
            >
              <Textarea
                value={note}
                onChange={(event) => setNote(event.target.value)}
                rows={3}
                placeholder="Name the removed field in the summary."
                aria-label="Note"
                data-testid="change-report-reject-note"
              />
            </FormField>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setRejecting(false)}
                disabled={busy === 'reject'}
                title={busy === 'reject' ? 'Rejecting…' : undefined}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="danger"
                onClick={() => void handleReject()}
                disabled={noteTooLong || busy === 'reject'}
                title={noteTooLong ? 'Shorten the note first' : undefined}
                data-testid="change-report-reject-confirm"
              >
                {busy === 'reject' ? 'Rejecting…' : 'Reject report'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      ) : null}
    </section>
  );
}
