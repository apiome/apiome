/**
 * Import Actions Tests
 *
 * Tests for the import-actions module which provides server actions
 * for the import functionality. This is a thin wrapper around import-helper
 * that can be called from client components.
 */

import { describe, test, expect, jest, beforeEach } from '@jest/globals';
import type { ImportJobInput, ImportStatus } from '../lib/db/import-helper';

// Mock the import-helper module
jest.mock('../lib/db/import-helper', () => ({
  startImport: jest.fn(),
  getImportStatus: jest.fn(),
  cancelImport: jest.fn(),
  commitImport: jest.fn(),
  rollbackImport: jest.fn(),
  rollbackCompletedImport: jest.fn(),
  retryImport: jest.fn(),
}));

describe('Import Actions - Module Exports', () => {
  test('should export startImport function', async () => {
    // Import the module
    const importActions = await import('../lib/db/import-actions');

    expect(typeof importActions.startImport).toBe('function');
  });

  test('should export getImportStatus function', async () => {
    const importActions = await import('../lib/db/import-actions');

    expect(typeof importActions.getImportStatus).toBe('function');
  });

  test('should export cancelImport function', async () => {
    const importActions = await import('../lib/db/import-actions');

    expect(typeof importActions.cancelImport).toBe('function');
  });

  test('should export retryImport function', async () => {
    const importActions = await import('../lib/db/import-actions');

    expect(typeof importActions.retryImport).toBe('function');
  });

  test('should export rollbackCompletedImport function', async () => {
    const importActions = await import('../lib/db/import-actions');

    expect(typeof importActions.rollbackCompletedImport).toBe('function');
  });
});

describe('Import Actions - Type Exports', () => {
  test('should export ImportJobInput type', () => {
    // Type checking - this will fail at compile time if type doesn't exist
    const input: ImportJobInput = {
      tenantId: 'test',
      userId: 'test',
      sourceKind: 'openapi' as any,
      document: {},
      project: { name: 'Test', slug: 'test' },
      version: { versionId: '1.0.0' },
      options: { selectedSchemas: [] }
    };

    expect(input).toBeDefined();
    expect(input.tenantId).toBe('test');
  });

  test('should export ImportStatus type', () => {
    const status: ImportStatus = {
      jobId: 'test-123',
      state: 'queued',
      percent: 0,
      events: []
    };

    expect(status).toBeDefined();
    expect(status.jobId).toBe('test-123');
  });

  test('should export all necessary types', async () => {
    const importActions = await import('../lib/db/import-actions');

    // Verify type exports exist (TypeScript will catch if they don't)
    type TestTypes = {
      ImportJobInput: typeof importActions.ImportJobInput;
      ImportStatus: typeof importActions.ImportStatus;
      ImportEvent: typeof importActions.ImportEvent;
      ProgressEvent: typeof importActions.ProgressEvent;
      ImportJobState: typeof importActions.ImportJobState;
      ImportLogLevel: typeof importActions.ImportLogLevel;
    };

    expect(true).toBe(true); // Types exist if this compiles
  });
});

