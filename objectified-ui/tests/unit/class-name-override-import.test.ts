/**
 * Unit tests for #754: Custom name override for imported classes.
 *
 * When importing, the custom name (classNameMap) is applied as an override on classes.
 * - Dashboard and studio import flows pass classNameMap through to the importer.
 * - OpenAPI importer uses classNameMap when present, otherwise getSmartClassName.
 *
 * Unit tests for #755: Prefix/suffix rules for imported class names.
 * - classPrefix and classSuffix are applied after naming convention.
 * - $ref in properties (and items.$ref) are updated to final names.
 */

import { describe, it, expect } from '@jest/globals';
import { openApiImporter } from '../../lib/importers/openapi';
import { getSmartClassName } from '../../lib/schema-context-naming';

describe('#754 Custom name override for imported classes', () => {
  describe('OpenAPI importer normalize with classNameMap', () => {
    it('uses classNameMap override when provided for selected schema', () => {
      const document = {
        components: {
          schemas: {
            order_item: {
              type: 'object',
              title: 'Order Item',
              properties: { qty: { type: 'integer' } },
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['order_item'],
          applyNamingConvention: false,
          classNameMap: { order_item: 'LineItem' },
        },
      });
      expect(result.classes).toHaveLength(1);
      expect(result.classes[0].name).toBe('LineItem');
      expect(result.classes[0].originalSchemaKey).toBe('order_item');
    });

    it('falls back to smart name when schema key not in classNameMap', () => {
      const schema = { type: 'object', title: 'User Profile', properties: {} };
      const document = {
        components: {
          schemas: {
            user_profile: schema,
          },
        },
      };
      const smartName = getSmartClassName('user_profile', schema);
      expect(smartName).toBe('User Profile');

      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['user_profile'],
          applyNamingConvention: true,
          classNamingConvention: 'PascalCase',
          propertyNamingConvention: 'camelCase',
          classNameMap: {},
        },
      });
      expect(result.classes[0].name).toBe('UserProfile');
    });

    it('applies naming convention to classNameMap override', () => {
      const document = {
        components: {
          schemas: {
            item: {
              type: 'object',
              properties: { id: { type: 'string' } },
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['item'],
          applyNamingConvention: true,
          classNamingConvention: 'PascalCase',
          propertyNamingConvention: 'camelCase',
          classNameMap: { item: 'line_item' },
        },
      });
      expect(result.classes[0].name).toBe('LineItem');
    });

    it('allows mixed overrides: some schemas in map, others use smart name', () => {
      const document = {
        components: {
          schemas: {
            a: { type: 'object', title: 'SchemaA', properties: {} },
            b: { type: 'object', title: 'SchemaB', properties: {} },
            c: { type: 'object', title: 'SchemaC', properties: {} },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['a', 'b', 'c'],
          applyNamingConvention: true,
          classNamingConvention: 'PascalCase',
          propertyNamingConvention: 'camelCase',
          classNameMap: { b: 'CustomB' },
        },
      });
      expect(result.classes.find((c) => c.originalSchemaKey === 'a')!.name).toBe('SchemaA');
      expect(result.classes.find((c) => c.originalSchemaKey === 'b')!.name).toBe('CustomB');
      expect(result.classes.find((c) => c.originalSchemaKey === 'c')!.name).toBe('SchemaC');
    });

    it('ignores classNameMap entries for non-selected schemas', () => {
      const document = {
        components: {
          schemas: {
            selected_schema: { type: 'object', title: 'Selected', properties: {} },
            not_selected: { type: 'object', title: 'NotSelected', properties: {} },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['selected_schema'],
          applyNamingConvention: false,
          classNameMap: {
            selected_schema: 'MyClass',
            not_selected: 'ShouldBeIgnored',
          },
        },
      });
      expect(result.classes).toHaveLength(1);
      expect(result.classes[0].name).toBe('MyClass');
      expect(result.classes[0].originalSchemaKey).toBe('selected_schema');
    });
  });

  describe('#755 Prefix/suffix rules for imported class names', () => {
    it('applies prefix and suffix to every class name after naming convention', () => {
      const document = {
        components: {
          schemas: {
            user: { type: 'object', properties: { id: { type: 'string' } } },
            order: { type: 'object', properties: { total: { type: 'number' } } },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['user', 'order'],
          applyNamingConvention: true,
          classNamingConvention: 'PascalCase',
          propertyNamingConvention: 'camelCase',
          classPrefix: 'Api',
          classSuffix: 'Dto',
        },
      });
      expect(result.classes).toHaveLength(2);
      expect(result.classes.map((c) => c.name).sort()).toEqual(['ApiOrderDto', 'ApiUserDto']);
    });

    it('applies only prefix when suffix is empty', () => {
      const document = {
        components: { schemas: { item: { type: 'object', properties: {} } } },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['item'],
          applyNamingConvention: true,
          classNamingConvention: 'PascalCase',
          propertyNamingConvention: 'camelCase',
          classPrefix: 'V1',
          classSuffix: '',
        },
      });
      expect(result.classes[0].name).toBe('V1Item');
    });

    it('applies only suffix when prefix is empty', () => {
      const document = {
        components: { schemas: { request: { type: 'object', properties: {} } } },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['request'],
          applyNamingConvention: true,
          classNamingConvention: 'PascalCase',
          propertyNamingConvention: 'camelCase',
          classPrefix: '',
          classSuffix: 'Model',
        },
      });
      expect(result.classes[0].name).toBe('RequestModel');
    });

    it('updates $ref in properties to use prefixed/suffixed class names', () => {
      const document = {
        components: {
          schemas: {
            user: {
              type: 'object',
              properties: {
                id: { type: 'string' },
                profile: { $ref: '#/components/schemas/profile' },
              },
            },
            profile: {
              type: 'object',
              properties: { name: { type: 'string' } },
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['user', 'profile'],
          applyNamingConvention: true,
          classNamingConvention: 'PascalCase',
          propertyNamingConvention: 'camelCase',
          classPrefix: 'Api',
          classSuffix: 'Dto',
        },
      });
      expect(result.classes.map((c) => c.name).sort()).toEqual(['ApiProfileDto', 'ApiUserDto']);
      const userClass = result.classes.find((c) => c.originalSchemaKey === 'user');
      expect(userClass).toBeDefined();
      const profileProp = userClass!.properties.find((p) => p.name === 'profile');
      expect(profileProp?.data?.$ref).toBe('#/components/schemas/ApiProfileDto');
    });

    it('ignores empty/whitespace-only prefix and suffix', () => {
      const document = {
        components: { schemas: { item: { type: 'object', properties: {} } } },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['item'],
          applyNamingConvention: false,
          classPrefix: '  ',
          classSuffix: '\t',
        },
      });
      expect(result.classes[0].name).toBe('item');
    });

    it('applies prefix/suffix when naming convention is disabled (raw schema key names)', () => {
      const document = {
        components: {
          schemas: {
            snake_case_schema: { type: 'object', properties: {} },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['snake_case_schema'],
          applyNamingConvention: false,
          classPrefix: 'Imported',
          classSuffix: 'Schema',
        },
      });
      expect(result.classes[0].name).toBe('Importedsnake_case_schemaSchema');
    });

    it('updates items.$ref for array-of-reference properties', () => {
      const document = {
        components: {
          schemas: {
            list: {
              type: 'object',
              properties: {
                items: {
                  type: 'array',
                  items: { $ref: '#/components/schemas/entry' },
                },
              },
            },
            entry: {
              type: 'object',
              properties: { value: { type: 'string' } },
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['list', 'entry'],
          applyNamingConvention: true,
          classNamingConvention: 'PascalCase',
          propertyNamingConvention: 'camelCase',
          classPrefix: 'Api',
          classSuffix: 'Dto',
        },
      });
      const listClass = result.classes.find((c) => c.originalSchemaKey === 'list');
      const itemsProp = listClass!.properties.find((p) => p.name === 'items');
      expect(itemsProp?.data?.items?.$ref).toBe('#/components/schemas/ApiEntryDto');
    });

    it('applies prefix/suffix after classNameMap and naming convention', () => {
      const document = {
        components: {
          schemas: {
            user_response: {
              type: 'object',
              properties: { id: { type: 'string' } },
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['user_response'],
          applyNamingConvention: true,
          classNamingConvention: 'PascalCase',
          propertyNamingConvention: 'camelCase',
          classNameMap: { user_response: 'UserResponse' },
          classPrefix: 'Api',
          classSuffix: '',
        },
      });
      expect(result.classes[0].name).toBe('ApiUserResponse');
    });

    it('leaves class names unchanged when prefix and suffix are undefined', () => {
      const document = {
        components: { schemas: { user: { type: 'object', properties: {} } } },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['user'],
          applyNamingConvention: true,
          classNamingConvention: 'PascalCase',
          propertyNamingConvention: 'camelCase',
        },
      });
      expect(result.classes[0].name).toBe('User');
    });

    it('leaves $ref unchanged when referenced schema is not in selected schemas', () => {
      const document = {
        components: {
          schemas: {
            owner: {
              type: 'object',
              properties: {
                external: { $ref: '#/components/schemas/other_service_entity' },
              },
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['owner'],
          applyNamingConvention: true,
          classNamingConvention: 'PascalCase',
          propertyNamingConvention: 'camelCase',
          classPrefix: 'Api',
          classSuffix: 'Dto',
        },
      });
      const ownerClass = result.classes.find((c) => c.originalSchemaKey === 'owner');
      const externalProp = ownerClass!.properties.find((p) => p.name === 'external');
      expect(externalProp?.data?.$ref).toBe('#/components/schemas/other_service_entity');
    });

    it('updates $ref in nested child properties', () => {
      const document = {
        components: {
          schemas: {
            wrapper: {
              type: 'object',
              properties: {
                nested: {
                  type: 'object',
                  properties: {
                    ref_to_inner: { $ref: '#/components/schemas/inner' },
                  },
                },
              },
            },
            inner: {
              type: 'object',
              properties: { x: { type: 'string' } },
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['wrapper', 'inner'],
          applyNamingConvention: true,
          classNamingConvention: 'PascalCase',
          propertyNamingConvention: 'camelCase',
          classPrefix: 'Api',
          classSuffix: 'Dto',
        },
      });
      const wrapperClass = result.classes.find((c) => c.originalSchemaKey === 'wrapper');
      const nestedProp = wrapperClass!.properties.find((p) => p.name === 'nested');
      const refProp = nestedProp!.children!.find((p: { name: string }) => p.name === 'refToInner');
      expect(refProp?.data?.$ref).toBe('#/components/schemas/ApiInnerDto');
    });
  });

  describe('getSmartClassName contract', () => {
    it('returns schema key when no title or x-class-name', () => {
      expect(getSmartClassName('api_response', { type: 'object' })).toBe('api_response');
    });

    it('returns title-derived name when title present', () => {
      expect(getSmartClassName('x', { title: 'User Profile', type: 'object' })).toBe('User Profile');
    });

    it('x-class-name takes precedence over title', () => {
      expect(
        getSmartClassName('k', { 'x-class-name': 'CustomName', title: 'Title', type: 'object' })
      ).toBe('CustomName');
    });
  });
});
