/**
 * Unit tests for #590: Import as new version of existing schema (sub-version e.g. 1.0.0b).
 * - Flow: getVersionById -> bumpPrereleaseVersion -> createVersion -> importClassesToVersion with new version id
 * - overwriteExisting is false when importing into the new version
 * - Error handling when getVersionById or createVersion fails
 */

import { describe, it, expect, jest, beforeEach } from '@jest/globals';

const mockGetVersionById = jest.fn();
const mockCreateVersion = jest.fn();

jest.mock('../../lib/db/helper', () => {
  const actual = jest.requireActual('../../lib/db/helper');
  return {
    ...actual,
    getVersionById: (...args: unknown[]) => mockGetVersionById(...args),
    createVersion: (...args: unknown[]) => mockCreateVersion(...args),
  };
});

const mockImportClassesToVersion = jest.fn();

jest.mock('../../lib/db/class-import-actions', () => ({
  importClassesToVersion: (...args: unknown[]) => mockImportClassesToVersion(...args),
}));

jest.mock('next/headers', () => ({
  cookies: jest.fn(() => ({ getAll: () => [] })),
}));

const mockNormalize = jest.fn();
jest.mock('../../lib/importers', () => ({
  getImporter: jest.fn(() => ({ normalize: (input: unknown) => mockNormalize(input) })),
}));

// Import after mocks so we get real bumpPrereleaseVersion and mocked getVersionById, createVersion, importClassesToVersion
import { getVersionById, createVersion, bumpPrereleaseVersion } from '../../lib/db/helper';
import { importClassesToVersion } from '../../lib/db/class-import-actions';

const CURRENT_VERSION_RECORD_ID = 'ver-current-uuid';
const PROJECT_ID = 'proj-1';
const USER_ID = 'user-1';
const NEW_VERSION_RECORD_ID = 'ver-new-1.0.0b';
const PRERELEASE_SUFFIX = 'b';

/**
 * Replicates the ClassImportDialog handleImport flow when conflictResolution === 'createVersion'.
 * Returns { success, error?, newVersionId? } for assertion.
 */
async function runCreateVersionThenImportFlow(params: {
  versionId: string;
  projectId: string;
  userId: string;
  prereleaseSuffix: string;
  document: unknown;
  selectedSchemas: string[];
  importOptions: Record<string, unknown>;
}): Promise<{ success: boolean; error?: string; newVersionId?: string }> {
  const { versionId, projectId, userId, prereleaseSuffix } = params;

  const getRes = JSON.parse(await getVersionById(versionId));
  if (!getRes.success || !getRes.version_id) {
    return { success: false, error: getRes.error || 'Could not load current version' };
  }

  const newVersionIdStr = await bumpPrereleaseVersion(getRes.version_id, prereleaseSuffix.trim() || 'b');
  const createRes = JSON.parse(
    await createVersion(
      projectId,
      userId,
      newVersionIdStr,
      'Imported as new version',
      'Import as new version to avoid conflicts'
    )
  );
  if (!createRes.success || !createRes.version?.id) {
    return { success: false, error: createRes.error || 'Could not create new version' };
  }

  const targetVersionId = createRes.version.id;
  const result = await importClassesToVersion({
    ...params.importOptions,
    versionId: targetVersionId,
    projectId,
    document: params.document,
    selectedSchemas: params.selectedSchemas,
    overwriteExisting: false,
  } as any);

  if (!result.success) {
    return { success: false, error: result.error, newVersionId: targetVersionId };
  }
  return { success: true, newVersionId: targetVersionId };
}

