/**
 * Unit tests for import error report builder (#736).
 * Tests buildImportErrorReport and getImportErrorReportFilename.
 */

import { describe, test, expect, beforeEach, afterEach } from '@jest/globals';
import {
  buildImportErrorReport,
  getImportErrorReportFilename,
  type ImportStatusForReport
} from '../../lib/db/import-error-report';

describe('buildImportErrorReport', () => {
  const fixedExportedAt = '2025-02-10T12:00:00.000Z';

  test('builds report with minimal status (no summary, no events)', () => {
    const status: ImportStatusForReport = {
      jobId: 'job-1',
      state: 'completed'
    };
    const report = buildImportErrorReport(status, fixedExportedAt);

    expect(report.jobId).toBe('job-1');
    expect(report.state).toBe('completed');
    expect(report.exportedAt).toBe(fixedExportedAt);
    expect(report.summary).toEqual({
      success: 0,
      warnings: 0,
      failed: 0,
      properties: 0,
      totalTime: undefined,
      sourceName: undefined,
      projectName: undefined,
      projectId: undefined,
      versionId: undefined
    });
    expect(report.failedClasses).toEqual([]);
    expect(report.verificationMismatches).toEqual([]);
    expect(report.errorsAndWarnings).toEqual([]);
  });

  test('includes summary counts from status.summary', () => {
    const status: ImportStatusForReport = {
      jobId: 'job-2',
      state: 'completed',
      summary: {
        classesCreated: 5,
        propertiesCreated: 20,
        warnings: 1,
        failed: 2,
        totalTime: 3000,
        sourceName: 'openapi.yaml',
        projectName: 'My API',
        projectId: 'proj-1',
        versionId: 'v1'
      }
    };
    const report = buildImportErrorReport(status, fixedExportedAt);

    expect(report.summary).toEqual({
      success: 5,
      warnings: 1,
      failed: 2,
      properties: 20,
      totalTime: 3000,
      sourceName: 'openapi.yaml',
      projectName: 'My API',
      projectId: 'proj-1',
      versionId: 'v1'
    });
  });

  test('prefers status.result for projectId and versionId over summary', () => {
    const status: ImportStatusForReport = {
      jobId: 'job-3',
      state: 'completed',
      summary: {
        projectId: 'old-proj',
        versionId: 'old-ver'
      },
      result: {
        projectId: 'new-proj',
        versionId: 'new-ver'
      }
    };
    const report = buildImportErrorReport(status, fixedExportedAt);

    expect(report.summary.projectId).toBe('new-proj');
    expect(report.summary.versionId).toBe('new-ver');
  });

  test('filters failed classes from summary.classes', () => {
    const status: ImportStatusForReport = {
      jobId: 'job-4',
      state: 'failed',
      summary: {
        classes: [
          { name: 'User', status: 'success' },
          { name: 'Order', status: 'failed' },
          { name: 'Product', status: 'warning' },
          { name: 'Payment', status: 'failed' }
        ]
      }
    };
    const report = buildImportErrorReport(status, fixedExportedAt);

    expect(report.failedClasses).toEqual([
      { name: 'Order' },
      { name: 'Payment' }
    ]);
  });

  test('includes verification mismatches when present', () => {
    const status: ImportStatusForReport = {
      jobId: 'job-5',
      state: 'completed',
      summary: {
        verification: {
          passed: false,
          classesVerified: 2,
          propertiesVerified: 10,
          mismatches: [
            {
              type: 'missing_property',
              className: 'User',
              propertyName: 'email',
              message: 'Property email not found in database'
            },
            {
              type: 'property_mismatch',
              className: 'Order',
              propertyName: 'total',
              expected: 'number',
              actual: 'string',
              message: 'Type mismatch'
            }
          ]
        }
      }
    };
    const report = buildImportErrorReport(status, fixedExportedAt);

    expect(report.verificationMismatches).toHaveLength(2);
    expect(report.verificationMismatches[0]).toEqual({
      type: 'missing_property',
      className: 'User',
      propertyName: 'email',
      message: 'Property email not found in database'
    });
    expect(report.verificationMismatches[1].message).toBe('Type mismatch');
  });

  test('filters events to error and warn only', () => {
    const status: ImportStatusForReport = {
      jobId: 'job-6',
      state: 'failed',
      events: [
        { id: 'e1', ts: 1000, level: 'info', code: 'INIT', message: 'Starting' },
        { id: 'e2', ts: 2000, level: 'warn', code: 'SKIP', message: 'Skipped item' },
        { id: 'e3', ts: 3000, level: 'error', code: 'CLASS_FAILED', message: 'Failed to create class' },
        { id: 'e4', ts: 4000, level: 'info', code: 'DONE', message: 'Done' }
      ]
    };
    const report = buildImportErrorReport(status, fixedExportedAt);

    expect(report.errorsAndWarnings).toHaveLength(2);
    expect(report.errorsAndWarnings[0]).toEqual({
      timestamp: '1970-01-01T00:00:02.000Z',
      level: 'warn',
      code: 'SKIP',
      message: 'Skipped item'
    });
    expect(report.errorsAndWarnings[1]).toEqual({
      timestamp: '1970-01-01T00:00:03.000Z',
      level: 'error',
      code: 'CLASS_FAILED',
      message: 'Failed to create class'
    });
  });

  test('includes event context when present', () => {
    const status: ImportStatusForReport = {
      jobId: 'job-7',
      state: 'failed',
      events: [
        {
          id: 'e1',
          ts: 1000,
          level: 'error',
          code: 'FAILED',
          message: 'Import failed',
          context: { className: 'User', detail: 'Constraint violation' }
        }
      ]
    };
    const report = buildImportErrorReport(status, fixedExportedAt);

    expect(report.errorsAndWarnings).toHaveLength(1);
    expect(report.errorsAndWarnings[0].context).toEqual({
      className: 'User',
      detail: 'Constraint violation'
    });
  });

  test('uses current ISO time when exportedAt not provided', () => {
    const status: ImportStatusForReport = { jobId: 'j', state: 'completed' };
    const before = new Date().toISOString();
    const report = buildImportErrorReport(status);
    const after = new Date().toISOString();

    expect(report.exportedAt >= before && report.exportedAt <= after).toBe(true);
  });
});

describe('getImportErrorReportFilename', () => {
  test('returns filename with jobId and timestamp with colons replaced by hyphens', () => {
    const name = getImportErrorReportFilename('job-abc', '2025-02-10T14:30:00.000Z');
    expect(name).toBe('import-error-report-job-abc-2025-02-10T14-30-00.json');
  });

  test('uses current time when exportedAt not provided', () => {
    const name = getImportErrorReportFilename('job-1');
    expect(name).toMatch(/^import-error-report-job-1-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}\.json$/);
  });
});
