/**
 * Builds a detailed error report object from import job status.
 * Used for the "Download error report" feature (#736).
 */

export interface ImportStatusForReport {
  jobId: string;
  state: string;
  events?: Array<{
    id: string;
    ts: number;
    level: string;
    code: string;
    message: string;
    context?: unknown;
  }>;
  summary?: {
    classesCreated?: number;
    propertiesCreated?: number;
    warnings?: number;
    failed?: number;
    totalTime?: number;
    sourceName?: string;
    projectName?: string;
    projectId?: string;
    versionId?: string;
    classes?: Array<{ name: string; status: string }>;
    verification?: {
      passed: boolean;
      classesVerified?: number;
      propertiesVerified?: number;
      mismatches?: Array<{
        type: string;
        className: string;
        propertyName?: string;
        expected?: unknown;
        actual?: unknown;
        message: string;
      }>;
    };
  };
  result?: { projectId?: string; versionId?: string };
}

export interface ImportErrorReport {
  jobId: string;
  state: string;
  exportedAt: string;
  summary: {
    success: number;
    warnings: number;
    failed: number;
    properties: number;
    totalTime?: number;
    sourceName?: string;
    projectName?: string;
    projectId?: string;
    versionId?: string;
  };
  failedClasses: Array<{ name: string }>;
  verificationMismatches: Array<{
    type: string;
    className: string;
    propertyName?: string;
    expected?: unknown;
    actual?: unknown;
    message: string;
  }>;
  errorsAndWarnings: Array<{
    timestamp: string;
    level: string;
    code: string;
    message: string;
    context?: unknown;
  }>;
}

/**
 * Builds a structured error report from import job status.
 * Filters events to error/warn only and maps classes to failed only.
 */
export function buildImportErrorReport(status: ImportStatusForReport, exportedAt: string = new Date().toISOString()): ImportErrorReport {
  const rawSummary = status.summary ?? {};
  const failedClasses = (rawSummary.classes ?? []).filter((c) => c.status === 'failed');
  const verificationMismatches = rawSummary.verification?.mismatches ?? [];
  const errorsAndWarnings = (status.events ?? []).filter(
    (e) => e.level === 'error' || e.level === 'warn'
  );
  return {
    jobId: status.jobId,
    state: status.state,
    exportedAt,
    summary: {
      success: rawSummary.classesCreated ?? 0,
      warnings: rawSummary.warnings ?? 0,
      failed: rawSummary.failed ?? 0,
      properties: rawSummary.propertiesCreated ?? 0,
      totalTime: rawSummary.totalTime,
      sourceName: rawSummary.sourceName,
      projectName: rawSummary.projectName,
      projectId: status.result?.projectId ?? rawSummary.projectId,
      versionId: status.result?.versionId ?? rawSummary.versionId
    },
    failedClasses: failedClasses.map((c) => ({ name: c.name })),
    verificationMismatches,
    errorsAndWarnings: errorsAndWarnings.map((e) => ({
      timestamp: new Date(e.ts).toISOString(),
      level: e.level,
      code: e.code,
      message: e.message,
      ...(e.context != null && { context: e.context })
    }))
  };
}

/**
 * Returns a suggested filename for the error report download.
 */
export function getImportErrorReportFilename(jobId: string, exportedAt?: string): string {
  const ts = (exportedAt ?? new Date().toISOString()).slice(0, 19).replace(/:/g, '-');
  return `import-error-report-${jobId}-${ts}.json`;
}
