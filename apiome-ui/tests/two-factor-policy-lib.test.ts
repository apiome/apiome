/**
 * Tenant two-factor policy helpers (TFA-1.3, #5657): `lib/two-factor-policy.ts`, and the deadline
 * SQL the enforcement read shares with apiome-rest.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import {
  daysUntil,
  isValidGraceDays,
  MAX_TWO_FACTOR_GRACE_DAYS,
  NO_TWO_FACTOR_REQUIREMENT,
  requiringWorkspacesPhrase,
  summarizeTwoFactorRequirement,
  toMemberTwoFactorStatus,
} from '@lib/two-factor-policy';

jest.mock('../lib/db/db', () => ({ query: jest.fn() }));
// eslint-disable-next-line @typescript-eslint/no-require-imports
const pool = require('../lib/db/db') as { query: jest.Mock };
import { getTwoFactorRequirementRows, TWO_FACTOR_DUE_AT_SQL } from '../lib/db/two-factor-requirement';

const NOW = new Date('2026-10-23T12:00:00Z');

describe('grace days', () => {
  it('accepts whole days from 0 to 90', () => {
    expect(isValidGraceDays(0)).toBe(true);
    expect(isValidGraceDays(7)).toBe(true);
    expect(isValidGraceDays(MAX_TWO_FACTOR_GRACE_DAYS)).toBe(true);
  });

  it.each([-1, 91, 1.5, NaN, '7', null])('refuses %p', (value) => {
    expect(isValidGraceDays(value)).toBe(false);
  });
});

describe('daysUntil', () => {
  it('rounds up, so a few hours left reads as one day', () => {
    expect(daysUntil('2026-10-23T18:00:00Z', NOW)).toBe(1);
    expect(daysUntil('2026-10-30T12:00:00Z', NOW)).toBe(7);
  });

  it('is 0 once the deadline has passed, and null for nonsense', () => {
    expect(daysUntil('2026-10-20T12:00:00Z', NOW)).toBe(0);
    expect(daysUntil('not a date', NOW)).toBeNull();
  });
});

describe('member status', () => {
  it('narrows untrusted values', () => {
    expect(toMemberTwoFactorStatus('grace')).toBe('grace');
    expect(toMemberTwoFactorStatus('overdue')).toBe('overdue');
    expect(toMemberTwoFactorStatus('enabled')).toBe('enabled');
    expect(toMemberTwoFactorStatus(undefined)).toBe('not_required');
    expect(toMemberTwoFactorStatus('banana')).toBe('not_required');
  });
});

describe('summarizeTwoFactorRequirement', () => {
  it('owes nothing without rows', () => {
    expect(summarizeTwoFactorRequirement([], NOW)).toBe(NO_TWO_FACTOR_REQUIREMENT);
  });

  it('takes the earliest deadline, since enrolling once satisfies every workspace', () => {
    const summary = summarizeTwoFactorRequirement(
      [
        { tenantName: 'Globex', dueAt: '2026-10-30T12:00:00Z' },
        { tenantName: 'Acme', dueAt: '2026-10-25T12:00:00Z' },
      ],
      NOW
    );
    expect(summary.dueAt).toBe('2026-10-25T12:00:00Z');
    expect(summary.tenants.map((tenant) => tenant.tenantName)).toEqual(['Acme', 'Globex']);
    expect(summary.overdue).toBe(false);
  });

  it('is overdue once the earliest deadline has passed', () => {
    const summary = summarizeTwoFactorRequirement(
      [
        { tenantName: 'Globex', dueAt: '2026-10-30T12:00:00Z' },
        { tenantName: 'Acme', dueAt: '2026-10-22T12:00:00Z' },
      ],
      NOW
    );
    expect(summary.overdue).toBe(true);
  });

  it('drops unreadable deadlines rather than blocking on them', () => {
    expect(summarizeTwoFactorRequirement([{ tenantName: 'Acme', dueAt: 'garbage' }], NOW)).toBe(
      NO_TWO_FACTOR_REQUIREMENT
    );
  });
});

describe('requiringWorkspacesPhrase', () => {
  const row = (tenantName: string) => ({ tenantName, dueAt: '2026-10-25T12:00:00Z' });

  it('names one, two, or two and a count', () => {
    expect(requiringWorkspacesPhrase([])).toBe('Your workspace');
    expect(requiringWorkspacesPhrase([row('Acme')])).toBe('Acme');
    expect(requiringWorkspacesPhrase([row('Acme'), row('Globex')])).toBe('Acme and Globex');
    expect(requiringWorkspacesPhrase([row('Acme'), row('Globex'), row('Initech'), row('Umbrella')])).toBe(
      'Acme, Globex and 2 more'
    );
  });
});

describe('the enforcement read', () => {
  beforeEach(() => pool.query.mockReset());

  it('asks only about active memberships of live workspaces that require it, for a user without two-factor', async () => {
    pool.query.mockResolvedValue({
      rows: [{ tenant_name: 'Acme', due_at: new Date('2026-10-25T12:00:00Z') }],
    });

    expect(await getTwoFactorRequirementRows('u-1')).toEqual([
      { tenantName: 'Acme', dueAt: '2026-10-25T12:00:00.000Z' },
    ]);
    const [sql, params] = pool.query.mock.calls[0];
    expect(params).toEqual(['u-1']);
    for (const clause of [
      "tu.status = 'active'",
      'tn.deleted_at IS NULL',
      'tn.enabled',
      'tn.require_two_factor',
      'NOT COALESCE(u."twoFactorEnabled", false)',
    ]) {
      expect(sql).toContain(clause);
    }
  });

  it('computes the deadline exactly as apiome-rest does', () => {
    // The rule lives in two languages; this keeps them from drifting apart.
    const python = readFileSync(join(__dirname, '..', '..', 'apiome-rest', 'src', 'app', 'two_factor_policy.py'), 'utf8');
    const block = python.slice(python.indexOf('DUE_AT_SQL = ('), python.indexOf('STATUS_SQL = ('));
    const restExpression = Array.from(block.matchAll(/"([^"]*)"/g), (match) => match[1])
      .join('')
      .replace(/\s+/g, ' ');
    expect(restExpression).toContain(TWO_FACTOR_DUE_AT_SQL);
  });
});
