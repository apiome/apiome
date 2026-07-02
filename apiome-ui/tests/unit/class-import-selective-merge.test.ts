/**
 * Unit tests for #593: Selective per-property merge strategy.
 * - importClassesToVersion accepts propertyMergeStrategies and passes it when merging.
 * - Merge path uses getClassWithPropertiesAndTags and mergeClasses with options.
 */

import { describe, it, expect, jest, beforeEach } from '@jest/globals';

const mockCreateClass = jest.fn();
const mockAddPropertyToClass = jest.fn();
const mockUpdateClass = jest.fn();
const mockGetClassesForVersion = jest.fn();
const mockGetClassWithPropertiesAndTags = jest.fn();
const mockDeleteClassPropertiesForClass = jest.fn();

jest.mock('../../lib/db/helper', () => ({
  createClass: (...args: unknown[]) => mockCreateClass(...args),
  addPropertyToClass: (...args: unknown[]) => mockAddPropertyToClass(...args),
  updateClass: (...args: unknown[]) => mockUpdateClass(...args),
  getClassesForVersion: (...args: unknown[]) => mockGetClassesForVersion(...args),
  getClassWithPropertiesAndTags: (...args: unknown[]) => mockGetClassWithPropertiesAndTags(...args),
  deleteClassPropertiesForClass: (...args: unknown[]) => mockDeleteClassPropertiesForClass(...args),
}));

