/**
 * Unit tests for #587: Replace existing schema with imported schema (overwrite existing).
 * - overwriteExisting flag and behavior in importClassesToVersion
 * - getClassesForVersion, updateClass, deleteClassPropertiesForClass used when overwriting
 * - createClass skipped for classes that exist when overwriteExisting is true
 */

import { describe, it, expect, jest, beforeEach } from '@jest/globals';

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
const DEFAULT_DOCUMENT = { openapi: '3.0.0', info: { title: 'Test', version: '1.0.0' } };

function defaultInput(overrides: Partial<ImportClassesInput> = {}): ImportClassesInput {
  return {
    versionId: DEFAULT_VERSION_ID,
    projectId: DEFAULT_PROJECT_ID,
    document: DEFAULT_DOCUMENT,
    selectedSchemas: ['ExistingClass'],
    ...overrides,
  };
}

describe('#587 Overwrite existing with imported schema', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ success: true, property: { id: 'prop-1' } }),
    });
  });

  describe('ImportClassesInput interface', () => {
    it('accepts optional overwriteExisting flag', () => {
      const input: ImportClassesInput = {
        versionId: 'v1',
        projectId: 'p1',
        document: {},
        selectedSchemas: ['A'],
        overwriteExisting: true,
      };
      expect(input.overwriteExisting).toBe(true);
    });

    it('works without overwriteExisting (default behavior)', () => {
      const input: ImportClassesInput = {
        versionId: 'v1',
        projectId: 'p1',
        document: {},
        selectedSchemas: ['A'],
      };
      expect(input.overwriteExisting).toBeUndefined();
    });
  });

  describe('when overwriteExisting is true', () => {
    it('calls getClassesForVersion to resolve existing class ids', async () => {
      const existingClasses = [{ id: 'existing-class-id', name: 'ExistingClass' }];
      mockGetClassesForVersion.mockResolvedValue(JSON.stringify(existingClasses));
      mockUpdateClass.mockResolvedValue(JSON.stringify({ success: true, class: { id: 'existing-class-id' } }));
      mockAddPropertyToClass.mockResolvedValue(
        JSON.stringify({ success: true, classProperty: { id: 'cp-1' } })
      );
      mockNormalize.mockReturnValue({
        classes: [
          {
            name: 'ExistingClass',
            description: 'Updated description',
            schema: { type: 'object' },
            properties: [{ name: 'id', description: null, data: { type: 'string' }, children: [] }],
          },
        ],
        warnings: [],
      });

      const result = await importClassesToVersion(
        defaultInput({ overwriteExisting: true })
      );

      expect(mockGetClassesForVersion).toHaveBeenCalledTimes(1);
      expect(mockGetClassesForVersion).toHaveBeenCalledWith(DEFAULT_VERSION_ID);
      expect(result.success).toBe(true);
      expect(result.importedClasses).toContain('ExistingClass');
    });

    it('calls deleteClassPropertiesForClass and updateClass for existing class', async () => {
      const existingClasses = [{ id: 'existing-class-id', name: 'ExistingClass' }];
      mockGetClassesForVersion.mockResolvedValue(JSON.stringify(existingClasses));
      mockUpdateClass.mockResolvedValue(JSON.stringify({ success: true, class: { id: 'existing-class-id' } }));
      mockAddPropertyToClass.mockResolvedValue(
        JSON.stringify({ success: true, classProperty: { id: 'cp-1' } })
      );
      mockNormalize.mockReturnValue({
        classes: [
          {
            name: 'ExistingClass',
            description: 'Desc',
            schema: { type: 'object' },
            properties: [{ name: 'id', description: null, data: { type: 'string' }, children: [] }],
          },
        ],
        warnings: [],
      });

      await importClassesToVersion(defaultInput({ overwriteExisting: true }));

      expect(mockDeleteClassPropertiesForClass).toHaveBeenCalledWith('existing-class-id');
      expect(mockUpdateClass).toHaveBeenCalledWith(
        'existing-class-id',
        'ExistingClass',
        'Desc',
        expect.any(Object)
      );
    });

    it('does not call createClass when class already exists', async () => {
      const existingClasses = [{ id: 'existing-class-id', name: 'ExistingClass' }];
      mockGetClassesForVersion.mockResolvedValue(JSON.stringify(existingClasses));
      mockUpdateClass.mockResolvedValue(JSON.stringify({ success: true, class: { id: 'existing-class-id' } }));
      mockNormalize.mockReturnValue({
        classes: [
          {
            name: 'ExistingClass',
            description: null,
            schema: { type: 'object' },
            properties: [],
          },
        ],
        warnings: [],
      });

      await importClassesToVersion(defaultInput({ overwriteExisting: true }));

      expect(mockCreateClass).not.toHaveBeenCalled();
      expect(mockUpdateClass).toHaveBeenCalledTimes(1);
    });

    it('creates new class when name is not in existing list', async () => {
      const existingClasses = [{ id: 'existing-id', name: 'ExistingClass' }];
      mockGetClassesForVersion.mockResolvedValue(JSON.stringify(existingClasses));
      mockUpdateClass.mockResolvedValue(JSON.stringify({ success: true, class: {} }));
      mockCreateClass.mockResolvedValue(
        JSON.stringify({ success: true, class: { id: 'new-class-id' } })
      );
      mockAddPropertyToClass.mockResolvedValue(
        JSON.stringify({ success: true, classProperty: { id: 'cp-1' } })
      );
      mockNormalize.mockReturnValue({
        classes: [
          {
            name: 'ExistingClass',
            description: null,
            schema: { type: 'object' },
            properties: [],
          },
          {
            name: 'NewClass',
            description: null,
            schema: { type: 'object' },
            properties: [{ name: 'x', description: null, data: { type: 'string' }, children: [] }],
          },
        ],
        warnings: [],
      });

      const result = await importClassesToVersion(
        defaultInput({ overwriteExisting: true, selectedSchemas: ['ExistingClass', 'NewClass'] })
      );

      expect(result.success).toBe(true);
      expect(result.importedClasses).toContain('ExistingClass');
      expect(result.importedClasses).toContain('NewClass');
      expect(mockUpdateClass).toHaveBeenCalledTimes(1);
      expect(mockCreateClass).toHaveBeenCalledTimes(1);
      expect(mockCreateClass).toHaveBeenCalledWith(DEFAULT_VERSION_ID, 'NewClass', null, expect.any(Object));
    });

    it('returns success with importedCount when overwrite succeeds', async () => {
      mockGetClassesForVersion.mockResolvedValue(
        JSON.stringify([{ id: 'id-1', name: 'ExistingClass' }])
      );
      mockUpdateClass.mockResolvedValue(JSON.stringify({ success: true, class: {} }));
      mockNormalize.mockReturnValue({
        classes: [
          {
            name: 'ExistingClass',
            description: null,
            schema: { type: 'object' },
            properties: [],
          },
        ],
        warnings: [],
      });

      const result = await importClassesToVersion(
        defaultInput({ overwriteExisting: true })
      );

      expect(result.success).toBe(true);
      expect(result.importedCount).toBe(1);
      expect(result.importedClasses).toEqual(['ExistingClass']);
    });
  });

  describe('when overwriteExisting is false or omitted', () => {
    it('does not call getClassesForVersion', async () => {
      mockCreateClass.mockResolvedValue(
        JSON.stringify({ success: true, class: { id: 'new-id' } })
      );
      mockNormalize.mockReturnValue({
        classes: [
          {
            name: 'NewClass',
            description: null,
            schema: { type: 'object' },
            properties: [],
          },
        ],
        warnings: [],
      });

      await importClassesToVersion(
        defaultInput({ selectedSchemas: ['NewClass'], overwriteExisting: false })
      );

      expect(mockGetClassesForVersion).not.toHaveBeenCalled();
      expect(mockCreateClass).toHaveBeenCalled();
    });

    it('skips class and increments skippedCount when createClass returns already exists', async () => {
      mockCreateClass
        .mockResolvedValueOnce(
          JSON.stringify({ success: false, error: 'A class with this name already exists in this version' })
        );
      mockNormalize.mockReturnValue({
        classes: [
          {
            name: 'ExistingClass',
            description: null,
            schema: { type: 'object' },
            properties: [],
          },
        ],
        warnings: [],
      });

      const result = await importClassesToVersion(
        defaultInput({ overwriteExisting: false })
      );

      expect(result.success).toBe(true);
      expect(result.skippedCount).toBe(1);
      expect(result.importedClasses).toEqual([]);
      expect(mockGetClassesForVersion).not.toHaveBeenCalled();
      expect(mockUpdateClass).not.toHaveBeenCalled();
    });
  });

  describe('error handling', () => {
    it('propagates error when updateClass fails during overwrite', async () => {
      mockGetClassesForVersion.mockResolvedValue(
        JSON.stringify([{ id: 'id-1', name: 'ExistingClass' }])
      );
      mockUpdateClass.mockResolvedValue(
        JSON.stringify({ success: false, error: 'Update failed' })
      );
      mockNormalize.mockReturnValue({
        classes: [
          {
            name: 'ExistingClass',
            description: null,
            schema: { type: 'object' },
            properties: [],
          },
        ],
        warnings: [],
      });

      const result = await importClassesToVersion(
        defaultInput({ overwriteExisting: true })
      );

      expect(result.success).toBe(false);
      expect(result.error).toContain('Update failed');
    });

    it('propagates error when getClassesForVersion returns invalid JSON', async () => {
      mockGetClassesForVersion.mockResolvedValue('not valid json');
      mockNormalize.mockReturnValue({
        classes: [{ name: 'A', description: null, schema: {}, properties: [] }],
        warnings: [],
      });

      const result = await importClassesToVersion(
        defaultInput({ overwriteExisting: true })
      );

      expect(result.success).toBe(false);
      expect(result.error).toBeDefined();
    });
  });
});
