/**
 * Unit tests for #589: Import with modified names to avoid conflict (rename).
 * - When conflictResolution is "rename", conflicting schemas are imported under a new name (base + suffix).
 * - importClassesToVersion is called with classNameMap and without overwriteExisting, so new classes are created.
 * - Logic for building classNameMap: conflicting selected schemas get baseName + renameSuffix.
 */

import { describe, it, expect, jest, beforeEach } from '@jest/globals';
import { getSmartClassName } from '../../lib/schema-context-naming';

const mockCreateClass = jest.fn();
const mockAddPropertyToClass = jest.fn();
const mockUpdateClass = jest.fn();
const mockGetClassesForVersion = jest.fn();
const mockDeleteClassPropertiesForClass = jest.fn();

jest.mock('../../lib/db/helper', () => ({
  createClass: (...args: unknown[]) => mockCreateClass(...args),
  addPropertyToClass: (...args: unknown[]) => mockAddPropertyToClass(...args),
  updateClass: (...args: unknown[]) => mockUpdateClass(...args),
  getClassesForVersion: (...args: unknown[]) => mockGetClassesForVersion(...args),
  getClassWithPropertiesAndTags: jest.fn(),
  deleteClassPropertiesForClass: (...args: unknown[]) => mockDeleteClassPropertiesForClass(...args),
}));

const mockNormalize = jest.fn();
jest.mock('../../lib/importers', () => ({
  getImporter: jest.fn(() => ({
    normalize: (input: unknown) => mockNormalize(input),
  })),
}));

jest.mock('next/headers', () => ({
  cookies: jest.fn(() => ({
    getAll: () => [],
  })),
}));

const mockFetch = jest.fn();
global.fetch = mockFetch;

// Must import after mocks
import { importClassesToVersion, type ImportClassesInput } from '../../lib/db/class-import-actions';

const DEFAULT_VERSION_ID = 'ver-1';
const DEFAULT_PROJECT_ID = 'proj-1';
const DEFAULT_DOCUMENT = {
  openapi: '3.0.0',
  info: { title: 'Test', version: '1.0.0' },
  components: {
    schemas: {
      Pet: { type: 'object', properties: { id: { type: 'integer' }, name: { type: 'string' } } },
      Category: { type: 'object', properties: { id: { type: 'integer' } } },
    },
  },
};

function defaultInput(overrides: Partial<ImportClassesInput> = {}): ImportClassesInput {
  return {
    versionId: DEFAULT_VERSION_ID,
    projectId: DEFAULT_PROJECT_ID,
    document: DEFAULT_DOCUMENT,
    selectedSchemas: ['Pet'],
    ...overrides,
  };
}

