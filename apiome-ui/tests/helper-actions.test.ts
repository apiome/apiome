/**
 * lib/db/helper-actions — the guarded workspace server actions.
 *
 * For every action: which check it runs (and on which workspace), that a refusal comes back as
 * `{ success: false, error }` without touching the helper, and that an allowed call reaches the
 * helper with the caller's arguments unchanged. The checks themselves are covered by
 * tests/action-guard.test.ts.
 */

import { describe, test, expect, jest, beforeEach } from '@jest/globals';

/** What each check returns this test: `null` allows, a string refuses. */
let verdict: string | null = null;
const check = () => jest.fn(async () => verdict);

jest.mock('../lib/auth/action-guard', () => ({
  NOT_FOUND: 'Not found',
  requireSelf: check(),
  requireSelfOrNobody: check(),
  requireSignedIn: check(),
  requireTenantMember: check(),
  requireTenantAdmin: check(),
  requireTenantPermission: check(),
  tenantOfAdministratorRecord: jest.fn(async () => 'tenant-of-admin-record'),
  tenantOfMemberRecord: jest.fn(async () => 'tenant-of-member-record'),
  tenantOfApiKey: jest.fn(async () => 'tenant-of-key'),
  tenantOfClass: jest.fn(async () => 'tenant-of-class'),
  tenantOfClasses: jest.fn(async () => 'tenant-of-classes'),
  tenantOfVersion: jest.fn(async () => 'tenant-of-version'),
  versionScope: jest.fn(async () => ({ tenantId: 'tenant-of-version', projectId: 'proj-1' })),
}));

jest.mock('../lib/db/helper', () => {
  const names = [
    'getDashboardStats',
    'getRecentActivity',
    'getTenantsForUser',
    'getTenantsAdministratedByUser',
    'updateUserName',
    'updateUserPassword',
    'getCurrentUserLastLoginAt',
    'getLinkedAccountsForUser',
    'getUserHasPassword',
    'unlinkExternalAccount',
    'updatePersonalAccessToken',
    'removePersonalAccessToken',
    'getTenantUsers',
    'updateTenant',
    'addTenantAdministrator',
    'addTenantUser',
    'removeTenantAdministrator',
    'removeTenantUser',
    'createProject',
    'updateProject',
    'deleteProject',
    'restoreProject',
    'permanentDeleteProject',
    'importProjectFromOpenAPI',
    'getPublishedVersionsForTenant',
    'updateVersionVisibility',
    'deleteVersion',
    'getClassesForVersion',
    'getPropertiesForClass',
    'getPropertiesForClassesBatch',
    'buildOpenApiSpecJsonForVersion',
    'getDefaultCanvasLayout',
    'getEffectiveDefaultLayoutName',
    'getNamedCanvasLayout',
    'getApiKeysForTenant',
    'createApiKey',
    'deleteApiKey',
    'toggleApiKeyStatus',
    'getVersionById',
  ];
  return Object.fromEntries(names.map((name) => [name, jest.fn(async () => `helper:${name}`)]));
});

import * as actions from '../lib/db/helper-actions';
import * as guardModule from '../lib/auth/action-guard';
import * as helperModule from '../lib/db/helper';

const guard = guardModule as unknown as Record<string, jest.Mock>;
const helper = helperModule as unknown as Record<string, jest.Mock>;

type Case = [name: keyof typeof actions, args: unknown[], check: string, checkArgs: unknown[]];