describe('#590 Import as new version of existing schema', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGetVersionById.mockResolvedValue(
      JSON.stringify({ success: true, id: CURRENT_VERSION_RECORD_ID, version_id: '1.0.0' })
    );
    mockCreateVersion.mockResolvedValue(
      JSON.stringify({
        success: true,
        version: { id: NEW_VERSION_RECORD_ID, version_id: '1.0.0b' },
      })
    );
    mockImportClassesToVersion.mockResolvedValue({
      success: true,
      importedCount: 2,
      importedClasses: ['Pet', 'Order'],
    });
  });

  describe('bumpPrereleaseVersion (used by flow)', () => {
    it('produces 1.0.0b from 1.0.0 and suffix "b"', async () => {
      expect(await bumpPrereleaseVersion('1.0.0', 'b')).toBe('1.0.0b');
    });

    it('strips existing prerelease from base (e.g. 1.0.0-beta -> 1.0.0)', async () => {
      expect(await bumpPrereleaseVersion('1.0.0-beta', 'b')).toBe('1.0.0b');
    });

    it('uses default "b" when suffix is empty string', async () => {
      expect(await bumpPrereleaseVersion('2.1.0', '')).toBe('2.1.0b');
    });

    it('allows custom suffix (e.g. import)', async () => {
      expect(await bumpPrereleaseVersion('1.0.0', 'import')).toBe('1.0.0import');
    });
  });

  describe('create-version-then-import flow', () => {
    it('calls getVersionById with current version record id', async () => {
      await runCreateVersionThenImportFlow({
        versionId: CURRENT_VERSION_RECORD_ID,
        projectId: PROJECT_ID,
        userId: USER_ID,
        prereleaseSuffix: PRERELEASE_SUFFIX,
        document: { components: { schemas: {} } },
        selectedSchemas: ['Pet'],
        importOptions: {},
      });

      expect(mockGetVersionById).toHaveBeenCalledTimes(1);
      expect(mockGetVersionById).toHaveBeenCalledWith(CURRENT_VERSION_RECORD_ID);
    });

    it('calls createVersion with projectId, userId, and new sub-version string (e.g. 1.0.0b)', async () => {
      await runCreateVersionThenImportFlow({
        versionId: CURRENT_VERSION_RECORD_ID,
        projectId: PROJECT_ID,
        userId: USER_ID,
        prereleaseSuffix: 'b',
        document: { components: { schemas: {} } },
        selectedSchemas: ['Pet'],
        importOptions: {},
      });

      expect(mockCreateVersion).toHaveBeenCalledTimes(1);
      expect(mockCreateVersion).toHaveBeenCalledWith(
        PROJECT_ID,
        USER_ID,
        '1.0.0b',
        'Imported as new version',
        'Import as new version to avoid conflicts'
      );
    });

    it('calls importClassesToVersion with new version record id and overwriteExisting false', async () => {
      const doc = { openapi: '3.0.0', components: { schemas: { Pet: { type: 'object' } } } };
      await runCreateVersionThenImportFlow({
        versionId: CURRENT_VERSION_RECORD_ID,
        projectId: PROJECT_ID,
        userId: USER_ID,
        prereleaseSuffix: 'b',
        document: doc,
        selectedSchemas: ['Pet'],
        importOptions: { applyNamingConvention: true },
      });

      expect(mockImportClassesToVersion).toHaveBeenCalledTimes(1);
      const callArg = mockImportClassesToVersion.mock.calls[0][0];
      expect(callArg.versionId).toBe(NEW_VERSION_RECORD_ID);
      expect(callArg.overwriteExisting).toBe(false);
      expect(callArg.projectId).toBe(PROJECT_ID);
      expect(callArg.selectedSchemas).toEqual(['Pet']);
    });

    it('returns success and newVersionId when all steps succeed', async () => {
      const result = await runCreateVersionThenImportFlow({
        versionId: CURRENT_VERSION_RECORD_ID,
        projectId: PROJECT_ID,
        userId: USER_ID,
        prereleaseSuffix: 'b',
        document: {},
        selectedSchemas: ['A'],
        importOptions: {},
      });

      expect(result.success).toBe(true);
      expect(result.newVersionId).toBe(NEW_VERSION_RECORD_ID);
    });

    it('returns error when getVersionById fails', async () => {
      mockGetVersionById.mockResolvedValueOnce(
        JSON.stringify({ success: false, error: 'Version not found' })
      );

      const result = await runCreateVersionThenImportFlow({
        versionId: 'nonexistent',
        projectId: PROJECT_ID,
        userId: USER_ID,
        prereleaseSuffix: 'b',
        document: {},
        selectedSchemas: ['A'],
        importOptions: {},
      });

      expect(result.success).toBe(false);
      expect(result.error).toBe('Version not found');
      expect(mockCreateVersion).not.toHaveBeenCalled();
      expect(mockImportClassesToVersion).not.toHaveBeenCalled();
    });

    it('returns error when getVersionById returns no version_id', async () => {
      mockGetVersionById.mockResolvedValueOnce(
        JSON.stringify({ success: true, id: 'ver-1', version_id: null })
      );

      const result = await runCreateVersionThenImportFlow({
        versionId: CURRENT_VERSION_RECORD_ID,
        projectId: PROJECT_ID,
        userId: USER_ID,
        prereleaseSuffix: 'b',
        document: {},
        selectedSchemas: ['A'],
        importOptions: {},
      });

      expect(result.success).toBe(false);
      expect(result.error).toContain('Could not load');
      expect(mockCreateVersion).not.toHaveBeenCalled();
    });

    it('returns error when createVersion fails', async () => {
      mockCreateVersion.mockResolvedValueOnce(
        JSON.stringify({ success: false, error: 'A version with this ID already exists for this project' })
      );

      const result = await runCreateVersionThenImportFlow({
        versionId: CURRENT_VERSION_RECORD_ID,
        projectId: PROJECT_ID,
        userId: USER_ID,
        prereleaseSuffix: 'b',
        document: {},
        selectedSchemas: ['A'],
        importOptions: {},
      });

      expect(result.success).toBe(false);
      expect(result.error).toContain('already exists');
      expect(mockImportClassesToVersion).not.toHaveBeenCalled();
    });

    it('uses custom prerelease suffix for new version string', async () => {
      mockGetVersionById.mockResolvedValueOnce(
        JSON.stringify({ success: true, id: CURRENT_VERSION_RECORD_ID, version_id: '2.0.0' })
      );
      mockCreateVersion.mockResolvedValueOnce(
        JSON.stringify({
          success: true,
          version: { id: 'ver-2.0.0import', version_id: '2.0.0import' },
        })
      );
      mockImportClassesToVersion.mockResolvedValueOnce({ success: true, importedCount: 1 });

      await runCreateVersionThenImportFlow({
        versionId: CURRENT_VERSION_RECORD_ID,
        projectId: PROJECT_ID,
        userId: USER_ID,
        prereleaseSuffix: 'import',
        document: {},
        selectedSchemas: ['X'],
        importOptions: {},
      });

      expect(mockCreateVersion).toHaveBeenCalledWith(
        PROJECT_ID,
        USER_ID,
        '2.0.0import',
        'Imported as new version',
        'Import as new version to avoid conflicts'
      );
    });
  });

  describe('conflict report impact text for createVersion (#590)', () => {
    /** Mirrors ClassImportDialog impactIfResolved for duplicate_schema when conflictResolution === 'createVersion' */
    function buildCreateVersionImpact(prereleaseSuffix: string): string {
      const suffix = prereleaseSuffix.trim() || 'b';
      return `With "Import as new version" a new sub-version (e.g. 1.0.0${suffix}) will be created and the import will go there; the current version is unchanged.`;
    }

    it('impact text includes prerelease suffix', () => {
      expect(buildCreateVersionImpact('b')).toContain('1.0.0b');
      expect(buildCreateVersionImpact('b')).toContain('Import as new version');
      expect(buildCreateVersionImpact('b')).toContain('current version is unchanged');
    });

    it('impact text uses default "b" when suffix is empty', () => {
      expect(buildCreateVersionImpact('')).toContain('1.0.0b');
    });

    it('impact text uses custom suffix', () => {
      expect(buildCreateVersionImpact('import')).toContain('1.0.0import');
    });
  });
});
