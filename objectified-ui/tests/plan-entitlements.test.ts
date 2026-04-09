/**
 * @jest-environment node
 */

import { describe, it, expect, jest, beforeEach } from '@jest/globals';

jest.mock('../lib/db/db', () => ({
  query: jest.fn(),
}));

import { getPlanBlockMessageForNewProject, getPlanBlockMessageForNewVersion } from '../lib/db/plan-entitlements';

const pool = require('../lib/db/db');

describe('plan-entitlements', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('allows projects when no entitlement row exists (legacy users)', async () => {
    pool.query.mockImplementationOnce(async () => ({ rowCount: 0, rows: [] }));
    const msg = await getPlanBlockMessageForNewProject('user-1');
    expect(msg).toBeNull();
  });

  it('blocks a new project when at max_projects', async () => {
    pool.query
      .mockImplementationOnce(async () => ({
        rowCount: 1,
        rows: [{ plan_code: 'free', max_tenants: 1, max_projects: 1, max_versions: 3 }],
      }))
      .mockImplementationOnce(async () => ({ rows: [{ c: 1 }] }));
    const msg = await getPlanBlockMessageForNewProject('user-1');
    expect(msg).toContain('free');
    expect(msg).toContain('1 project');
  });

  it('blocks a new version when at max_versions', async () => {
    pool.query
      .mockImplementationOnce(async () => ({
        rowCount: 1,
        rows: [{ plan_code: 'free', max_tenants: 1, max_projects: 1, max_versions: 3 }],
      }))
      .mockImplementationOnce(async () => ({ rows: [{ c: 3 }] }));
    const msg = await getPlanBlockMessageForNewVersion('user-1');
    expect(msg).toContain('3 version');
  });
});
