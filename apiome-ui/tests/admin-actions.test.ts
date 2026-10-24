/**
 * lib/db/admin-actions — the admin console's server actions.
 *
 * Every one must refuse without the super-admin session (a signed-in workspace user is not enough)
 * and reach admin-helper unchanged with it.
 */

import { describe, test, expect, jest, beforeEach } from '@jest/globals';

let mockVerdict: string | null = null;

jest.mock('../lib/auth/action-guard', () => ({
  requireSuperAdmin: jest.fn(async () => mockVerdict),
}));

jest.mock('../lib/db/admin-helper', () => {
  const names = [
    'getAllUsers',
    'createUser',
    'updateUser',
    'deleteUser',
    'getUserStats',
    'getTenantStats',
    'getTenantUsers',
    'createTenant',
    'updateTenant',
    'deleteTenant',
    'addUserToTenant',
    'removeUserFromTenant',
    'addTenantAdministrator',
    'provisionSampleProject',
    'removeTenantAdministrator',
    'getUsersNotInTenant',
    'getAllPropertyTemplates',
    'getPropertyTemplateCategoriesAdmin',
    'createPropertyTemplateAdmin',
    'updatePropertyTemplateAdmin',
    'deletePropertyTemplateAdmin',
    'getAllLicenses',
    'createLicense',
    'updateLicense',
    'deleteLicense',
    'getAllFeatureFlags',
    'createFeatureFlag',
    'updateFeatureFlag',
    'deleteFeatureFlag',
    'getAllFeatureFlagGroups',
    'createFeatureFlagGroup',
    'updateFeatureFlagGroup',
    'deleteFeatureFlagGroup',
    'getAllUsersWithLicenses',
    'getUserLicense',
    'assignLicenseToUser',
    'removeUserLicense',
    'setUserFeatureFlag',
    'removeUserFeatureFlag',
    'togglePropertyTemplateStatus',
    'getPropertyTemplateStats',
  ];
  return Object.fromEntries(names.map((name) => [name, jest.fn(async () => `admin:${name}`)]));
});

import * as actions from '../lib/db/admin-actions';
import * as adminModule from '../lib/db/admin-helper';

const admin = adminModule as unknown as Record<string, jest.Mock>;
const NAMES = Object.keys(actions) as Array<keyof typeof actions>;

beforeEach(() => {
  mockVerdict = null;
  for (const fn of Object.values(admin)) if (jest.isMockFunction(fn)) fn.mockClear();
});

describe('admin console actions', () => {
  test('wrap every admin-helper function the console uses', () => {
    expect(NAMES.length).toBe(41);
  });

  test.each(NAMES)('%s refuses without the super-admin session', async (name) => {
    mockVerdict = 'Unauthorized';
    const result = await (actions[name] as (...a: unknown[]) => Promise<unknown>)('id-1', 'id-2');
    expect(JSON.parse(result as string)).toEqual({ success: false, error: 'Unauthorized' });
    expect(admin[name]).not.toHaveBeenCalled();
  });

  test.each(NAMES)('%s reaches admin-helper with the same arguments for a super admin', async (name) => {
    const result = await (actions[name] as (...a: unknown[]) => Promise<unknown>)('id-1', 'id-2');
    expect(admin[name]).toHaveBeenCalledWith('id-1', 'id-2');
    expect(result).toBe(`admin:${name}`);
  });
});
