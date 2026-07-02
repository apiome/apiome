/**
 * Unit tests for #756: Reserved name detection during import.
 * When importing, class names and property names that conflict with
 * JavaScript/TypeScript keywords, JSON Schema keywords, or built-in
 * names produce warnings.
 */

import { describe, it, expect } from '@jest/globals';
import { openApiImporter } from '../../lib/importers/openapi';
import { isReservedName, collectReservedNameWarnings } from '../../lib/importers/reserved-names';
import type { NormalizedClass } from '../../lib/importers';

describe('#756 Reserved name detection on import', () => {
  describe('isReservedName', () => {
    it('returns true for JS/TS keywords (case-insensitive)', () => {
      expect(isReservedName('class')).toBe(true);
      expect(isReservedName('Class')).toBe(true);
      expect(isReservedName('type')).toBe(true);
      expect(isReservedName('default')).toBe(true);
      expect(isReservedName('const')).toBe(true);
      expect(isReservedName('constructor')).toBe(true);
    });

    it('returns true for JSON Schema keywords', () => {
      expect(isReservedName('required')).toBe(true);
      expect(isReservedName('properties')).toBe(true);
      expect(isReservedName('items')).toBe(true);
      expect(isReservedName('enum')).toBe(true);
      expect(isReservedName('schema')).toBe(true);
    });

    it('returns true for built-in / prototype names', () => {
      expect(isReservedName('prototype')).toBe(true);
      expect(isReservedName('__proto__')).toBe(true);
      expect(isReservedName('valueOf')).toBe(true);
      expect(isReservedName('toString')).toBe(true);
    });

    it('returns false for non-reserved names', () => {
      expect(isReservedName('User')).toBe(false);
      expect(isReservedName('orderId')).toBe(false);
      expect(isReservedName('myType')).toBe(false);
      expect(isReservedName('userId')).toBe(false);
      expect(isReservedName('displayName')).toBe(false);
    });

    it('returns false for empty or whitespace-only string', () => {
      expect(isReservedName('')).toBe(false);
      expect(isReservedName('   ')).toBe(false);
    });

    it('returns false for names that only contain a reserved word as substring', () => {
      expect(isReservedName('userType')).toBe(false);
      expect(isReservedName('defaultValue')).toBe(false);
      expect(isReservedName('myClass')).toBe(false);
    });
  });

  describe('collectReservedNameWarnings', () => {
    it('returns warnings for class and property reserved names', () => {
      const classes: NormalizedClass[] = [
        {
          name: 'type',
          originalSchemaKey: 'type',
          properties: [
            { name: 'default', data: { type: 'string' } },
          ],
        },
      ];
      const warnings = collectReservedNameWarnings(classes);
      expect(warnings.some((w) => w.includes('class name') && w.includes('type'))).toBe(true);
      expect(warnings.some((w) => w.includes('property') && w.includes('default'))).toBe(true);
    });

    it('includes originalSchemaKey in class warning when present', () => {
      const classes: NormalizedClass[] = [
        { name: 'default', originalSchemaKey: 'default_schema', properties: [] },
      ];
      const warnings = collectReservedNameWarnings(classes);
      expect(warnings).toHaveLength(1);
      expect(warnings[0]).toContain('default_schema');
      expect(warnings[0]).toContain('Consider renaming');
    });

    it('returns empty array for empty classes list', () => {
      expect(collectReservedNameWarnings([])).toEqual([]);
    });

    it('returns empty array when all class and property names are safe', () => {
      const classes: NormalizedClass[] = [
        {
          name: 'User',
          properties: [
            { name: 'userId', data: {} },
            { name: 'email', data: {} },
          ],
        },
      ];
      expect(collectReservedNameWarnings(classes)).toEqual([]);
    });

    it('checks nested properties recursively and includes context path', () => {
      const classes: NormalizedClass[] = [
        {
          name: 'Root',
          properties: [
            {
              name: 'nested',
              data: {},
              children: [
                { name: 'type', data: {} },
              ],
            },
          ],
        },
      ];
      const warnings = collectReservedNameWarnings(classes);
      const propWarning = warnings.find((w) => w.includes('property') && w.includes('type'));
      expect(propWarning).toBeDefined();
      expect(propWarning).toMatch(/class "Root".*"nested"/);
    });

    it('returns multiple warnings when multiple classes and properties are reserved', () => {
      const classes: NormalizedClass[] = [
        { name: 'class', properties: [{ name: 'type', data: {} }] },
        { name: 'default', properties: [{ name: 'constructor', data: {} }] },
      ];
      const warnings = collectReservedNameWarnings(classes);
      expect(warnings.length).toBeGreaterThanOrEqual(4);
      expect(warnings.some((w) => w.includes('class name') && w.includes('class'))).toBe(true);
      expect(warnings.some((w) => w.includes('class name') && w.includes('default'))).toBe(true);
      expect(warnings.some((w) => w.includes('property') && w.includes('type'))).toBe(true);
      expect(warnings.some((w) => w.includes('property') && w.includes('constructor'))).toBe(true);
    });
  });

  describe('OpenAPI importer normalize warnings', () => {
    it('adds warning when a class name is reserved', () => {
      const document = {
        components: {
          schemas: {
            default: {
              type: 'object',
              properties: { value: { type: 'string' } },
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['default'],
          applyNamingConvention: false,
        },
      });
      expect(result.classes).toHaveLength(1);
      expect(result.classes[0].name).toBe('default');
      const reservedWarnings = result.warnings.filter((w) =>
        w.includes('Reserved name') && w.includes('class name')
      );
      expect(reservedWarnings.length).toBeGreaterThanOrEqual(1);
      expect(reservedWarnings.some((w) => w.includes('default'))).toBe(true);
    });

    it('adds warning when a property name is reserved', () => {
      const document = {
        components: {
          schemas: {
            Settings: {
              type: 'object',
              properties: {
                type: { type: 'string' },
                value: { type: 'number' },
              },
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['Settings'],
          applyNamingConvention: false,
        },
      });
      expect(result.classes).toHaveLength(1);
      const reservedPropWarnings = result.warnings.filter((w) =>
        w.includes('Reserved name') && w.includes('property')
      );
      expect(reservedPropWarnings.length).toBeGreaterThanOrEqual(1);
      expect(reservedPropWarnings.some((w) => w.includes('type') && w.includes('Settings'))).toBe(true);
    });

    it('adds warning for reserved nested property name', () => {
      const document = {
        components: {
          schemas: {
            Wrapper: {
              type: 'object',
              properties: {
                inner: {
                  type: 'object',
                  properties: {
                    constructor: { type: 'string' },
                  },
                },
              },
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['Wrapper'],
          applyNamingConvention: false,
        },
      });
      const reservedWarnings = result.warnings.filter((w) =>
        w.includes('constructor') && w.includes('property')
      );
      expect(reservedWarnings.length).toBeGreaterThanOrEqual(1);
    });

    it('produces no reserved-name warnings when names are safe', () => {
      const document = {
        components: {
          schemas: {
            User: {
              type: 'object',
              properties: {
                userId: { type: 'string' },
                displayName: { type: 'string' },
              },
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['User'],
          applyNamingConvention: true,
          classNamingConvention: 'PascalCase',
          propertyNamingConvention: 'camelCase',
        },
      });
      const reservedWarnings = result.warnings.filter((w) => w.includes('Reserved name'));
      expect(reservedWarnings).toHaveLength(0);
    });

    it('adds warnings for multiple reserved names in one schema', () => {
      const document = {
        components: {
          schemas: {
            type: {
              type: 'object',
              properties: {
                default: { type: 'string' },
                class: { type: 'string' },
              },
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['type'],
          applyNamingConvention: false,
        },
      });
      const reservedWarnings = result.warnings.filter((w) => w.includes('Reserved name'));
      expect(reservedWarnings.length).toBeGreaterThanOrEqual(3); // class name + 2 properties
    });

    it('detects reserved names after naming convention is applied', () => {
      const document = {
        components: {
          schemas: {
            default_response: {
              type: 'object',
              properties: {
                type: { type: 'string' },
              },
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['default_response'],
          applyNamingConvention: true,
          classNamingConvention: 'PascalCase',
          propertyNamingConvention: 'camelCase',
        },
      });
      const reservedWarnings = result.warnings.filter((w) => w.includes('Reserved name'));
      expect(reservedWarnings.length).toBeGreaterThanOrEqual(1);
      expect(reservedWarnings.some((w) => w.includes('type'))).toBe(true);
    });

    it('detects reserved property in array of objects (items.properties)', () => {
      const document = {
        components: {
          schemas: {
            Container: {
              type: 'object',
              properties: {
                list: {
                  type: 'array',
                  items: {
                    type: 'object',
                    properties: {
                      enum: { type: 'string' },
                    },
                  },
                },
              },
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['Container'],
          applyNamingConvention: false,
        },
      });
      const reservedWarnings = result.warnings.filter((w) =>
        w.includes('enum') && w.includes('property')
      );
      expect(reservedWarnings.length).toBeGreaterThanOrEqual(1);
    });

    it('reserved class name warning includes schema key when different from final name', () => {
      const document = {
        components: {
          schemas: {
            default_schema: {
              type: 'object',
              properties: {},
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['default_schema'],
          applyNamingConvention: false,
          classNameMap: { default_schema: 'default' },
        },
      });
      const classWarning = result.warnings.find((w) =>
        w.includes('class name') && w.includes('default')
      );
      expect(classWarning).toBeDefined();
      expect(classWarning).toContain('default_schema');
    });
  });
});
