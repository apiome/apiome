/**
 * Bulk CSV member import — the decisions behind the dialog (EID-2.5, #5671).
 *
 * The import has two halves, and only the first is the server's:
 *
 * 1. **Dry run.** `POST /api/access/members/import?dryRun=true` reads the uploaded file and
 *    answers with one {@link MemberImportRow} per data row, each labelled with what applying it
 *    would do. Nothing is written.
 * 2. **Apply.** Each `invite` row is sent, one at a time, to the same `POST /api/access/members`
 *    the Invite member dialog uses ({@link applyMemberImport}). There is no second create path:
 *    the seat guard (`license-seats-exhausted`), the rate limit and the audit entry apply to each
 *    row as they do to one typed by hand, and a row that fails is listed with its own reason.
 *
 * Everything here is pure, apart from the `invite` callback {@link applyMemberImport} is given,
 * and unit-tested in `tests/member-import.test.ts`.
 */

/** What applying one row would do, as the dry run reports it. */
export type MemberImportOutcome =
  | 'invite'
  | 'already-member'
  | 'invalid-email'
  | 'unknown-role'
  | 'no-account'
  | 'seat-cap';

/** One row of the dry-run report. */
export interface MemberImportRow {
  /** Line number in the uploaded file (the header is line 1). */
  line: number;
  /** The email cell, as written. */
  email: string;
  /** The role cell, as written; empty for the default role. */
  role: string;
  /** The display_name cell, as written. Shown only — the account already has a name. */
  display_name: string;
  outcome: MemberImportOutcome;
  /** Why the row will not be invited; `null` on an `invite` row. */
  message: string | null;
  /** On an `invite` row, the role to send (`null` for the default role). */
  role_id: string | null;
  /** On an `invite` row, that role's name. */
  role_name: string | null;
}

/** The dry run's answer. */
export interface MemberImportReport {
  dry_run: true;
  /** Data rows read from the file. */
  total: number;
  /** Most rows a file may hold. */
  max_rows: number;
  /** Seats free before the import, or `null` when seats are not enforced. */
  seats_free: number | null;
  /** Rows per outcome; every outcome is present. */
  counts: Record<MemberImportOutcome, number>;
  rows: MemberImportRow[];
}

/** What happened to one `invite` row when it was sent. */
export interface MemberImportResult {
  line: number;
  email: string;
  /** `null` when the invitation was sent; otherwise the reason it was refused. */
  error: string | null;
}

/** Most data rows one file may hold — the server's limit, repeated for the dialog's hint. */
export const MEMBER_IMPORT_MAX_ROWS = 1000;

/** Largest file the server accepts. Checked before upload so a large file fails at once. */
export const MEMBER_IMPORT_MAX_BYTES = 1024 * 1024;

/** The header an import file starts with. */
export const MEMBER_IMPORT_HEADER = 'email,role,display_name';

/** Where the roster export downloads from. */
export const MEMBERS_EXPORT_URL = '/api/access/members/export';

/** Outcomes in the order the report lists them, with the label and badge tone each one has. */
export const MEMBER_IMPORT_OUTCOMES: ReadonlyArray<{
  outcome: MemberImportOutcome;
  label: string;
  tone: 'ok' | 'neutral' | 'warn' | 'danger';
}> = [
  { outcome: 'invite', label: 'Invite', tone: 'ok' },
  { outcome: 'already-member', label: 'Already a member', tone: 'neutral' },
  { outcome: 'invalid-email', label: 'Invalid email', tone: 'danger' },
  { outcome: 'unknown-role', label: 'Unknown role', tone: 'danger' },
  { outcome: 'no-account', label: 'No account', tone: 'warn' },
  { outcome: 'seat-cap', label: 'No seat left', tone: 'warn' },
];

/**
 * The label and tone of one outcome.
 *
 * @param outcome The row's outcome.
 * @returns Its entry in {@link MEMBER_IMPORT_OUTCOMES}.
 */
export function memberImportOutcome(outcome: MemberImportOutcome) {
  return (
    MEMBER_IMPORT_OUTCOMES.find((entry) => entry.outcome === outcome) ?? {
      outcome,
      label: outcome,
      tone: 'neutral' as const,
    }
  );
}

/**
 * Check a chosen file before it is uploaded.
 *
 * @param file The file the reader picked, or `undefined` when they cleared the input.
 * @returns The sentence to show, or `null` when the file can be sent.
 */
export function validateMemberImportFile(file: File | undefined): string | null {
  if (!file) return 'Choose a CSV file.';
  if (file.size === 0) return 'That file is empty.';
  if (file.size > MEMBER_IMPORT_MAX_BYTES) return 'That file is larger than the 1 MiB limit.';
  return null;
}

/**
 * The rows applying the report would send.
 *
 * @param report The dry run's answer.
 * @returns Its `invite` rows, in file order.
 */
export function invitableRows(report: MemberImportReport): MemberImportRow[] {
  return report.rows.filter((row) => row.outcome === 'invite');
}

/**
 * The one-line summary over the report table.
 *
 * @param report The dry run's answer.
 * @returns E.g. "60 rows: 58 to invite, 2 will be skipped."
 */
export function summariseMemberImport(report: MemberImportReport): string {
  const invites = report.counts.invite ?? 0;
  const skipped = report.total - invites;
  const rows = `${report.total} ${report.total === 1 ? 'row' : 'rows'}`;
  if (skipped === 0) return `${rows}: all ${invites} to invite.`;
  return `${rows}: ${invites} to invite, ${skipped} will be skipped.`;
}

/**
 * Send each row's invitation through the existing invite route, one at a time.
 *
 * Sequential on purpose: the invite route is rate limited and seat-gated per request, and a
 * burst of parallel calls would turn both into a race the reader cannot follow. Every row is
 * tried even after one fails — a refusal of row 12 says nothing about row 13 — and every
 * failure is kept with its own message.
 *
 * @param rows The `invite` rows to send ({@link invitableRows}).
 * @param invite Sends one invitation; throws on refusal. The page's `inviteMember`.
 * @param describe Turns a caught refusal into the sentence to show.
 * @param onProgress Called after each row with how many have been sent.
 * @returns One result per row, in order.
 */
export async function applyMemberImport(
  rows: readonly MemberImportRow[],
  invite: (input: { email: string; roleId?: string }) => Promise<void>,
  describe: (error: unknown) => string,
  onProgress?: (done: number) => void
): Promise<MemberImportResult[]> {
  const results: MemberImportResult[] = [];
  for (const row of rows) {
    try {
      await invite({ email: row.email, roleId: row.role_id ?? undefined });
      results.push({ line: row.line, email: row.email, error: null });
    } catch (error) {
      results.push({ line: row.line, email: row.email, error: describe(error) });
    }
    onProgress?.(results.length);
  }
  return results;
}

/**
 * Count what happened when the invitations were sent.
 *
 * @param results From {@link applyMemberImport}.
 * @returns How many were sent, and the rows that failed.
 */
export function summariseMemberImportResults(results: readonly MemberImportResult[]): {
  sent: number;
  failed: MemberImportResult[];
} {
  const failed = results.filter((result) => result.error !== null);
  return { sent: results.length - failed.length, failed };
}