const mockMergeClasses = jest.fn();
jest.mock('../../src/app/utils/schema-merge', () => ({
  mergeClasses: (...args: unknown[]) => {
    const result = mockMergeClasses(...args);
    if (result !== undefined) return result;
    const imported = args[1] as { name: string; properties?: unknown[] };
    return { ...imported, name: imported?.name ?? 'Merged', properties: imported?.properties ?? [] };
  },
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

import { importClassesToVersion, type ImportClassesInput } from '../../lib/db/class-import-actions';

const DEFAULT_VERSION_ID = 'ver-1';
const DEFAULT_PROJECT_ID = 'proj-1';
const DEFAULT_DOCUMENT = { openapi: '3.0.0', info: { title: 'Test', version: '1.0.0' } };

function defaultInput(overrides: Partial<ImportClassesInput> = {}): ImportClassesInput {
  return {
    versionId: DEFAULT_VERSION_ID,
    projectId: DEFAULT_PROJECT_ID,
    document: DEFAULT_DOCUMENT,
    selectedSchemas: ['Pet'],
    ...overrides,
  };
}

describe('#593 Selective per-property merge strategy', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ success: true, property: { id: 'prop-1' } }),
    });
    mockGetClassesForVersion.mockResolvedValue(
      JSON.stringify([{ id: 'existing-pet-id', name: 'Pet' }])
    );
    mockGetClassWithPropertiesAndTags.mockResolvedValue(
      JSON.stringify({
        id: 'existing-pet-id',
        name: 'Pet',
        description: 'Existing pet',
        schema: { type: 'object' },
        properties: [
          { id: 'p1', parent_id: null, name: 'id', data: { type: 'string' }, description: null },
          { id: 'p2', parent_id: null, name: 'name', data: { type: 'string' }, description: null },
        ],
      })
    );
    mockUpdateClass.mockResolvedValue(JSON.stringify({ success: true, class: { id: 'existing-pet-id' } }));
    mockAddPropertyToClass.mockResolvedValue(
      JSON.stringify({ success: true, classProperty: { id: 'cp-1' } })
    );
    mockNormalize.mockReturnValue({
      classes: [
        {
          name: 'Pet',
          originalSchemaKey: 'Pet',
          description: 'Imported pet',
          schema: { type: 'object' },
          properties: [
            { name: 'id', data: { type: 'integer' }, description: null, children: undefined },
            { name: 'name', data: { type: 'string' }, description: null, children: undefined },
            { name: 'tag', data: { type: 'string' }, description: null, children: undefined },
          ],
        },
      ],
      warnings: [],
    });
  });

  describe('ImportClassesInput', () => {
    it('accepts optional propertyMergeStrategies', () => {
      const input: ImportClassesInput = {
        versionId: 'v1',
        projectId: 'p1',
        document: {},
        selectedSchemas: ['A'],
        overwriteExisting: true,
        mergeStrategy: 'additive',
        propertyMergeStrategies: {
          A: { id: 'override' },
        },
      };
      expect(input.propertyMergeStrategies).toEqual({ A: { id: 'override' } });
    });

    it('accepts optional arrayMergeStrategy (#595)', () => {
      const input: ImportClassesInput = {
        versionId: 'v1',
        projectId: 'p1',
        document: {},
        selectedSchemas: ['A'],
        overwriteExisting: true,
        mergeStrategy: 'override',
        arrayMergeStrategy: 'deduplicate',
      };
      expect(input.arrayMergeStrategy).toBe('deduplicate');
    });
  });

  describe('when overwriteExisting and mergeStrategy are set', () => {
    it('calls mergeClasses with propertyMergeStrategies when provided', async () => {
      const propertyMergeStrategies = {
        Pet: { id: 'override' as const, name: 'additive' as const },
      };

      await importClassesToVersion(
        defaultInput({
          overwriteExisting: true,
          mergeStrategy: 'additive',
          propertyMergeStrategies,
        })
      );

      expect(mockMergeClasses).toHaveBeenCalledTimes(1);
      const [, , strategy, options] = mockMergeClasses.mock.calls[0];
      expect(strategy).toBe('additive');
      expect(options).toEqual({
        schemaKey: 'Pet',
        propertyMergeStrategies,
        arrayMergeStrategy: undefined,
      });
    });

    it('calls mergeClasses with arrayMergeStrategy when provided (#595)', async () => {
      await importClassesToVersion(
        defaultInput({
          overwriteExisting: true,
          mergeStrategy: 'override',
          arrayMergeStrategy: 'deduplicate',
        })
      );

      expect(mockMergeClasses).toHaveBeenCalledTimes(1);
      const [, , , options] = mockMergeClasses.mock.calls[0];
      expect(options).toEqual({
        schemaKey: 'Pet',
        propertyMergeStrategies: undefined,
        arrayMergeStrategy: 'deduplicate',
      });
    });

    it('calls mergeClasses with both propertyMergeStrategies and arrayMergeStrategy when provided', async () => {
      const propertyMergeStrategies = { Pet: { id: 'override' as const } };

      await importClassesToVersion(
        defaultInput({
          overwriteExisting: true,
          mergeStrategy: 'additive',
          propertyMergeStrategies,
          arrayMergeStrategy: 'append',
        })
      );

      expect(mockMergeClasses).toHaveBeenCalledTimes(1);
      const [, , , options] = mockMergeClasses.mock.calls[0];
      expect(options?.propertyMergeStrategies).toEqual(propertyMergeStrategies);
      expect(options?.arrayMergeStrategy).toBe('append');
    });

    it('calls mergeClasses with schemaKey from normalized class originalSchemaKey', async () => {
      mockNormalize.mockReturnValue({
        classes: [
          {
            name: 'Order',
            originalSchemaKey: 'order_item',
            description: null,
            schema: { type: 'object' },
            properties: [{ name: 'quantity', data: { type: 'integer' }, description: null, children: undefined }],
          },
        ],
        warnings: [],
      });
      mockGetClassesForVersion.mockResolvedValue(
        JSON.stringify([{ id: 'ord-1', name: 'Order' }])
      );
      mockGetClassWithPropertiesAndTags.mockResolvedValue(
        JSON.stringify({
          id: 'ord-1',
          name: 'Order',
          description: null,
          schema: { type: 'object' },
          properties: [{ id: 'q1', parent_id: null, name: 'quantity', data: { type: 'number' }, description: null }],
        })
      );

      await importClassesToVersion(
        defaultInput({
          selectedSchemas: ['order_item'],
          overwriteExisting: true,
          mergeStrategy: 'override',
          propertyMergeStrategies: { order_item: { quantity: 'additive' } },
        })
      );

      expect(mockMergeClasses).toHaveBeenCalledTimes(1);
      const [, , , options] = mockMergeClasses.mock.calls[0];
      expect(options?.schemaKey).toBe('order_item');
      expect(options?.propertyMergeStrategies).toEqual({ order_item: { quantity: 'additive' } });
    });

    it('calls mergeClasses with undefined options when propertyMergeStrategies not provided', async () => {
      await importClassesToVersion(
        defaultInput({
          overwriteExisting: true,
          mergeStrategy: 'additive',
        })
      );

      expect(mockMergeClasses).toHaveBeenCalledTimes(1);
      const [, , , options] = mockMergeClasses.mock.calls[0];
      expect(options).toEqual({
        schemaKey: 'Pet',
        propertyMergeStrategies: undefined,
        arrayMergeStrategy: undefined,
      });
    });
  });
});
