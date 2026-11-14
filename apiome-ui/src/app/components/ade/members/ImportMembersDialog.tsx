'use client';

import * as React from 'react';
import { FileUp, Send, Upload } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import {
  DataTable,
  DataTableFilterChip,
  DataTableToolbar,
  type DataTableColumn,
} from '@/app/components/ui/DataTable';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import { Input } from '@/app/components/ui/Input';
import { Label } from '@/app/components/ui/Label';
import { Spinner } from '@/app/components/ui/Spinner';

import {
  applyMemberImport,
  invitableRows,
  memberImportOutcome,
  summariseMemberImport,
  summariseMemberImportResults,
  validateMemberImportFile,
  MEMBER_IMPORT_HEADER,
  MEMBER_IMPORT_MAX_ROWS,
  MEMBER_IMPORT_OUTCOMES,
  type MemberImportOutcome,
  type MemberImportReport,
  type MemberImportResult,
  type MemberImportRow,
} from './memberImport';

/**
 * Import members from CSV — EID-2.5 (#5671).
 *
 * Three steps in one dialog:
 *
 * 1. **Choose a file.** An `email,role,display_name` CSV of up to 1,000 rows. **Check file**
 *    uploads it for a dry run, which changes nothing.
 * 2. **Read the report.** One table row per file row, each labelled with what applying it
 *    would do (invite, already a member, invalid email, unknown role, no account, no seat
 *    left), with chips to narrow it. **Send N invites** is the only write.
 * 3. **Read the result.** Each `invite` row went through the same invite call the Invite
 *    member dialog makes, so the seat guard and the rate limit apply per row. Rows that were
 *    refused are listed by line and email with their own reason; the dialog never calls a
 *    partial import a success.
 */

/** The form's id, so the footer's submit can be associated with it. */
const FORM_ID = 'members-import-form';

/** How tall the report table may grow before it scrolls — set on `.mbr-import-report`. */
const REPORT_MAX_HEIGHT = 'var(--mbr-import-report-block)';

/** Where the dialog is in the three steps. */
type ImportPhase = 'pick' | 'checking' | 'report' | 'sending' | 'done';

/** Which rows the report table shows. */
type ReportFilter = 'all' | MemberImportOutcome;

/** Props for {@link ImportMembersDialog}. */
export interface ImportMembersDialogProps {
  open: boolean;
  /** Called with `false` on cancel, dismiss or close. */
  onOpenChange: (open: boolean) => void;
  /**
   * Upload the file for the dry run.
   *
   * @param file The chosen CSV.
   * @returns The report. Throws with the server's sentence when the file cannot be read.
   */
  onPreview: (file: File) => Promise<MemberImportReport>;
  /**
   * Send one invitation through the existing invite route. Throws on refusal.
   *
   * @param input The row's email and the role to assign (absent for the default role).
   */
  onInvite: (input: { email: string; roleId?: string }) => Promise<void>;
  /**
   * Turn a caught refusal into the sentence to show — the page's licence-aware reader.
   *
   * @param error Whatever was caught.
   */
  describeError: (error: unknown) => string;
  /** Called once the invitations have been sent, so the page can reload the roster. */
  onApplied: () => void;
}

/** The report table's columns. */
const REPORT_COLUMNS: DataTableColumn<MemberImportRow>[] = [
  {
    id: 'line',
    header: 'Line',
    align: 'end',
    className: 'mbr-import-line',
    cell: (row) => row.line,
  },
  {
    id: 'email',
    header: 'Email',
    cell: (row) => <span className="mbr-import-email">{row.email || '—'}</span>,
  },
  {
    id: 'role',
    header: 'Role',
    cell: (row) => row.role_name ?? (row.role || 'Default role'),
  },
  {
    id: 'outcome',
    header: 'Result',
    cell: (row) => {
      const outcome = memberImportOutcome(row.outcome);
      return (
        <Badge variant={outcome.tone} data-outcome={row.outcome}>
          {outcome.label}
        </Badge>
      );
    },
  },
  {
    id: 'message',
    header: 'Note',
    cell: (row) => <span className="mbr-import-note">{row.message ?? ''}</span>,
  },
];