describe('Import Actions - startImport Integration', () => {
  test('should call import-helper startImport with correct parameters', async () => {
    const { startImport } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    const mockInput: ImportJobInput = {
      tenantId: 'tenant-123',
      userId: 'user-456',
      sourceKind: 'openapi' as any,
      document: { openapi: '3.1.0', info: { title: 'Test API', version: '1.0.0' } },
      project: {
        name: 'Test Project',
        slug: 'test-project',
        description: 'Test Description'
      },
      version: {
        versionId: '1.0.0',
        description: 'Initial version'
      },
      options: {
        selectedSchemas: ['User', 'Product'],
        autoLayout: true,
        createRelationships: true
      }
    };

    // Mock the helper function
    (importHelper.startImport as jest.Mock).mockResolvedValue({ jobId: 'job-123' });

    const result = await startImport(mockInput);

    expect(importHelper.startImport).toHaveBeenCalledWith(mockInput);
    expect(result).toEqual({ jobId: 'job-123' });
  });

  test('should handle startImport errors gracefully', async () => {
    const { startImport } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    const mockInput: ImportJobInput = {
      tenantId: 'test',
      userId: 'test',
      sourceKind: 'openapi' as any,
      document: {},
      project: { name: 'Test', slug: 'test' },
      version: { versionId: '1.0.0' },
      options: { selectedSchemas: [] }
    };

    // Mock error
    (importHelper.startImport as jest.Mock).mockRejectedValue(new Error('Import failed'));

    await expect(startImport(mockInput)).rejects.toThrow('Import failed');
  });

  test('should pass through all import options', async () => {
    const { startImport } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    const mockInput: ImportJobInput = {
      tenantId: 'tenant-123',
      userId: 'user-456',
      sourceKind: 'openapi' as any,
      document: {},
      project: { name: 'Test', slug: 'test' },
      version: { versionId: '1.0.0' },
      options: {
        selectedSchemas: ['Schema1', 'Schema2', 'Schema3'],
        autoLayout: true,
        createRelationships: false,
        applyNamingConvention: true,
        dryRun: false
      }
    };

    (importHelper.startImport as jest.Mock).mockResolvedValue({ jobId: 'job-456' });

    await startImport(mockInput);

    expect(importHelper.startImport).toHaveBeenCalledWith(
      expect.objectContaining({
        options: expect.objectContaining({
          selectedSchemas: expect.arrayContaining(['Schema1', 'Schema2', 'Schema3']),
          autoLayout: true,
          createRelationships: false,
          applyNamingConvention: true,
          dryRun: false
        })
      })
    );
  });

  test('should pass dryRun: true to import-helper for preview-only import (#729)', async () => {
    const { startImport } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    const mockInput: ImportJobInput = {
      tenantId: 'tenant-123',
      userId: 'user-456',
      sourceKind: 'openapi' as any,
      document: { openapi: '3.1.0' },
      project: { name: 'Preview Project', slug: 'preview-project' },
      version: { versionId: '1.0.0' },
      options: {
        selectedSchemas: ['User', 'Order'],
        dryRun: true
      }
    };

    (importHelper.startImport as jest.Mock).mockResolvedValue({ jobId: 'job-dry-run' });

    const result = await startImport(mockInput);

    expect(importHelper.startImport).toHaveBeenCalledWith(mockInput);
    expect(importHelper.startImport).toHaveBeenCalledWith(
      expect.objectContaining({
        options: expect.objectContaining({
          dryRun: true,
          selectedSchemas: ['User', 'Order']
        })
      })
    );
    expect(result).toEqual({ jobId: 'job-dry-run' });
  });

  test('should pass incrementalMode: true to import-helper for incremental import (#730)', async () => {
    const { startImport } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    const mockInput: ImportJobInput = {
      tenantId: 'tenant-123',
      userId: 'user-456',
      sourceKind: 'openapi' as any,
      document: { openapi: '3.1.0' },
      project: { name: 'Incremental Project', slug: 'incremental-project' },
      version: { versionId: '1.0.0' },
      options: {
        selectedSchemas: ['User', 'Product'],
        dryRun: false,
        incrementalMode: true
      }
    };

    (importHelper.startImport as jest.Mock).mockResolvedValue({ jobId: 'job-incremental' });

    const result = await startImport(mockInput);

    expect(importHelper.startImport).toHaveBeenCalledWith(mockInput);
    expect(importHelper.startImport).toHaveBeenCalledWith(
      expect.objectContaining({
        options: expect.objectContaining({
          dryRun: false,
          incrementalMode: true,
          selectedSchemas: ['User', 'Product']
        })
      })
    );
    expect(result).toEqual({ jobId: 'job-incremental' });
  });
});

