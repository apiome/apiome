'use server';

/**
 * The import wizard's server actions.
 *
 * A job is started for a workspace and a user named in its input, and later calls name it by id
 * alone, so each action checks the session first (`lib/auth/action-guard.ts`):
 *
 * - **Starting** (and retrying) an import needs the input's user to be the caller and
 *   `imports:create` in the input's workspace.
 * - **Every other call** needs the caller to be the user who started the job, still in its
 *   workspace. Anyone else is told the job was not found, the same answer as for an unknown id.
 */

import { requireSelf, requireTenantMember, requireTenantPermission, type Refusal } from '../auth/action-guard';
import * as importHelper from './import-helper';

/**
 * Whether the caller may act on a job: they started it, and are still in its workspace.
 *
 * @param jobId The job id.
 * @returns `null` to proceed (also for an unknown job, which the helper reports), or a refusal.
 */
async function ownJob(jobId: string): Promise<Refusal> {
  const owner = importHelper.getImportJobOwner(jobId);
  if (!owner) return null;
  return (await requireSelf(owner.userId)) ?? (await requireTenantMember(owner.tenantId));
}

/** The refusal for a job the caller may not touch, worded as the helpers word a missing job. */
const JOB_NOT_FOUND = { success: false, error: 'Job not found' } as const;

/**
 * Start an import.
 *
 * @throws Error when the caller may not import into the workspace (as the helper throws for bad input).
 */
export async function startImport(input: importHelper.ImportJobInput) {
  const refusal =
    (await requireSelf(input?.userId)) ?? (await requireTenantPermission(input?.tenantId, 'imports:create'));
  if (refusal) throw new Error(refusal);
  return importHelper.startImport(input);
}

export async function getImportStatus(jobId: string) {
  if (await ownJob(jobId)) return importHelper.importJobNotFoundStatus(jobId);
  return importHelper.getImportStatus(jobId);
}

export async function cancelImport(jobId: string) {
  if (await ownJob(jobId)) return { success: false };
  return importHelper.cancelImport(jobId);
}

export async function commitImport(jobId: string) {
  if (await ownJob(jobId)) return JOB_NOT_FOUND;
  return importHelper.commitImport(jobId);
}

export async function rollbackImport(jobId: string) {
  if (await ownJob(jobId)) return JOB_NOT_FOUND;
  return importHelper.rollbackImport(jobId);
}

/** Also needs `projects:delete` when the import created a project (checked by `permanentDeleteProject`). */
export async function rollbackCompletedImport(jobId: string) {
  if (await ownJob(jobId)) return JOB_NOT_FOUND;
  return importHelper.rollbackCompletedImport(jobId);
}

/** Retrying starts the job again, so it also needs `imports:create` in the job's workspace. */
export async function retryImport(jobId: string) {
  if (await ownJob(jobId)) return JOB_NOT_FOUND;
  const owner = importHelper.getImportJobOwner(jobId);
  if (owner) {
    const refusal = await requireTenantPermission(owner.tenantId, 'imports:create');
    if (refusal) return { success: false, error: refusal };
  }
  return importHelper.retryImport(jobId);
}

export type { ImportJobInput, ImportStatus, ImportEvent, ProgressEvent, ImportJobState, ImportLogLevel } from './import-helper';