/** Every guarded action, the check it must run, and that check's arguments. */
const CASES: Case[] = [
  ['getDashboardStats', ['user-1'], 'requireSelf', ['user-1']],
  ['getRecentActivity', ['user-1', 5], 'requireSelf', ['user-1']],
  ['getTenantsForUser', ['user-1'], 'requireSelf', ['user-1']],
  ['getTenantsAdministratedByUser', ['user-1'], 'requireSelf', ['user-1']],
  ['updateUserName', ['user-1', 'Ada'], 'requireSelf', ['user-1']],
  ['updateUserPassword', ['user-1', 'old', 'new'], 'requireSelf', ['user-1']],
  ['getLinkedAccountsForUser', ['user-1'], 'requireSelf', ['user-1']],
  ['getUserHasPassword', ['user-1'], 'requireSelf', ['user-1']],
  ['unlinkExternalAccount', ['user-1', 'acct-1'], 'requireSelf', ['user-1']],
  ['updatePersonalAccessToken', ['user-1', 'acct-1', 'ghp_x'], 'requireSelf', ['user-1']],
  ['removePersonalAccessToken', ['user-1', 'acct-1'], 'requireSelf', ['user-1']],
  ['getTenantUsers', ['tenant-1'], 'requireTenantMember', ['tenant-1']],
  ['updateTenant', ['tenant-1', 'Acme', 'd'], 'requireTenantAdmin', ['tenant-1']],
  ['addTenantAdministrator', ['tenant-1', 'a@example.com'], 'requireTenantAdmin', ['tenant-1']],
  ['addTenantUser', ['tenant-1', 'a@example.com'], 'requireTenantAdmin', ['tenant-1']],
  ['removeTenantAdministrator', ['rec-1'], 'requireTenantAdmin', ['tenant-of-admin-record']],
  ['removeTenantUser', ['rec-1'], 'requireTenantAdmin', ['tenant-of-member-record']],
  ['getPublishedVersionsForTenant', ['tenant-1', null], 'requireTenantMember', ['tenant-1']],
  ['updateVersionVisibility', ['ver-1', 'public'], 'requireTenantPermission', ['tenant-of-version', 'versions:publish']],
  ['getClassesForVersion', ['ver-1'], 'requireTenantMember', ['tenant-of-version']],
  ['getPropertiesForClass', ['cls-1'], 'requireTenantMember', ['tenant-of-class']],
  ['getPropertiesForClassesBatch', [['cls-1', 'cls-2']], 'requireTenantMember', ['tenant-of-classes']],
  ['getApiKeysForTenant', ['tenant-1'], 'requireTenantPermission', ['tenant-1', 'api_keys:view']],
  ['createApiKey', ['tenant-1', 'CI', '', null], 'requireTenantPermission', ['tenant-1', 'api_keys:create']],
  ['deleteApiKey', ['key-1'], 'requireTenantPermission', ['tenant-of-key', 'api_keys:delete']],
  ['toggleApiKeyStatus', ['key-1', false], 'requireTenantPermission', ['tenant-of-key', 'api_keys:edit']],
  ['getDefaultCanvasLayout', ['ver-1', 'user-1'], 'requireSelfOrNobody', ['user-1']],
  ['getEffectiveDefaultLayoutName', ['ver-1', 'user-1', undefined], 'requireSelfOrNobody', ['user-1']],
  ['getNamedCanvasLayout', ['ver-1', null, 'Overview'], 'requireSelfOrNobody', [null]],
];

/** Actions that check the session inside the helper and are passed straight through. */
const PASS_THROUGH: Array<keyof typeof actions> = [
  'getCurrentUserLastLoginAt',
  'createProject',
  'updateProject',
  'deleteProject',
  'restoreProject',
  'permanentDeleteProject',
  'deleteVersion',
];

beforeEach(() => {
  verdict = null;
  for (const fn of Object.values(guard)) if (jest.isMockFunction(fn)) fn.mockClear();
  for (const fn of Object.values(helper)) if (jest.isMockFunction(fn)) fn.mockClear();
});