describe('#589 Import with modified names to avoid conflict (rename)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ success: true, property: { id: 'prop-1' } }),
    });
  });

  describe('ImportClassesInput and action behavior', () => {
    it('accepts classNameMap without overwriteExisting (rename scenario)', () => {
      const input: ImportClassesInput = {
        versionId: 'v1',
        projectId: 'p1',
        document: DEFAULT_DOCUMENT,
        selectedSchemas: ['Pet'],
        classNameMap: { Pet: 'PetImported' },
      };
      expect(input.classNameMap).toEqual({ Pet: 'PetImported' });
      expect(input.overwriteExisting).toBeUndefined();
    });

    it('when classNameMap renames a schema and overwriteExisting is omitted, creates new class with mapped name', async () => {
      mockNormalize.mockReturnValue({
        classes: [
          {
            name: 'PetImported',
            description: null,
            schema: { type: 'object' },
            properties: [],
          },
        ],
        warnings: [],
      });
      mockCreateClass.mockResolvedValue(
        JSON.stringify({ success: true, class: { id: 'new-class-id' } })
      );

      const result = await importClassesToVersion(
        defaultInput({
          selectedSchemas: ['Pet'],
          classNameMap: { Pet: 'PetImported' },
          overwriteExisting: undefined,
        })
      );

      expect(result.success).toBe(true);
      expect(result.importedCount).toBe(1);
      expect(result.importedClasses).toEqual(['PetImported']);
      expect(mockGetClassesForVersion).not.toHaveBeenCalled();
      expect(mockCreateClass).toHaveBeenCalledWith(
        DEFAULT_VERSION_ID,
        'PetImported',
        null,
        expect.any(Object)
      );
      expect(mockUpdateClass).not.toHaveBeenCalled();
    });

    it('passes classNameMap through to normalizer so output class has new name', async () => {
      let capturedNormalizeInput: unknown = null;
      mockNormalize.mockImplementation((input: unknown) => {
        capturedNormalizeInput = input;
        return {
          classes: [
            {
              name: (input as any)?.options?.classNameMap?.Pet ?? 'Pet',
              description: null,
              schema: { type: 'object' },
              properties: [],
            },
          ],
          warnings: [],
        };
      });
      mockCreateClass.mockResolvedValue(
        JSON.stringify({ success: true, class: { id: 'new-id' } })
      );

      await importClassesToVersion(
        defaultInput({
          selectedSchemas: ['Pet'],
          classNameMap: { Pet: 'PetV2' },
        })
      );

      expect(capturedNormalizeInput).not.toBeNull();
      const options = (capturedNormalizeInput as any)?.options;
      expect(options?.classNameMap).toEqual({ Pet: 'PetV2' });
      expect(mockCreateClass).toHaveBeenCalledWith(
        DEFAULT_VERSION_ID,
        'PetV2',
        null,
        expect.any(Object)
      );
    });

    it('with rename (classNameMap) and overwriteExisting false, does not call getClassesForVersion', async () => {
      mockNormalize.mockReturnValue({
        classes: [
          { name: 'UserImported', description: null, schema: { type: 'object' }, properties: [] },
        ],
        warnings: [],
      });
      mockCreateClass.mockResolvedValue(
        JSON.stringify({ success: true, class: { id: 'id-1' } })
      );

      await importClassesToVersion(
        defaultInput({
          selectedSchemas: ['User'],
          classNameMap: { User: 'UserImported' },
          overwriteExisting: false,
        })
      );

      expect(mockGetClassesForVersion).not.toHaveBeenCalled();
      expect(mockCreateClass).toHaveBeenCalledWith(
        DEFAULT_VERSION_ID,
        'UserImported',
        null,
        expect.any(Object)
      );
    });
  });

  describe('buildClassNameMapForRename (spec for dialog logic)', () => {
    /**
     * Mirrors the ClassImportDialog logic for building classNameMap when conflict resolution
     * is "rename". Used to specify and test the expected behavior without rendering the component.
     */
    function buildClassNameMapForRename(
      selectedSchemaKeys: string[],
      schemaExistsSet: Set<string>,
      schemaObj: Record<string, any>,
      conflictResolution: 'keep' | 'replace' | 'merge' | 'rename',
      renameSuffix: string,
      classNameOverrides: Record<string, string>
    ): Record<string, string> {
      const classNameMap: Record<string, string> = {};
      for (const schemaKey of selectedSchemaKeys) {
        const raw = schemaObj[schemaKey];
        const baseName = classNameOverrides[schemaKey]?.trim() || getSmartClassName(schemaKey, raw);
        if (!baseName) continue;
        const isConflicting = schemaExistsSet.has(schemaKey);
        const name =
          conflictResolution === 'rename' && isConflicting
            ? baseName + (renameSuffix.trim() || 'Imported')
            : baseName;
        classNameMap[schemaKey] = name;
      }
      return classNameMap;
    }

    it('when conflictResolution is rename and schema exists, appends suffix to base name', () => {
      const schemaObj = { Pet: { type: 'object', title: 'Pet' } };
      const exists = new Set(['Pet']);
      const overrides: Record<string, string> = {};

      const map = buildClassNameMapForRename(
        ['Pet'],
        exists,
        schemaObj,
        'rename',
        'Imported',
        overrides
      );

      expect(map).toEqual({ Pet: 'PetImported' });
    });

    it('when conflictResolution is rename and suffix is empty, uses default "Imported"', () => {
      const schemaObj = { Pet: { type: 'object' } };
      const exists = new Set(['Pet']);

      const map = buildClassNameMapForRename(
        ['Pet'],
        exists,
        schemaObj,
        'rename',
        '   ',
        {}
      );

      expect(map).toEqual({ Pet: 'PetImported' });
    });

    it('when conflictResolution is rename and schema does not exist, keeps base name', () => {
      const schemaObj = { NewSchema: { type: 'object', title: 'NewSchema' } };
      const exists = new Set<string>();

      const map = buildClassNameMapForRename(
        ['NewSchema'],
        exists,
        schemaObj,
        'rename',
        'Imported',
        {}
      );

      expect(map).toEqual({ NewSchema: 'NewSchema' });
    });

    it('when conflictResolution is keep, conflicting schema keeps base name (no suffix)', () => {
      const schemaObj = { Pet: { type: 'object' } };
      const exists = new Set(['Pet']);

      const map = buildClassNameMapForRename(
        ['Pet'],
        exists,
        schemaObj,
        'keep',
        'Imported',
        {}
      );

      expect(map).toEqual({ Pet: 'Pet' });
    });

    it('when conflictResolution is rename, classNameOverrides are used as base then suffix applied', () => {
      const schemaObj = { pet_schema: { type: 'object' } };
      const exists = new Set(['pet_schema']);
      const overrides = { pet_schema: 'Pet' };

      const map = buildClassNameMapForRename(
        ['pet_schema'],
        exists,
        schemaObj,
        'rename',
        'V2',
        overrides
      );

      expect(map).toEqual({ pet_schema: 'PetV2' });
    });

    it('mixed: conflicting schema renamed, non-conflicting unchanged', () => {
      const schemaObj = {
        Pet: { type: 'object' },
        Category: { type: 'object' },
      };
      const exists = new Set(['Pet']); // only Pet conflicts

      const map = buildClassNameMapForRename(
        ['Pet', 'Category'],
        exists,
        schemaObj,
        'rename',
        'Imported',
        {}
      );

      expect(map).toEqual({ Pet: 'PetImported', Category: 'Category' });
    });

    it('uses getSmartClassName from schema title when no override', () => {
      const schemaObj = { user_dto: { type: 'object', title: 'User DTO' } };
      const exists = new Set(['user_dto']);

      const map = buildClassNameMapForRename(
        ['user_dto'],
        exists,
        schemaObj,
        'rename',
        'Imported',
        {}
      );

      expect(getSmartClassName('user_dto', schemaObj.user_dto)).toBe('User DTO');
      expect(map).toEqual({ user_dto: 'User DTOImported' });
    });
  });
});
