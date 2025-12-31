'use server';

import * as importHelper from './import-helper';

export async function startImport(input: importHelper.ImportJobInput) {
  return importHelper.startImport(input);
}

export async function getImportStatus(jobId: string) {
  return importHelper.getImportStatus(jobId);
}

export async function cancelImport(jobId: string) {
  return importHelper.cancelImport(jobId);
}

export async function commitImport(jobId: string) {
  return importHelper.commitImport(jobId);
}

export async function rollbackImport(jobId: string) {
  return importHelper.rollbackImport(jobId);
}

export type { ImportJobInput, ImportStatus, ImportEvent, ProgressEvent, ImportJobState, ImportLogLevel } from './import-helper';

