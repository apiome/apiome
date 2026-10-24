/**
 * lib/db/import-actions — the session checks in front of the import wizard's actions.
 *
 * Starting an import needs the input's user to be the caller and imports:create in its workspace;
 * every later call needs the caller to be the user who started the job. Anyone else is told the job
 * was not found. (Delegation is covered by tests/import-actions.test.ts.)
 */

import { describe, test, expect, jest, beforeEach } from '@jest/globals';

let mockSelf: string | null = null;
let mockMember: string | null = null;
let mockPermission: string | null = null;

jest.mock('../lib/auth/action-guard', () => ({
  requireSelf: jest.fn(async () => mockSelf),
  requireTenantMember: jest.fn(async () => mockMember),
  requireTenantPermission: jest.fn(async () => mockPermission),
}));

jest.mock('../lib/db/import-helper', () => ({
  startImport: jest.fn(async () => ({ jobId: 'job-new' })),
  getImportStatus: jest.fn(async () => ({ jobId: 'job-1', state: 'running' })),
  cancelImport: jest.fn(async () => ({ success: true })),
  commitImport: jest.fn(async () => ({ success: true })),
  rollbackImport: jest.fn(async () => ({ success: true })),
  rollbackCompletedImport: jest.fn(async () => ({ success: true })),
  retryImport: jest.fn(async () => ({ success: true, jobId: 'job-2' })),
  getImportJobOwner: jest.fn((jobId: string) => (jobId === 'job-1' ? { userId: 'user-1', tenantId: 'tenant-1' } : null)),
  importJobNotFoundStatus: jest.fn((jobId: string) => ({ jobId, state: 'failed', percent: 0, events: [] })),
}));

import * as actions from '../lib/db/import-actions';
import * as guardModule from '../lib/auth/action-guard';
import * as helperModule from '../lib/db/import-helper';
import type { ImportJobInput } from '../lib/db/import-helper';

const guard = guardModule as unknown as Record<string, jest.Mock>;
const helper = helperModule as unknown as Record<string, jest.Mock>;
const input = { tenantId: 'tenant-1', userId: 'user-1' } as unknown as ImportJobInput;

beforeEach(() => {
  mockSelf = mockMember = mockPermission = null;
  for (const fn of [...Object.values(guard), ...Object.values(helper)]) if (jest.isMockFunction(fn)) fn.mockClear();
});

describe('startImport', () => {
  test('needs the caller to be the input user, with imports:create in the workspace', async () => {
    await expect(actions.startImport(input)).resolves.toEqual({ jobId: 'job-new' });
    expect(guard.requireSelf).toHaveBeenCalledWith('user-1');
    expect(guard.requireTenantPermission).toHaveBeenCalledWith('tenant-1', 'imports:create');
  });

  test('throws for someone else’s user id and starts nothing', async () => {
    mockSelf = 'Unauthorized';
    await expect(actions.startImport(input)).rejects.toThrow('Unauthorized');
    expect(helper.startImport).not.toHaveBeenCalled();
  });

  test('throws without imports:create', async () => {
    mockPermission = 'You do not have permission to do that in this workspace (imports:create).';
    await expect(actions.startImport(input)).rejects.toThrow('imports:create');
    expect(helper.startImport).not.toHaveBeenCalled();
  });
});

describe('job actions', () => {
  const JOB_ACTIONS = ['cancelImport', 'commitImport', 'rollbackImport', 'rollbackCompletedImport', 'retryImport'] as const;

  test.each(JOB_ACTIONS)('%s refuses a job someone else started', async (name) => {
    mockSelf = 'Unauthorized';
    const result = (await actions[name]('job-1')) as { success: boolean };
    expect(result.success).toBe(false);
    expect(helper[name]).not.toHaveBeenCalled();
  });

  test.each(JOB_ACTIONS)('%s refuses once the starter has left the workspace', async (name) => {
    mockMember = 'Not found';
    const result = (await actions[name]('job-1')) as { success: boolean };
    expect(result.success).toBe(false);
    expect(helper[name]).not.toHaveBeenCalled();
  });

  test.each(JOB_ACTIONS)('%s runs for the user who started the job', async (name) => {
    await actions[name]('job-1');
    expect(guard.requireSelf).toHaveBeenCalledWith('user-1');
    expect(helper[name]).toHaveBeenCalledWith('job-1');
  });

  test('an unknown job id reaches the helper, which reports it missing', async () => {
    await actions.commitImport('job-unknown');
    expect(helper.commitImport).toHaveBeenCalledWith('job-unknown');
  });

  test('getImportStatus hides another user’s job as not found', async () => {
    mockSelf = 'Unauthorized';
    await expect(actions.getImportStatus('job-1')).resolves.toMatchObject({ jobId: 'job-1', state: 'failed' });
    expect(helper.getImportStatus).not.toHaveBeenCalled();
  });

  test('retryImport also needs imports:create, since it starts the job again', async () => {
    mockPermission = 'You do not have permission to do that in this workspace (imports:create).';
    const result = await actions.retryImport('job-1');
    expect(result).toEqual({ success: false, error: mockPermission });
    expect(helper.retryImport).not.toHaveBeenCalled();
  });
});