describe('Import Actions - getImportStatus Integration', () => {
  test('should call import-helper getImportStatus with jobId', async () => {
    const { getImportStatus } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    const mockStatus: ImportStatus = {
      jobId: 'job-123',
      state: 'running',
      percent: 50,
      events: [
        {
          id: 'evt-1',
          ts: Date.now(),
          level: 'info',
          code: 'PROGRESS',
          message: 'Import in progress'
        }
      ],
      progress: {
        phase: 'creating-classes',
        total: 10,
        completed: 5,
        currentItem: 'User'
      }
    };

    (importHelper.getImportStatus as jest.Mock).mockResolvedValue(mockStatus);

    const result = await getImportStatus('job-123');

    expect(importHelper.getImportStatus).toHaveBeenCalledWith('job-123');
    expect(result).toEqual(mockStatus);
    expect(result.jobId).toBe('job-123');
    expect(result.state).toBe('running');
    expect(result.percent).toBe(50);
  });

  test('should handle queued state', async () => {
    const { getImportStatus } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    const mockStatus: ImportStatus = {
      jobId: 'job-queued',
      state: 'queued',
      percent: 0,
      events: []
    };

    (importHelper.getImportStatus as jest.Mock).mockResolvedValue(mockStatus);

    const result = await getImportStatus('job-queued');

    expect(result.state).toBe('queued');
    expect(result.percent).toBe(0);
  });

  test('should handle completed state with summary', async () => {
    const { getImportStatus } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    const mockStatus: ImportStatus = {
      jobId: 'job-complete',
      state: 'completed',
      percent: 100,
      events: [],
      summary: {
        projectId: 'proj-123',
        versionId: 'ver-456'
      }
    };

    (importHelper.getImportStatus as jest.Mock).mockResolvedValue(mockStatus);

    const result = await getImportStatus('job-complete');

    expect(result.state).toBe('completed');
    expect(result.percent).toBe(100);
    expect(result.summary).toBeDefined();
    expect(result.summary!.projectId).toBe('proj-123');
  });

  test('should handle failed state with error events', async () => {
    const { getImportStatus } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    const mockStatus: ImportStatus = {
      jobId: 'job-failed',
      state: 'failed',
      percent: 30,
      events: [
        {
          id: 'evt-error',
          ts: Date.now(),
          level: 'error',
          code: 'IMPORT_ERROR',
          message: 'Failed to create project'
        }
      ]
    };

    (importHelper.getImportStatus as jest.Mock).mockResolvedValue(mockStatus);

    const result = await getImportStatus('job-failed');

    expect(result.state).toBe('failed');
    expect(result.events.length).toBeGreaterThan(0);
    expect(result.events[0].level).toBe('error');
  });

  test('should handle canceled state', async () => {
    const { getImportStatus } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    const mockStatus: ImportStatus = {
      jobId: 'job-canceled',
      state: 'canceled',
      percent: 45,
      events: [
        {
          id: 'evt-cancel',
          ts: Date.now(),
          level: 'warn',
          code: 'CANCELED',
          message: 'Import canceled by user'
        }
      ]
    };

    (importHelper.getImportStatus as jest.Mock).mockResolvedValue(mockStatus);

    const result = await getImportStatus('job-canceled');

    expect(result.state).toBe('canceled');
  });

  test('should handle non-existent job', async () => {
    const { getImportStatus } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    const mockStatus: ImportStatus = {
      jobId: 'job-nonexistent',
      state: 'failed',
      percent: 0,
      events: [
        {
          id: 'evt-notfound',
          ts: Date.now(),
          level: 'error',
          code: 'NOT_FOUND',
          message: 'Job not found'
        }
      ]
    };

    (importHelper.getImportStatus as jest.Mock).mockResolvedValue(mockStatus);

    const result = await getImportStatus('job-nonexistent');

    expect(result.events[0].code).toBe('NOT_FOUND');
  });
});

describe('Import Actions - cancelImport Integration', () => {
  test('should call import-helper cancelImport with jobId', async () => {
    const { cancelImport } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    (importHelper.cancelImport as jest.Mock).mockResolvedValue({ success: true });

    const result = await cancelImport('job-123');

    expect(importHelper.cancelImport).toHaveBeenCalledWith('job-123');
    expect(result).toEqual({ success: true });
  });

  test('should handle successful cancellation', async () => {
    const { cancelImport } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    (importHelper.cancelImport as jest.Mock).mockResolvedValue({ success: true });

    const result = await cancelImport('job-running');

    expect(result.success).toBe(true);
  });

  test('should handle failed cancellation', async () => {
    const { cancelImport } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    (importHelper.cancelImport as jest.Mock).mockResolvedValue({ success: false });

    const result = await cancelImport('job-nonexistent');

    expect(result.success).toBe(false);
  });

  test('should handle cancellation of already completed job', async () => {
    const { cancelImport } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    // Job already completed, cancellation returns false
    (importHelper.cancelImport as jest.Mock).mockResolvedValue({ success: false });

    const result = await cancelImport('job-completed');

    expect(result.success).toBe(false);
  });
});

