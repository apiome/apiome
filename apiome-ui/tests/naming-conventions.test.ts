/**
 * Unit tests for naming convention utilities (#581)
 *
 * Tests convertToNamingConvention, validateNamingConvention,
 * applyNamingConventionToClass, applyNamingConventionToClasses,
 * and OpenAPI importer integration.
 */

import {
  convertToNamingConvention,
  validateNamingConvention,
  detectNamingConvention,
  applyNamingConventionToClass,
  applyNamingConventionToClasses,
} from '../src/app/utils/naming-conventions';
import { openApiImporter } from '../lib/importers/openapi';

describe('naming-conventions (#581)', () => {
  describe('convertToNamingConvention', () => {
    it('converts to PascalCase', () => {
      expect(convertToNamingConvention('user_profile', 'PascalCase')).toBe('UserProfile');
      expect(convertToNamingConvention('userName', 'PascalCase')).toBe('UserName');
      expect(convertToNamingConvention('user-name', 'PascalCase')).toBe('UserName');
    });

    it('converts to camelCase', () => {
      expect(convertToNamingConvention('user_profile', 'camelCase')).toBe('userProfile');
      expect(convertToNamingConvention('UserProfile', 'camelCase')).toBe('userProfile');
    });

    it('converts to snake_case', () => {
      expect(convertToNamingConvention('UserProfile', 'snake_case')).toBe('user_profile');
      expect(convertToNamingConvention('userName', 'snake_case')).toBe('user_name');
    });

    it('converts to kebab-case', () => {
      expect(convertToNamingConvention('UserProfile', 'kebab-case')).toBe('user-profile');
    });

    it('returns original when convention is none', () => {
      expect(convertToNamingConvention('user_profile', 'none')).toBe('user_profile');
    });

    it('handles empty string', () => {
      expect(convertToNamingConvention('', 'PascalCase')).toBe('');
      expect(convertToNamingConvention('', 'camelCase')).toBe('');
    });

    it('handles single word', () => {
      expect(convertToNamingConvention('user', 'PascalCase')).toBe('User');
      expect(convertToNamingConvention('user', 'camelCase')).toBe('user');
      expect(convertToNamingConvention('User', 'snake_case')).toBe('user');
    });

    it('handles names with numbers', () => {
      expect(convertToNamingConvention('user_id_v2', 'PascalCase')).toBe('UserIdV2');
      expect(convertToNamingConvention('userId_v2', 'camelCase')).toBe('userIdV2');
    });

    it('handles multiple separators', () => {
      expect(convertToNamingConvention('user__profile', 'PascalCase')).toBe('UserProfile');
      expect(convertToNamingConvention('user--profile', 'kebab-case')).toBe('user-profile');
    });

    it('handles mixed separators', () => {
      expect(convertToNamingConvention('user_profile-id', 'PascalCase')).toBe('UserProfileId');
    });
  });

  describe('validateNamingConvention', () => {
    it('returns valid for matching convention', () => {
      expect(validateNamingConvention('UserProfile', 'PascalCase')).toEqual({ valid: true });
      expect(validateNamingConvention('userProfile', 'camelCase')).toEqual({ valid: true });
      expect(validateNamingConvention('user_profile', 'snake_case')).toEqual({ valid: true });
      expect(validateNamingConvention('user-profile', 'kebab-case')).toEqual({ valid: true });
    });

    it('returns suggested conversion when invalid', () => {
      const result = validateNamingConvention('user_profile', 'PascalCase');
      expect(result.valid).toBe(false);
      expect(result.suggested).toBe('UserProfile');
    });

    it('returns valid for empty string with any convention', () => {
      expect(validateNamingConvention('', 'PascalCase')).toEqual({ valid: true });
    });

    it('returns valid for convention none', () => {
      expect(validateNamingConvention('anything_here', 'none')).toEqual({ valid: true });
    });
  });

  describe('detectNamingConvention (#558)', () => {
    it('detects PascalCase', () => {
      expect(detectNamingConvention('UserProfile')).toBe('PascalCase');
      expect(detectNamingConvention('OrderItem')).toBe('PascalCase');
      expect(detectNamingConvention('User')).toBe('PascalCase');
    });
    it('detects snake_case', () => {
      expect(detectNamingConvention('user_profile')).toBe('snake_case');
      expect(detectNamingConvention('user_id_v2')).toBe('snake_case');
    });
    it('detects camelCase', () => {
      expect(detectNamingConvention('userProfile')).toBe('camelCase');
      expect(detectNamingConvention('userId')).toBe('camelCase');
    });
    it('returns other for kebab-case or invalid', () => {
      expect(detectNamingConvention('user-profile')).toBe('other');
      expect(detectNamingConvention('')).toBe('other');
    });
  });

  describe('applyNamingConventionToClass', () => {
    it('transforms class and property names', () => {
      const cls = {
        name: 'api_response',
        description: 'API response',
        properties: [
          { name: 'status_code', data: { type: 'integer' }, children: [] },
        ],
      };
      const result = applyNamingConventionToClass(cls, {
        classNamingConvention: 'PascalCase',
        propertyNamingConvention: 'camelCase',
        applyNamingConvention: true,
      });
      expect(result.name).toBe('ApiResponse');
      expect(result.properties![0].name).toBe('statusCode');
    });

    it('preserves description and other class fields', () => {
      const cls = {
        name: 'pet',
        description: 'A pet',
        schema: { type: 'object' },
        properties: [] as any[],
      };
      const result = applyNamingConventionToClass(cls, {
        classNamingConvention: 'PascalCase',
        applyNamingConvention: true,
      });
      expect(result.name).toBe('Pet');
      expect(result.description).toBe('A pet');
      expect(result.schema).toEqual({ type: 'object' });
    });

    it('returns unchanged when applyNamingConvention is false', () => {
      const cls = {
        name: 'user_profile',
        properties: [{ name: 'first_name', data: {}, children: [] }],
      };
      const result = applyNamingConventionToClass(cls, { applyNamingConvention: false });
      expect(result.name).toBe('user_profile');
      expect(result.properties![0].name).toBe('first_name');
    });

    it('handles classNamingConvention none', () => {
      const cls = {
        name: 'user_profile',
        properties: [{ name: 'first_name', data: {}, children: [] }],
      };
      const result = applyNamingConventionToClass(cls, {
        classNamingConvention: 'none',
        propertyNamingConvention: 'camelCase',
        applyNamingConvention: true,
      });
      expect(result.name).toBe('user_profile');
      expect(result.properties![0].name).toBe('firstName');
    });
  });

  describe('applyNamingConventionToClasses', () => {
    it('applies naming to class and property names', () => {
      const classes = [
        {
          name: 'user_profile',
          description: 'User',
          properties: [
            { name: 'first_name', data: { type: 'string' }, children: [] },
            { name: 'last_name', data: { type: 'string' }, children: [] },
          ],
        },
      ];
      const result = applyNamingConventionToClasses(classes, {
        classNamingConvention: 'PascalCase',
        propertyNamingConvention: 'camelCase',
        applyNamingConvention: true,
      });
      expect(result[0].name).toBe('UserProfile');
      expect(result[0].properties![0].name).toBe('firstName');
      expect(result[0].properties![1].name).toBe('lastName');
    });

    it('updates $ref in property data when class names change', () => {
      const classes = [
        {
          name: 'order_item',
          description: 'Order item',
          properties: [
            {
              name: 'product',
              data: { $ref: '#/components/schemas/product_info' },
              children: [] as any[],
            },
          ],
        },
        {
          name: 'product_info',
          description: 'Product',
          properties: [] as any[],
        },
      ];
      const result = applyNamingConventionToClasses(classes, {
        classNamingConvention: 'PascalCase',
        propertyNamingConvention: 'camelCase',
        applyNamingConvention: true,
      });
      expect(result[0].name).toBe('OrderItem');
      expect(result[0].properties![0].data.$ref).toBe('#/components/schemas/ProductInfo');
      expect(result[1].name).toBe('ProductInfo');
    });

    it('updates items.$ref for array-of-reference properties', () => {
      const classes = [
        {
          name: 'order',
          properties: [
            {
              name: 'line_items',
              data: {
                type: 'array',
                items: { $ref: '#/components/schemas/order_item' },
              },
              children: [] as any[],
            },
          ],
        },
        {
          name: 'order_item',
          properties: [] as any[],
        },
      ];
      const result = applyNamingConventionToClasses(classes, {
        classNamingConvention: 'PascalCase',
        propertyNamingConvention: 'camelCase',
        applyNamingConvention: true,
      });
      expect(result[0].properties![0].name).toBe('lineItems');
      expect(result[0].properties![0].data.items.$ref).toBe('#/components/schemas/OrderItem');
    });

    it('leaves $ref unchanged when referenced class is not in the map', () => {
      const classes = [
        {
          name: 'pet',
          properties: [
            {
              name: 'category',
              data: { $ref: '#/components/schemas/external_schema' },
              children: [] as any[],
            },
          ],
        },
      ];
      const result = applyNamingConventionToClasses(classes, {
        classNamingConvention: 'PascalCase',
        propertyNamingConvention: 'camelCase',
        applyNamingConvention: true,
      });
      expect(result[0].properties![0].data.$ref).toBe('#/components/schemas/external_schema');
    });

    it('transforms nested child properties recursively', () => {
      const classes = [
        {
          name: 'order',
          properties: [
            {
              name: 'shipping_address',
              data: { type: 'object' },
              children: [
                {
                  name: 'street_name',
                  data: { type: 'string' },
                  children: [] as any[],
                },
              ] as any[],
            },
          ],
        },
      ];
      const result = applyNamingConventionToClasses(classes, {
        classNamingConvention: 'PascalCase',
        propertyNamingConvention: 'camelCase',
        applyNamingConvention: true,
      });
      expect(result[0].properties![0].name).toBe('shippingAddress');
      expect((result[0].properties![0].children as any[])[0].name).toBe('streetName');
    });

    it('does not transform when applyNamingConvention is false', () => {
      const classes = [
        {
          name: 'user_profile',
          properties: [{ name: 'first_name', data: {}, children: [] }],
        },
      ];
      const result = applyNamingConventionToClasses(classes, {
        applyNamingConvention: false,
      });
      expect(result[0].name).toBe('user_profile');
      expect(result[0].properties![0].name).toBe('first_name');
    });

    it('returns empty array when given empty classes', () => {
      const result = applyNamingConventionToClasses([], {
        classNamingConvention: 'PascalCase',
        propertyNamingConvention: 'camelCase',
        applyNamingConvention: true,
      });
      expect(result).toEqual([]);
    });

    it('handles classes with no properties', () => {
      const classes = [{ name: 'empty_schema', properties: [] as any[] }];
      const result = applyNamingConventionToClasses(classes, {
        classNamingConvention: 'PascalCase',
        applyNamingConvention: true,
      });
      expect(result[0].name).toBe('EmptySchema');
      expect(result[0].properties).toEqual([]);
    });

    it('preserves non-$ref property data', () => {
      const classes = [
        {
          name: 'user',
          properties: [
            {
              name: 'age',
              data: { type: 'integer', minimum: 0, maximum: 150 },
              children: [] as any[],
            },
          ],
        },
      ];
      const result = applyNamingConventionToClasses(classes, {
        classNamingConvention: 'PascalCase',
        propertyNamingConvention: 'none',
        applyNamingConvention: true,
      });
      expect(result[0].properties![0].data).toEqual({ type: 'integer', minimum: 0, maximum: 150 });
    });
  });

  describe('OpenAPI importer integration', () => {
    it('applies naming convention when options.applyNamingConvention is true', () => {
      const document = {
        components: {
          schemas: {
            user_profile: {
              type: 'object',
              properties: {
                first_name: { type: 'string' },
                last_name: { type: 'string' },
              },
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['user_profile'],
          applyNamingConvention: true,
          classNamingConvention: 'PascalCase',
          propertyNamingConvention: 'camelCase',
        },
      });
      expect(result.classes).toHaveLength(1);
      expect(result.classes[0].name).toBe('UserProfile');
      expect(result.classes[0].properties.map((p) => p.name)).toEqual(['firstName', 'lastName']);
    });

    it('keeps original names when applyNamingConvention is false', () => {
      const document = {
        components: {
          schemas: {
            user_profile: {
              type: 'object',
              properties: {
                first_name: { type: 'string' },
              },
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['user_profile'],
          applyNamingConvention: false,
        },
      });
      expect(result.classes[0].name).toBe('user_profile');
      expect(result.classes[0].properties[0].name).toBe('first_name');
    });

    it('updates $ref in properties when applying naming convention', () => {
      const document = {
        components: {
          schemas: {
            pet: {
              type: 'object',
              properties: {
                category: { $ref: '#/components/schemas/category' },
              },
            },
            category: {
              type: 'object',
              properties: { name: { type: 'string' } },
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['pet', 'category'],
          applyNamingConvention: true,
          classNamingConvention: 'PascalCase',
          propertyNamingConvention: 'camelCase',
        },
      });
      const petClass = result.classes.find((c) => c.name === 'Pet')!;
      const categoryProp = petClass.properties.find((p) => p.name === 'category')!;
      expect(categoryProp.data.$ref).toBe('#/components/schemas/Category');
    });
  });

  describe('#753 class name mapping and smart naming', () => {
    it('uses smart name from schema title when no classNameMap', () => {
      const document = {
        components: {
          schemas: {
            api_response: {
              type: 'object',
              title: 'API Response',
              properties: { code: { type: 'integer' } },
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['api_response'],
          applyNamingConvention: true,
          classNamingConvention: 'PascalCase',
          propertyNamingConvention: 'camelCase',
        },
      });
      expect(result.classes).toHaveLength(1);
      expect(result.classes[0].name).toBe('ApiResponse');
      expect(result.classes[0].originalSchemaKey).toBe('api_response');
      expect(result.classes[0].properties[0].name).toBe('code');
    });

    it('uses smart name from x-class-name when present', () => {
      const document = {
        components: {
          schemas: {
            user_profile: {
              type: 'object',
              'x-class-name': 'UserProfile',
              properties: { name: { type: 'string' } },
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['user_profile'],
          applyNamingConvention: true,
          classNamingConvention: 'PascalCase',
          propertyNamingConvention: 'camelCase',
        },
      });
      expect(result.classes[0].name).toBe('UserProfile');
      expect(result.classes[0].originalSchemaKey).toBe('user_profile');
    });

    it('applies classNameMap override over schema context', () => {
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
          applyNamingConvention: true,
          classNamingConvention: 'PascalCase',
          propertyNamingConvention: 'camelCase',
          classNameMap: { order_item: 'LineItem' },
        },
      });
      expect(result.classes[0].name).toBe('LineItem');
      expect(result.classes[0].originalSchemaKey).toBe('order_item');
    });

    it('applies classNameMap for multiple schemas (partial override) (#754)', () => {
      const document = {
        components: {
          schemas: {
            user_profile: {
              type: 'object',
              title: 'User Profile',
              properties: { name: { type: 'string' } },
            },
            order_item: {
              type: 'object',
              title: 'Order Item',
              properties: { qty: { type: 'integer' } },
            },
            api_error: {
              type: 'object',
              'x-class-name': 'ApiError',
              properties: { code: { type: 'integer' } },
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['user_profile', 'order_item', 'api_error'],
          applyNamingConvention: true,
          classNamingConvention: 'PascalCase',
          propertyNamingConvention: 'camelCase',
          classNameMap: { order_item: 'LineItem' },
        },
      });
      expect(result.classes).toHaveLength(3);
      expect(result.classes.find((c) => c.originalSchemaKey === 'user_profile')!.name).toBe('UserProfile');
      expect(result.classes.find((c) => c.originalSchemaKey === 'order_item')!.name).toBe('LineItem');
      expect(result.classes.find((c) => c.originalSchemaKey === 'api_error')!.name).toBe('ApiError');
    });

    it('uses smart name when classNameMap omits schema (#754)', () => {
      const document = {
        components: {
          schemas: {
            pet: { type: 'object', title: 'Pet', properties: {} },
            category: { type: 'object', title: 'Category', properties: {} },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['pet', 'category'],
          applyNamingConvention: true,
          classNamingConvention: 'PascalCase',
          propertyNamingConvention: 'camelCase',
          classNameMap: { category: 'Tag' },
        },
      });
      expect(result.classes.find((c) => c.originalSchemaKey === 'pet')!.name).toBe('Pet');
      expect(result.classes.find((c) => c.originalSchemaKey === 'category')!.name).toBe('Tag');
    });

    it('updates $ref by schema key when class name comes from smart name (originalSchemaKey)', () => {
      const document = {
        components: {
          schemas: {
            pet: {
              type: 'object',
              title: 'Pet',
              properties: {
                category: { $ref: '#/components/schemas/category' },
              },
            },
            category: {
              type: 'object',
              title: 'Category',
              properties: { name: { type: 'string' } },
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['pet', 'category'],
          applyNamingConvention: true,
          classNamingConvention: 'PascalCase',
          propertyNamingConvention: 'camelCase',
        },
      });
      const petClass = result.classes.find((c) => c.originalSchemaKey === 'pet')!;
      expect(petClass.name).toBe('Pet');
      const categoryProp = petClass.properties.find((p) => p.name === 'category')!;
      expect(categoryProp.data.$ref).toBe('#/components/schemas/Category');
    });

    it('sets originalSchemaKey on all normalized classes', () => {
      const document = {
        components: {
          schemas: {
            a: { type: 'object', properties: {} },
            b: { type: 'object', title: 'BModel', properties: {} },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['a', 'b'],
          applyNamingConvention: false,
        },
      });
      expect(result.classes.find((c) => c.originalSchemaKey === 'a')).toBeDefined();
      expect(result.classes.find((c) => c.originalSchemaKey === 'b')).toBeDefined();
      expect(result.classes.find((c) => c.originalSchemaKey === 'b')!.name).toBe('BModel');
    });
  });
});

describe('applyNamingConventionToClasses with originalSchemaKey (#753)', () => {
  it('updates $ref by originalSchemaKey when class name differs from key', () => {
    const classes = [
      {
        name: 'Order Item',
        originalSchemaKey: 'order_item',
        properties: [
          {
            name: 'product',
            data: { $ref: '#/components/schemas/product_info' },
            children: [] as any[],
          },
        ],
      },
      {
        name: 'Product Info',
        originalSchemaKey: 'product_info',
        properties: [] as any[],
      },
    ];
    const result = applyNamingConventionToClasses(classes, {
      classNamingConvention: 'PascalCase',
      propertyNamingConvention: 'camelCase',
      applyNamingConvention: true,
    });
    expect(result[0].name).toBe('OrderItem');
    expect(result[1].name).toBe('ProductInfo');
    expect(result[0].properties![0].data.$ref).toBe('#/components/schemas/ProductInfo');
  });
});
