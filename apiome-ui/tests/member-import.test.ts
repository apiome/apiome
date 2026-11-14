/**
 * The CSV member import's decisions (EID-2.5, #5671) — `memberImport.ts`.
 *
 * The dialog that uses these is rendered in `members-hive-redesign.test.tsx`; this pins the
 * rules: each `invite` row is sent on its own through the invite call, a refusal never stops
 * the rows after it, and the summary never counts a refused row as sent.
 */

import { jest } from '@jest/globals';

import {
  applyMemberImport,
  invitableRows,
  memberImportOutcome,
  summariseMemberImport,
  summariseMemberImportResults,
  validateMemberImportFile,
  MEMBER_IMPORT_MAX_BYTES,
  MEMBER_IMPORT_OUTCOMES,
  type MemberImportReport,
  type MemberImportRow,
} from '../src/app/components/ade/members/memberImport';

/** A report row with the defaults an `invite` row has. */
function row(line: number, overrides: Partial<MemberImportRow> = {}): MemberImportRow {
  return {
    line,
    email: `p${line}@acme.io`,
    role: 'Editor',
    display_name: '',
    outcome: 'invite',
    message: null,
    role_id: 'role-editor',
    role_name: 'Editor',
    ...overrides,
  };
}

/** A report over `rows`, with counts worked out from them. */
function report(rows: MemberImportRow[]): MemberImportReport {
  const counts = Object.fromEntries(MEMBER_IMPORT_OUTCOMES.map((entry) => [entry.outcome, 0])) as MemberImportReport['counts'];
  rows.forEach((r) => {
    counts[r.outcome] += 1;
  });
  return { dry_run: true, total: rows.length, max_rows: 1000, seats_free: null, counts, rows };
}

describe('choosing a file', () => {
  it('asks for one when none is chosen', () => {
    expect(validateMemberImportFile(undefined)).toBe('Choose a CSV file.');
  });

  it('refuses an empty file and one over 1 MiB before uploading', () => {
    expect(validateMemberImportFile(new File([], 'empty.csv'))).toBe('That file is empty.');
    const big = new File(['x'.repeat(MEMBER_IMPORT_MAX_BYTES + 1)], 'big.csv');
    expect(validateMemberImportFile(big)).toBe('That file is larger than the 1 MiB limit.');
  });

  it('accepts an ordinary CSV', () => {
    expect(validateMemberImportFile(new File(['email\nada@acme.io\n'], 'm.csv'))).toBeNull();
  });
});

describe('the report', () => {
  it('sends only the invite rows', () => {
    const r = report([row(2), row(3, { outcome: 'invalid-email' }), row(4)]);
    expect(invitableRows(r).map((x) => x.line)).toEqual([2, 4]);
  });

  it('summarises how many will be invited and skipped', () => {
    const rows = Array.from({ length: 60 }, (_, i) =>
      row(i + 2, i === 10 ? { outcome: 'invalid-email' } : i === 20 ? { outcome: 'unknown-role' } : {})
    );
    expect(summariseMemberImport(report(rows))).toBe('60 rows: 58 to invite, 2 will be skipped.');
    expect(summariseMemberImport(report([row(2)]))).toBe('1 row: all 1 to invite.');
  });

  it('labels every outcome the server sends', () => {
    expect(memberImportOutcome('seat-cap')).toMatchObject({ label: 'No seat left', tone: 'warn' });
    expect(memberImportOutcome('no-account').label).toBe('No account');
    expect(MEMBER_IMPORT_OUTCOMES.map((entry) => entry.outcome)).toEqual([
      'invite',
      'already-member',
      'invalid-email',
      'unknown-role',
      'no-account',
      'seat-cap',
    ]);
  });
});

describe('applying the report', () => {
  it('invites each row in order with its role, one call at a time', async () => {
    let inFlight = 0;
    let maxInFlight = 0;
    const invite = jest.fn(async (input: { email: string; roleId?: string }) => {
      void input;
      inFlight += 1;
      maxInFlight = Math.max(maxInFlight, inFlight);
      await Promise.resolve();
      inFlight -= 1;
    });
    const progress = jest.fn();
    const results = await applyMemberImport(
      [row(2), row(3, { role_id: null, role_name: null })],
      invite,
      () => 'x',
      progress
    );
    expect(invite.mock.calls.map((call) => call[0])).toEqual([
      { email: 'p2@acme.io', roleId: 'role-editor' },
      { email: 'p3@acme.io', roleId: undefined },
    ]);
    expect(maxInFlight).toBe(1);
    expect(progress.mock.calls).toEqual([[1], [2]]);
    expect(results.every((r) => r.error === null)).toBe(true);
  });

  it('keeps going past a refusal and names each refused row', async () => {
    const invite = jest.fn(async (input: { email: string }) => {
      if (input.email === 'p3@acme.io') throw new Error('Too many requests');
    });
    const results = await applyMemberImport([row(2), row(3), row(4)], invite, (e) =>
      e instanceof Error ? e.message : 'failed'
    );
    expect(invite).toHaveBeenCalledTimes(3);
    const summary = summariseMemberImportResults(results);
    expect(summary.sent).toBe(2);
    expect(summary.failed).toEqual([{ line: 3, email: 'p3@acme.io', error: 'Too many requests' }]);
  });
});