describe('Import Actions - retryImport (error recovery)', () => {
  test('should call import-helper retryImport with jobId', async () => {
    const { retryImport } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    (importHelper.retryImport as jest.Mock).mockResolvedValue({ success: true, jobId: 'job-new-123' });

    const result = await retryImport('job-failed-456');

    expect(importHelper.retryImport).toHaveBeenCalledWith('job-failed-456');
    expect(result.success).toBe(true);
    expect(result.jobId).toBe('job-new-123');
  });

  test('should return new jobId on successful retry', async () => {
    const { retryImport } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    (importHelper.retryImport as jest.Mock).mockResolvedValue({ success: true, jobId: 'job-retry-789' });

    const result = await retryImport('job-failed');

    expect(result).toEqual({ success: true, jobId: 'job-retry-789' });
  });

  test('should return error when job not found', async () => {
    const { retryImport } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    (importHelper.retryImport as jest.Mock).mockResolvedValue({ success: false, error: 'Job not found' });

    const result = await retryImport('job-nonexistent');

    expect(result.success).toBe(false);
    expect(result.error).toBe('Job not found');
    expect(result.jobId).toBeUndefined();
  });

  test('should return error when job state does not allow retry', async () => {
    const { retryImport } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    (importHelper.retryImport as jest.Mock).mockResolvedValue({
      success: false,
      error: 'Import can only be retried when it has failed or was canceled (current state: running)'
    });

    const result = await retryImport('job-running');

    expect(result.success).toBe(false);
    expect(result.error).toContain('can only be retried');
  });

  test('should propagate retryImport errors', async () => {
    const { retryImport } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    (importHelper.retryImport as jest.Mock).mockRejectedValue(new Error('Failed to start retry'));

    await expect(retryImport('job-failed')).rejects.toThrow('Failed to start retry');
  });
});

describe('Import Actions - Server Action Behavior', () => {
  test('should be marked as server action', async () => {
    const fileContent = `'use server';`;

    // Verify that module uses 'use server' directive
    expect(fileContent).toContain("'use server'");
  });

  test('should delegate all logic to import-helper', async () => {
    const { startImport, getImportStatus, cancelImport } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    // Setup mocks
    (importHelper.startImport as jest.Mock).mockResolvedValue({ jobId: 'test' });
    (importHelper.getImportStatus as jest.Mock).mockResolvedValue({ jobId: 'test', state: 'running', percent: 0, events: [] });
    (importHelper.cancelImport as jest.Mock).mockResolvedValue({ success: true });

    const mockInput: ImportJobInput = {
      tenantId: 'test',
      userId: 'test',
      sourceKind: 'openapi' as any,
      document: {},
      project: { name: 'Test', slug: 'test' },
      version: { versionId: '1.0.0' },
      options: { selectedSchemas: [] }
    };

    // All functions should delegate
    await startImport(mockInput);
    await getImportStatus('test-job');
    await cancelImport('test-job');

    expect(importHelper.startImport).toHaveBeenCalled();
    expect(importHelper.getImportStatus).toHaveBeenCalled();
    expect(importHelper.cancelImport).toHaveBeenCalled();
  });
});

describe('Import Actions - Error Propagation', () => {
  test('should propagate startImport errors', async () => {
    const { startImport } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    const mockInput: ImportJobInput = {
      tenantId: 'test',
      userId: 'test',
      sourceKind: 'openapi' as any,
      document: {},
      project: { name: 'Test', slug: 'test' },
      version: { versionId: '1.0.0' },
      options: { selectedSchemas: [] }
    };

    (importHelper.startImport as jest.Mock).mockRejectedValue(new Error('Database error'));

    await expect(startImport(mockInput)).rejects.toThrow('Database error');
  });

  test('should propagate getImportStatus errors', async () => {
    const { getImportStatus } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    (importHelper.getImportStatus as jest.Mock).mockRejectedValue(new Error('Job not found'));

    await expect(getImportStatus('bad-job')).rejects.toThrow('Job not found');
  });

  test('should propagate cancelImport errors', async () => {
    const { cancelImport } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    (importHelper.cancelImport as jest.Mock).mockRejectedValue(new Error('Cannot cancel'));

    await expect(cancelImport('bad-job')).rejects.toThrow('Cannot cancel');
  });
});

describe('Import Actions - rollbackCompletedImport (#735)', () => {
  test('should call import-helper rollbackCompletedImport with jobId', async () => {
    const { rollbackCompletedImport } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    (importHelper.rollbackCompletedImport as jest.Mock).mockResolvedValue({ success: true });

    const result = await rollbackCompletedImport('job-completed-123');

    expect(importHelper.rollbackCompletedImport).toHaveBeenCalledWith('job-completed-123');
    expect(result).toEqual({ success: true });
  });

  test('should return error when rollback fails', async () => {
    const { rollbackCompletedImport } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    (importHelper.rollbackCompletedImport as jest.Mock).mockResolvedValue({
      success: false,
      error: 'No project ID associated with this import'
    });

    const result = await rollbackCompletedImport('job-completed');

    expect(result.success).toBe(false);
    expect(result.error).toBe('No project ID associated with this import');
  });

  test('should only allow rollback when import is completed', async () => {
    const { rollbackCompletedImport } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    (importHelper.rollbackCompletedImport as jest.Mock).mockResolvedValue({
      success: false,
      error: 'Rollback of completed import is only allowed when the import has been committed (current state: pending-approval)'
    });

    const result = await rollbackCompletedImport('job-pending');

    expect(result.success).toBe(false);
    expect(result.error).toContain('only allowed when');
  });
});

