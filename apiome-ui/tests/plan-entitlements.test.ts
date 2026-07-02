/**
 * @jest-environment node
 */

import { describe, it, expect, jest, beforeEach } from '@jest/globals';

jest.mock('../lib/db/db', () => ({
  query: jest.fn(),
}));

import { entitlementLimitsFromLicenseSeats } from '../lib/db/entitlement-limits-from-license-seats';
import { getPlanBlockMessageForNewProject, getPlanBlockMessageForNewVersion } from '../lib/db/plan-entitlements';

const pool = require('../lib/db/db');

describe('plan-entitlements', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    pool.query.mockReset();
  });

  describe('entitlementLimitsFromLicenseSeats', () => {
    it('maps seats to entitlement columns', () => {
      expect(
        entitlementLimitsFromLicenseSeats({
          max_tenants: 2,
          max_projects: 999,
          max_versions: 999,
        })
      ).toEqual({ max_tenants: 2, max_projects: 999, max_versions: 999 });
    });

    it('uses free-tier defaults for missing keys', () => {
      expect(entitlementLimitsFromLicenseSeats({})).toEqual({
        max_tenants: 1,
        max_projects: 1,
        max_versions: 3,
      });
    });

    it('parses JSON string seats from pg', () => {
      expect(entitlementLimitsFromLicenseSeats('{"max_projects":42}')).toEqual({
        max_tenants: 1,
        max_projects: 42,
        max_versions: 3,
      });
    });

    it('treats negative values as unlimited sentinel', () => {
      expect(entitlementLimitsFromLicenseSeats({ max_projects: -1 })).toEqual({
        max_tenants: 1,
        max_projects: -1,
        max_versions: 3,
      });
    });
  });

  it('allows projects when no entitlement row exists (legacy users)', async () => {
    pool.query.mockImplementationOnce(async () => ({ rowCount: 0, rows: [] }));
    const msg = await getPlanBlockMessageForNewProject('user-1');
    expect(msg).toBeNull();
  });

  it('allows new projects when max_projects is unlimited', async () => {
    pool.query
      .mockImplementationOnce(async () => ({
        rowCount: 1,
        rows: [{ plan_code: 'paid', max_tenants: 1, max_projects: -1, max_versions: 3 }],
      }))
      .mockImplementationOnce(async () => ({ rows: [{ c: 100 }] }));
    const msg = await getPlanBlockMessageForNewProject('user-1');
    expect(msg).toBeNull();
  });

  it('uses joined license.seats when license_id is set (ignores stale user_entitlements max_*)', async () => {
    pool.query
      .mockImplementationOnce(async () => ({
        rowCount: 1,
        rows: [
          {
            plan_code: 'paid',
            max_tenants: 1,
            max_projects: 1,
            max_versions: 3,
            license_id: '550e8400-e29b-41d4-a716-446655440000',
            license_seats: { max_projects: 999, max_versions: 999, max_tenants: 5 },
          },
        ],
      }))
      .mockImplementationOnce(async () => ({ rows: [{ c: 1 }] }));
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