describe('guarded actions', () => {
  test.each(CASES)('%s runs %s', async (name, args, checkName, checkArgs) => {
    await (actions[name] as (...a: unknown[]) => Promise<unknown>)(...args);
    expect(guard[checkName]).toHaveBeenCalledWith(...checkArgs);
  });

  test.each(CASES)('%s returns the refusal and writes nothing when refused', async (name, args) => {
    verdict = 'Not found';
    const result = await (actions[name] as (...a: unknown[]) => Promise<unknown>)(...args);
    expect(JSON.parse(result as string)).toEqual({ success: false, error: 'Not found' });
    expect(helper[name]).not.toHaveBeenCalled();
  });

  test.each(CASES)('%s reaches the helper with the same arguments when allowed', async (name, args) => {
    const result = await (actions[name] as (...a: unknown[]) => Promise<unknown>)(...args);
    expect(helper[name]).toHaveBeenCalledWith(...args);
    expect(result).toBe(`helper:${name}`);
  });

  test.each(PASS_THROUGH)('%s is passed through to the self-checking helper', async (name) => {
    await (actions[name] as (...a: unknown[]) => Promise<unknown>)('arg');
    expect(helper[name]).toHaveBeenCalledTimes(1);
    expect(guard.requireSelf).not.toHaveBeenCalled();
  });

  test('every export is covered by a case here', () => {
    const covered = new Set<string>([
      ...CASES.map(([name]) => name),
      ...PASS_THROUGH,
      'importProjectFromOpenAPI',
      'buildOpenApiSpecJsonForVersion',
    ]);
    expect(Object.keys(actions).filter((name) => !covered.has(name))).toEqual([]);
  });
});

describe('importProjectFromOpenAPI', () => {
  const args = ['tenant-1', 'user-1', 'Pets', 'pets', null, '1.0.0', null, []] as const;

  test('needs the creator to be the caller and projects:create in the workspace', async () => {
    await actions.importProjectFromOpenAPI(...(args as unknown as Parameters<typeof actions.importProjectFromOpenAPI>));
    expect(guard.requireSelf).toHaveBeenCalledWith('user-1');
    expect(guard.requireTenantPermission).toHaveBeenCalledWith('tenant-1', 'projects:create');
    expect(helper.importProjectFromOpenAPI).toHaveBeenCalled();
  });

  test('stops at the first refusal', async () => {
    verdict = 'Unauthorized';
    const result = await actions.importProjectFromOpenAPI(
      ...(args as unknown as Parameters<typeof actions.importProjectFromOpenAPI>)
    );
    expect(JSON.parse(result as string).error).toBe('Unauthorized');
    expect(guard.requireTenantPermission).not.toHaveBeenCalled();
    expect(helper.importProjectFromOpenAPI).not.toHaveBeenCalled();
  });
});

describe('getPropertiesForClassesBatch', () => {
  test('an empty batch only needs a signed-in caller', async () => {
    await actions.getPropertiesForClassesBatch([]);
    expect(guard.requireSignedIn).toHaveBeenCalled();
    expect(guard.tenantOfClasses).not.toHaveBeenCalled();
  });
});

describe('canvas layout reads', () => {
  test('refuse a tenant id other than the version’s own', async () => {
    const result = await actions.getEffectiveDefaultLayoutName('ver-1', 'user-1', 'tenant-other');
    expect(JSON.parse(result as string).error).toBe('Not found');
    expect(helper.getEffectiveDefaultLayoutName).not.toHaveBeenCalled();
  });

  test('check membership of the version’s workspace', async () => {
    await actions.getDefaultCanvasLayout('ver-1');
    expect(guard.requireTenantMember).toHaveBeenCalledWith('tenant-of-version');
  });
});

describe('buildOpenApiSpecJsonForVersion', () => {
  const row = { id: 'ver-1', version_id: '1.0.0', project_id: 'proj-1' };

  test('builds for a member when the row’s project is the version’s', async () => {
    await expect(actions.buildOpenApiSpecJsonForVersion(row, 'Pets')).resolves.toBe(
      'helper:buildOpenApiSpecJsonForVersion'
    );
    expect(guard.requireTenantMember).toHaveBeenCalledWith('tenant-of-version');
  });

  test('throws for a non-member', async () => {
    verdict = 'Not found';
    await expect(actions.buildOpenApiSpecJsonForVersion(row, 'Pets')).rejects.toThrow('Not found');
    expect(helper.buildOpenApiSpecJsonForVersion).not.toHaveBeenCalled();
  });

  test('throws when the row names another project', async () => {
    await expect(
      actions.buildOpenApiSpecJsonForVersion({ ...row, project_id: 'proj-other' }, 'Pets')
    ).rejects.toThrow('Not found');
    expect(helper.buildOpenApiSpecJsonForVersion).not.toHaveBeenCalled();
  });
});