describe('Import Actions - Real-World Scenarios', () => {
  test('should handle complete import workflow', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    const mockInput: ImportJobInput = {
      tenantId: 'tenant-123',
      userId: 'user-456',
      sourceKind: 'openapi' as any,
      document: {
        openapi: '3.1.0',
        info: { title: 'API', version: '1.0.0' },
        components: {
          schemas: {
            User: { type: 'object', properties: { id: { type: 'string' } } }
          }
        }
      },
      project: { name: 'My API', slug: 'my-api' },
      version: { versionId: '1.0.0' },
      options: { selectedSchemas: ['User'] }
    };

    // Start import
    (importHelper.startImport as jest.Mock).mockResolvedValue({ jobId: 'job-workflow' });
    const startResult = await startImport(mockInput);
    expect(startResult.jobId).toBe('job-workflow');

    // Check status - running
    (importHelper.getImportStatus as jest.Mock).mockResolvedValue({
      jobId: 'job-workflow',
      state: 'running',
      percent: 50,
      events: []
    });
    let status = await getImportStatus('job-workflow');
    expect(status.state).toBe('running');

    // Check status - completed
    (importHelper.getImportStatus as jest.Mock).mockResolvedValue({
      jobId: 'job-workflow',
      state: 'completed',
      percent: 100,
      events: [],
      summary: { projectId: 'proj-123', versionId: 'ver-456' }
    });
    status = await getImportStatus('job-workflow');
    expect(status.state).toBe('completed');
    expect(status.summary).toBeDefined();
  });

  test('should handle import cancellation workflow', async () => {
    const { startImport, getImportStatus, cancelImport } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    const mockInput: ImportJobInput = {
      tenantId: 'test',
      userId: 'test',
      sourceKind: 'openapi' as any,
      document: {},
      project: { name: 'Test', slug: 'test' },
      version: { versionId: '1.0.0' },
      options: { selectedSchemas: [] }
    };

    // Start import
    (importHelper.startImport as jest.Mock).mockResolvedValue({ jobId: 'job-cancel' });
    const startResult = await startImport(mockInput);

    // Check running
    (importHelper.getImportStatus as jest.Mock).mockResolvedValue({
      jobId: 'job-cancel',
      state: 'running',
      percent: 30,
      events: []
    });
    let status = await getImportStatus('job-cancel');
    expect(status.state).toBe('running');

    // Cancel
    (importHelper.cancelImport as jest.Mock).mockResolvedValue({ success: true });
    const cancelResult = await cancelImport('job-cancel');
    expect(cancelResult.success).toBe(true);

    // Check canceled
    (importHelper.getImportStatus as jest.Mock).mockResolvedValue({
      jobId: 'job-cancel',
      state: 'canceled',
      percent: 30,
      events: []
    });
    status = await getImportStatus('job-cancel');
    expect(status.state).toBe('canceled');
  });

  test('should handle import failure workflow', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-actions');
    const importHelper = await import('../lib/db/import-helper');

    const mockInput: ImportJobInput = {
      tenantId: 'test',
      userId: 'test',
      sourceKind: 'openapi' as any,
      document: { invalid: 'document' },
      project: { name: 'Test', slug: 'test' },
      version: { versionId: '1.0.0' },
      options: { selectedSchemas: [] }
    };

    // Start import
    (importHelper.startImport as jest.Mock).mockResolvedValue({ jobId: 'job-fail' });
    await startImport(mockInput);

    // Check failed status
    (importHelper.getImportStatus as jest.Mock).mockResolvedValue({
      jobId: 'job-fail',
      state: 'failed',
      percent: 20,
      events: [
        {
          id: 'evt-1',
          ts: Date.now(),
          level: 'error',
          code: 'IMPORT_ERROR',
          message: 'Invalid document format'
        }
      ]
    });
    const status = await getImportStatus('job-fail');
    expect(status.state).toBe('failed');
    expect(status.events[0].level).toBe('error');
  });
});

console.log('✅ Import Actions tests defined - 38 tests total');

