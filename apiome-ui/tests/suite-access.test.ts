/**
 * Suite Access (V320): the Designer and Developer suites show only to a user an administrator gave
 * Suite Access. Before, the free license's `designer` flag showed Designer to every free account,
 * and Developer had no gate at all.
 */

const mockQuery = jest.fn();
jest.mock('../lib/db/db', () => ({ query: (...args: unknown[]) => mockQuery(...args) }));

const mockGetAuthSession = jest.fn();
jest.mock('../lib/auth/server-session', () => ({
  getAuthSession: (...args: unknown[]) => mockGetAuthSession(...args),
}));

import { getCommercialAccessForSession } from '../lib/db/commercial-access';
import { updateUser, getAllUsersWithLicenses } from '../lib/db/admin-helper';
import { userHasSuiteAccess } from '../lib/db/feature-entitlements';
import {
  applySuiteAccessToFlags,
  filterSuiteAccessEntries,
  SUITE_ACCESS_PRODUCT_IDS,
} from '../lib/suite-access';

/** Answer the entitlement query for each flag, and the Suite Access query. */
function mockDatabase({ suiteAccess, licensed }: { suiteAccess: boolean; licensed: string[] }) {
  mockQuery.mockImplementation(async (sql: string, params: unknown[]) => {
    if (sql.includes('suite_access')) return { rows: [{ suite_access: suiteAccess }], rowCount: 1 };
    const flag = String(params[0]);
    return {
      rowCount: 1,
      rows: [{ flag_enabled: true, user_override: null, tenant_override: null, license_grant: licensed.includes(flag) }],
    };
  });
}

const ids = (entries: { id: string }[]) => entries.map((entry) => entry.id);

beforeEach(() => {
  mockQuery.mockReset();
  mockGetAuthSession.mockResolvedValue({ user: { user_id: 'u-1', current_tenant_id: 't-1' } });
});

describe('applySuiteAccessToFlags', () => {
  it('withholds the Designer flags without Suite Access, whatever the license grants', () => {
    expect(applySuiteAccessToFlags(['designer', 'paths', 'scribe'], false)).toEqual(['scribe']);
  });

  it('grants the Designer flags with Suite Access', () => {
    expect(applySuiteAccessToFlags(['scribe'], true)).toEqual(['scribe', 'designer', 'paths']);
    expect(applySuiteAccessToFlags(['designer'], true)).toEqual(['designer', 'paths']);
  });
});

describe('filterSuiteAccessEntries', () => {
  const entries = [{ id: 'suite' }, { id: 'developer-suite' }, { id: 'authoring' }] as never[];

  it('drops the Designer and Developer suites without Suite Access', () => {
    expect(ids(filterSuiteAccessEntries(entries, false))).toEqual(['authoring']);
  });

  it('keeps them with Suite Access', () => {
    expect(ids(filterSuiteAccessEntries(entries, true))).toEqual(['suite', 'developer-suite', 'authoring']);
  });
});

describe('getCommercialAccessForSession', () => {
  it('shows a free account neither suite, though its license grants designer', async () => {
    mockDatabase({ suiteAccess: false, licensed: ['designer'] });
    const access = await getCommercialAccessForSession();
    for (const id of SUITE_ACCESS_PRODUCT_IDS) {
      expect(ids(access.navItems)).not.toContain(id);
      expect(ids(access.homeCards)).not.toContain(id);
    }
    expect(access.entitledFlags).not.toContain('designer');
  });

  it('shows both suites to a user with Suite Access, even with no license', async () => {
    mockDatabase({ suiteAccess: true, licensed: [] });
    const access = await getCommercialAccessForSession();
    expect(ids(access.navItems)).toEqual(expect.arrayContaining(['suite', 'developer-suite']));
    expect(ids(access.homeCards)).toEqual(expect.arrayContaining(['suite', 'developer-suite']));
    expect(access.entitledFlags).toEqual(expect.arrayContaining(['designer', 'paths']));
  });

  it('shows nothing to a signed-out visitor', async () => {
    mockGetAuthSession.mockResolvedValue(null);
    expect(await getCommercialAccessForSession()).toEqual({ entitledFlags: [], homeCards: [], navItems: [] });
    expect(mockQuery).not.toHaveBeenCalled();
  });
});

describe('userHasSuiteAccess', () => {
  it('reads the switch for a live account only', async () => {
    mockQuery.mockResolvedValue({ rows: [{ suite_access: true }] });
    expect(await userHasSuiteAccess('u-1')).toBe(true);
    expect(String(mockQuery.mock.calls[0][0])).toMatch(/SELECT suite_access FROM apiome\.users WHERE id = \$1 AND deleted_at IS NULL/);
  });

  it('is off for a missing account', async () => {
    mockQuery.mockResolvedValue({ rows: [] });
    expect(await userHasSuiteAccess('u-x')).toBe(false);
  });
});

describe('admin console', () => {
  it('sets Suite Access per user', async () => {
    mockQuery.mockResolvedValue({ rowCount: 1, rows: [{ id: 'u-1', suite_access: true }] });
    const result = JSON.parse(await updateUser('u-1', { suite_access: true }));
    expect(result.success).toBe(true);
    const [sql, values] = mockQuery.mock.calls[0];
    expect(String(sql)).toMatch(/suite_access = \$1/);
    expect(values).toEqual([true, 'u-1']);
  });

  it('lists each user with their Suite Access', async () => {
    mockQuery.mockResolvedValue({ rows: [] });
    await getAllUsersWithLicenses();
    expect(String(mockQuery.mock.calls[0][0])).toMatch(/u\.suite_access/);
  });
});