/**
 * The import dialog.
 *
 * @param props See {@link ImportMembersDialogProps}.
 * @returns The dialog.
 */
export default function ImportMembersDialog({
  open,
  onOpenChange,
  onPreview,
  onInvite,
  describeError,
  onApplied,
}: ImportMembersDialogProps) {
  const [phase, setPhase] = React.useState<ImportPhase>('pick');
  const [file, setFile] = React.useState<File | undefined>(undefined);
  const [error, setError] = React.useState('');
  const [report, setReport] = React.useState<MemberImportReport | null>(null);
  const [filter, setFilter] = React.useState<ReportFilter>('all');
  const [sent, setSent] = React.useState(0);
  const [results, setResults] = React.useState<MemberImportResult[]>([]);

  // Reset on open, not on close, so the reader never watches the dialog empty while it animates
  // away (the reason `InviteMemberDialog` gives).
  React.useEffect(() => {
    if (!open) return;
    setPhase('pick');
    setFile(undefined);
    setError('');
    setReport(null);
    setFilter('all');
    setSent(0);
    setResults([]);
  }, [open]);

  const busy = phase === 'checking' || phase === 'sending';
  /** Why the footer's buttons are unavailable while a request runs (§10: no silent disabled). */
  const busyReason = !busy
    ? undefined
    : phase === 'sending'
      ? 'Wait until every invitation has been sent.'
      : 'Wait until the file has been checked.';
  const invites = React.useMemo(() => (report ? invitableRows(report) : []), [report]);
  const visibleRows = React.useMemo(
    () =>
      !report ? [] : filter === 'all' ? report.rows : report.rows.filter((row) => row.outcome === filter),
    [filter, report]
  );
  const outcome = React.useMemo(() => summariseMemberImportResults(results), [results]);

  const check = React.useCallback(async () => {
    const problem = validateMemberImportFile(file);
    if (problem || !file) {
      setError(problem ?? 'Choose a CSV file.');
      return;
    }
    setError('');
    setPhase('checking');
    try {
      setReport(await onPreview(file));
      setFilter('all');
      setPhase('report');
    } catch (e) {
      setError(describeError(e));
      setPhase('pick');
    }
  }, [describeError, file, onPreview]);

  const send = React.useCallback(async () => {
    setPhase('sending');
    setSent(0);
    const done = await applyMemberImport(invites, onInvite, describeError, setSent);
    setResults(done);
    setPhase('done');
    onApplied();
  }, [describeError, invites, onApplied, onInvite]);

  const startOver = React.useCallback(() => {
    setPhase('pick');
    setFile(undefined);
    setReport(null);
    setError('');
  }, []);

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent size={phase === 'pick' || phase === 'checking' ? 'default' : 'xl'} data-testid="members-import-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <span className="tnt-icon-tile" data-tone="accent">
              <Upload aria-hidden />
            </span>
            Import members
          </DialogTitle>
          <DialogDescription>
            {phase === 'done'
              ? 'The invitations have been sent. Each row was invited on its own.'
              : 'Check a CSV file first: nothing is sent until you confirm the report.'}
          </DialogDescription>
        </DialogHeader>

        {error && <Alert variant="danger">{error}</Alert>}

        {(phase === 'pick' || phase === 'checking') && (
          <form
            id={FORM_ID}
            data-testid="members-import-form"
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (!busy) void check();
            }}
          >
            <div className="space-y-2">
              <Label htmlFor="membersImportFile">CSV file</Label>
              <Input
                id="membersImportFile"
                type="file"
                accept=".csv,text/csv"
                className="mbr-import-file"
                disabled={busy}
                data-testid="members-import-file"
                onChange={(event) => {
                  setError('');
                  setFile(event.target.files?.[0]);
                }}
              />
              <p className="text-xs text-fg-muted">
                The first line is the header <code className="mbr-import-code">{MEMBER_IMPORT_HEADER}</code>.
                Only <strong>email</strong> is required; <strong>role</strong> is a role name, and an
                empty role means the default role. Up to {MEMBER_IMPORT_MAX_ROWS.toLocaleString('en-US')} rows.
              </p>
              <p className="text-xs text-fg-muted">
                Each address must already have an Apiome account — invitations are not emailed.
              </p>
            </div>
          </form>
        )}

        {phase === 'report' && report && (
          <div className="mbr-import-report space-y-3" data-testid="members-import-report">
            <p className="text-sm text-fg" data-testid="members-import-summary">
              {summariseMemberImport(report)}
            </p>
            <DataTable
              columns={REPORT_COLUMNS}
              rows={visibleRows}
              getRowId={(row) => String(row.line)}
              getRowLabel={(row) => `Line ${row.line}`}
              caption="What each row of the file would do"
              dense
              maxBodyHeight={REPORT_MAX_HEIGHT}
              rowAttributes={(row) => ({ 'data-outcome': row.outcome })}
              empty="No rows match this filter."
              toolbar={
                <DataTableToolbar>
                  <DataTableFilterChip active={filter === 'all'} count={report.total} onClick={() => setFilter('all')}>
                    All
                  </DataTableFilterChip>
                  {MEMBER_IMPORT_OUTCOMES.filter((entry) => report.counts[entry.outcome] > 0).map((entry) => (
                    <DataTableFilterChip
                      key={entry.outcome}
                      active={filter === entry.outcome}
                      count={report.counts[entry.outcome]}
                      onClick={() => setFilter(entry.outcome)}
                    >
                      {entry.label}
                    </DataTableFilterChip>
                  ))}
                </DataTableToolbar>
              }
            />
            {invites.length === 0 && (
              <Alert variant="warn" data-testid="members-import-nothing">
                No row in this file can be invited. Fix the file and check it again.
              </Alert>
            )}
          </div>
        )}

        {phase === 'sending' && (
          <p className="flex items-center gap-2 text-sm text-fg" role="status" data-testid="members-import-progress">
            <Spinner size="sm" aria-hidden />
            Sending invitation {Math.min(sent + 1, invites.length)} of {invites.length}…
          </p>
        )}

        {phase === 'done' && (
          <div className="space-y-3" data-testid="members-import-result">
            {outcome.failed.length === 0 ? (
              <Alert variant="ok">
                {outcome.sent} {outcome.sent === 1 ? 'invitation' : 'invitations'} sent.
              </Alert>
            ) : (
              <>
                <Alert variant="danger" data-testid="members-import-failed">
                  {outcome.sent} of {results.length} invitations sent. {outcome.failed.length}{' '}
                  {outcome.failed.length === 1 ? 'row was' : 'rows were'} refused:
                </Alert>
                <ul className="mbr-import-failures" aria-label="Rows that were refused">
                  {outcome.failed.map((row) => (
                    <li key={row.line} data-testid="members-import-failure">
                      <span className="mbr-import-failures__where">
                        Line {row.line} · {row.email}
                      </span>
                      <span>{row.error}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}

        <DialogFooter>
          {phase === 'done' ? (
            <Button type="button" onClick={() => onOpenChange(false)}>
              Close
            </Button>
          ) : (
            <>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={busy} title={busyReason}>
                Cancel
              </Button>
              {phase === 'report' && (
                <Button type="button" variant="outline" onClick={startOver}>
                  <FileUp aria-hidden />
                  Choose another file
                </Button>
              )}
              {(phase === 'pick' || phase === 'checking') && (
                <Button
                  type="submit"
                  form={FORM_ID}
                  disabled={busy}
                  title={busyReason}
                  data-testid="members-import-check"
                >
                  {busy ? <Spinner size="sm" aria-hidden /> : <FileUp aria-hidden />}
                  {busy ? 'Checking…' : 'Check file'}
                </Button>
              )}
              {(phase === 'report' || phase === 'sending') && invites.length > 0 && (
                <Button
                  type="button"
                  onClick={() => void send()}
                  disabled={busy}
                  title={busyReason}
                  data-testid="members-import-send"
                >
                  {busy ? <Spinner size="sm" aria-hidden /> : <Send aria-hidden />}
                  {busy
                    ? 'Sending…'
                    : `Send ${invites.length} ${invites.length === 1 ? 'invite' : 'invites'}`}
                </Button>
              )}
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
