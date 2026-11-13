'use client';

/**
 * The change-report audit log (#2705): who edited, regenerated, submitted, approved, rejected
 * or exported a report, and who changed its templates. Tenant administrators only — the
 * button that opens this dialog is drawn for them alone, and the API refuses everyone else.
 *
 * Newest first, one page at a time (**Load older** follows the server's cursor), narrowed by
 * **Action** and — by default — to the report on screen. The words for each entry come from
 * `changeReportApprovalModel.ts`.
 */

import * as React from 'react';

import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import { EmptyState } from '@/app/components/ui/EmptyState';

import {
  AUDIT_ACTIONS,
  auditActionLabel,
  auditDetailSummary,
  buildAuditQuery,
  formatAuditTime,
  type ChangeReportAuditEntry,
} from './changeReportApprovalModel';

/** Which events the dialog lists. */
type Scope = 'report' | 'tenant';

export interface ChangeReportAuditDialogProps {
  /** The published version whose report is on screen; the default scope. */
  revisionId: string;
  /** That version's label, for the scope switch (`v1.2.0`). */
  revisionLabel: string;
  /** Close the dialog. */
  onClose: () => void;
}

/**
 * Render the dialog. See {@link ChangeReportAuditDialogProps}.
 *
 * @returns The filters, the list and the pager.
 */
export default function ChangeReportAuditDialog({
  revisionId,
  revisionLabel,
  onClose,
}: ChangeReportAuditDialogProps) {
  const [scope, setScope] = React.useState<Scope>('report');
  const [action, setAction] = React.useState('');
  const [entries, setEntries] = React.useState<ChangeReportAuditEntry[]>([]);
  const [nextCursor, setNextCursor] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [failure, setFailure] = React.useState<string | null>(null);

  const load = React.useCallback(
    async (cursor: string | null) => {
      setLoading(true);
      setFailure(null);
      try {
        const query = buildAuditQuery(
          { action, versionId: scope === 'report' ? revisionId : undefined },
          cursor
        );
        const response = await fetch(`/api/change-report-audit?${query}`);
        const data = await response.json();
        if (!response.ok || !data.success || !data.audit) {
          setFailure(data.error || 'The audit log could not be loaded.');
          return;
        }
        const page = (data.audit.items ?? []) as ChangeReportAuditEntry[];
        setEntries((current) => (cursor ? [...current, ...page] : page));
        setNextCursor(data.audit.nextCursor ?? null);
      } catch (error) {
        setFailure(error instanceof Error ? error.message : 'The audit log could not be loaded.');
      } finally {
        setLoading(false);
      }
    },
    [action, scope, revisionId]
  );

  // A changed filter starts over from the newest entry.
  React.useEffect(() => {
    void load(null);
  }, [load]);

  return (
    <Dialog open onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent className="prm-dialog prm-dialog--tall" data-testid="change-report-audit-dialog">
        <DialogHeader>
          <DialogTitle>Change report audit log</DialogTitle>
          <DialogDescription>
            Every edit, regeneration, review decision and PDF export, and every template change.
            Newest first.
          </DialogDescription>
        </DialogHeader>

        <div className="crv-audit__filters">
          <label className="crv-audit__filter">
            <span className="vdlg-field__label">Show</span>
            <select
              value={scope}
              onChange={(event) => setScope(event.target.value as Scope)}
              className="hive-control prm-select"
              aria-label="Show"
              data-testid="change-report-audit-scope"
            >
              <option value="report">This report ({revisionLabel})</option>
              <option value="tenant">All reports and templates</option>
            </select>
          </label>
          <label className="crv-audit__filter">
            <span className="vdlg-field__label">Action</span>
            <select
              value={action}
              onChange={(event) => setAction(event.target.value)}
              className="hive-control prm-select"
              aria-label="Action"
              data-testid="change-report-audit-action"
            >
              <option value="">All actions</option>
              {AUDIT_ACTIONS.map((entry) => (
                <option key={entry.value} value={entry.value}>
                  {entry.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        {failure ? (
          <Alert variant="error" data-testid="change-report-audit-error">
            <span>{failure}</span>
          </Alert>
        ) : null}

        {!failure && !loading && entries.length === 0 ? (
          <EmptyState
            title="No Audit Entries"
            description="Nothing matches these filters yet."
            variant="compact"
          />
        ) : null}

        {entries.length > 0 ? (
          <ol className="crv-audit__list" data-testid="change-report-audit-list">
            {entries.map((entry) => {
              const detail = auditDetailSummary(entry);
              return (
                <li key={entry.id} className="crv-audit__entry" data-action={entry.action}>
                  <span className="crv-audit__when mono">
                    {formatAuditTime(entry.createdAt) ?? '—'}
                  </span>
                  <span className="crv-audit__what">
                    <span className="crv-audit__action">{auditActionLabel(entry.action)}</span>
                    {detail ? <span className="crv-audit__detail">{detail}</span> : null}
                  </span>
                  <span className="crv-audit__who mono" title={entry.actorId ?? undefined}>
                    {entry.actorId ? `${entry.actorId.slice(0, 8)}…` : 'system'}
                  </span>
                </li>
              );
            })}
          </ol>
        ) : null}

        <DialogFooter>
          {nextCursor ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => void load(nextCursor)}
              disabled={loading}
              title={loading ? 'Loading…' : 'Load the next, older page'}
              data-testid="change-report-audit-more"
            >
              {loading ? 'Loading…' : 'Load older'}
            </Button>
          ) : null}
          <Button type="button" onClick={onClose} data-testid="change-report-audit-close">
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
