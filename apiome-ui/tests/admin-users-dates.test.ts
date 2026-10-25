/**
 * The admin console's Users list reads each account's dates: the list showed "Invalid Date" because
 * `getAllUsersWithLicenses` never selected `created_at`, and it had no last sign-in or activity.
 */

const mockQuery = jest.fn();
jest.mock('../lib/db/db', () => ({ query: (...args: unknown[]) => mockQuery(...args) }));

import { getAllUsersWithLicenses } from '../lib/db/admin-helper';

const pool = { query: mockQuery };

describe('getAllUsersWithLicenses', () => {
  beforeEach(() => pool.query.mockReset());

  it('selects the created date, the last sign-in and the last activity', async () => {
    pool.query.mockResolvedValue({ rows: [] });
    await getAllUsersWithLicenses();
    const sql = String(pool.query.mock.calls[0][0]);
    expect(sql).toMatch(/u\.created_at/);
    expect(sql).toMatch(/u\.last_login_at/);
    // Activity is the later of the last sign-in and the newest session refresh.
    expect(sql).toMatch(/GREATEST\(\s*u\.last_login_at,\s*\(SELECT MAX\(s\."updatedAt"\) FROM apiome\.session s WHERE s\."userId" = u\.id\)\s*\) AS last_active_at/);
  });

  it('passes the dates through to the screen', async () => {
    const row = {
      id: 'u-1',
      created_at: '2026-10-25T10:00:00.000Z',
      last_login_at: '2026-10-25T11:00:00.000Z',
      last_active_at: '2026-10-25T12:00:00.000Z',
    };
    pool.query.mockResolvedValue({ rows: [row] });
    expect(JSON.parse(await getAllUsersWithLicenses())).toEqual(
      expect.objectContaining({ success: true, users: [row] })
    );
  });
});
