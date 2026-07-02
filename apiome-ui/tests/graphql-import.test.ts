/**
 * GraphQL Import Test Suite
 *
 * Tests the conversion of GraphQL SDL and introspection results to OpenAPI 3.1.x
 * and validates the import functionality.
 */

import { describe, test, expect } from '@jest/globals';
import * as fs from 'fs';
import * as path from 'path';
import {
  convertGraphQLToOpenAPI,
  isGraphQL,
  isGraphQLIntrospection,
  convertGraphQLIntrospectionToOpenAPI
} from '../src/app/utils/graphql-converter';
import { parseOpenAPISpec } from '../src/app/utils/openapi-import';
import { analyzeSpecification, extractFileMetadata } from '../src/app/utils/openapi-analyzer';

// Test configuration
const EXAMPLES_DIR = path.join(__dirname, '../examples/graphql');

/**
 * Load file content as string
 */
function loadFileContent(filePath: string): string {
  return fs.readFileSync(filePath, 'utf-8');
}

/**
 * Get all GraphQL example files
 */
function getExampleFiles(): string[] {
  if (!fs.existsSync(EXAMPLES_DIR)) {
    return [];
  }

  return fs.readdirSync(EXAMPLES_DIR)
    .filter(file => file.endsWith('.graphql') || file.endsWith('.gql'))
    .map(file => path.join(EXAMPLES_DIR, file))
    .sort();
}

describe('GraphQL Import Tests', () => {
  describe('GraphQL Detection', () => {
    test('should detect simple type definition', () => {
      const content = 'type User { id: ID! name: String! }';
      expect(isGraphQL(content)).toBe(true);
    });

    test('should detect input type definition', () => {
      const content = 'input CreateUserInput { name: String! email: String! }';
      expect(isGraphQL(content)).toBe(true);
    });

    test('should detect interface definition', () => {
      const content = 'interface Node { id: ID! }';
      expect(isGraphQL(content)).toBe(true);
    });

    test('should detect enum definition', () => {
      const content = 'enum Status { ACTIVE INACTIVE }';
      expect(isGraphQL(content)).toBe(true);
    });

    test('should detect union definition', () => {
      const content = 'union SearchResult = User | Post';
      expect(isGraphQL(content)).toBe(true);
    });

    test('should detect scalar definition', () => {
      const content = 'scalar DateTime';
      expect(isGraphQL(content)).toBe(true);
    });

    test('should not detect JSON as GraphQL', () => {
      const content = '{"openapi": "3.1.0", "info": {"title": "Test"}}';
      expect(isGraphQL(content)).toBe(false);
    });

    test('should not detect YAML as GraphQL', () => {
      const content = 'openapi: 3.1.0\ninfo:\n  title: Test';
      expect(isGraphQL(content)).toBe(false);
    });

    test('should not detect empty content as GraphQL', () => {
      expect(isGraphQL('')).toBe(false);
      expect(isGraphQL('   ')).toBe(false);
    });

    test('should detect schema block', () => {
      const content = 'schema { query: Query mutation: Mutation }';
      expect(isGraphQL(content)).toBe(true);
    });
  });

  describe('GraphQL Introspection Detection', () => {
    test('should detect introspection result with __schema', () => {
      const doc = {
        __schema: {
          types: []
        }
      };
      expect(isGraphQLIntrospection(doc)).toBe(true);
    });

    test('should detect introspection result with data wrapper', () => {
      const doc = {
        data: {
          __schema: {
            types: []
          }
        }
      };
      expect(isGraphQLIntrospection(doc)).toBe(true);
    });

    test('should not detect regular object as introspection', () => {
      const doc = { type: 'object', properties: {} };
      expect(isGraphQLIntrospection(doc)).toBe(false);
    });

    test('should not detect null as introspection', () => {
      expect(isGraphQLIntrospection(null)).toBe(false);
    });
  });

  describe('Basic GraphQL Conversion', () => {
    test('should convert simple user schema', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '01-simple-user.graphql'));
      const result = convertGraphQLToOpenAPI(content, '01-simple-user.graphql');

      expect(result.success).toBe(true);
      expect(result.document).toBeDefined();
      expect(result.document.openapi).toBe('3.1.0');
    });

    test('should extract User type', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '01-simple-user.graphql'));
      const result = convertGraphQLToOpenAPI(content);

      expect(result.document.components.schemas.User).toBeDefined();
    });

    test('should convert field types correctly', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '01-simple-user.graphql'));
      const result = convertGraphQLToOpenAPI(content);

      const userSchema = result.document.components.schemas.User;
      expect(userSchema.properties.id).toBeDefined();
      expect(userSchema.properties.name).toBeDefined();
      expect(userSchema.properties.email).toBeDefined();
    });

    test('should mark non-null fields as required', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '01-simple-user.graphql'));
      const result = convertGraphQLToOpenAPI(content);

      const userSchema = result.document.components.schemas.User;
      expect(userSchema.required).toContain('id');
      expect(userSchema.required).toContain('name');
      expect(userSchema.required).toContain('email');
    });

    test('should preserve descriptions', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '01-simple-user.graphql'));
      const result = convertGraphQLToOpenAPI(content);

      const userSchema = result.document.components.schemas.User;
      expect(userSchema.description).toContain('simple user type');
    });
  });

  describe('Scalar Types Conversion', () => {
    test('should convert scalar types schema', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '02-scalar-types.graphql'));
      const result = convertGraphQLToOpenAPI(content);

      expect(result.success).toBe(true);
      expect(result.document.components.schemas.Product).toBeDefined();
    });

    test('should map ID to string', () => {
      const content = 'type Test { id: ID! }';
      const result = convertGraphQLToOpenAPI(content);

      const schema = result.document.components.schemas.Test;
      expect(schema.properties.id.type).toBe('string');
    });

    test('should map Int to integer', () => {
      const content = 'type Test { count: Int! }';
      const result = convertGraphQLToOpenAPI(content);

      const schema = result.document.components.schemas.Test;
      expect(schema.properties.count.type).toBe('integer');
    });

    test('should map Float to number', () => {
      const content = 'type Test { value: Float! }';
      const result = convertGraphQLToOpenAPI(content);

      const schema = result.document.components.schemas.Test;
      expect(schema.properties.value.type).toBe('number');
    });

    test('should map Boolean to boolean', () => {
      const content = 'type Test { active: Boolean! }';
      const result = convertGraphQLToOpenAPI(content);

      const schema = result.document.components.schemas.Test;
      expect(schema.properties.active.type).toBe('boolean');
    });

    test('should map String to string', () => {
      const content = 'type Test { name: String! }';
      const result = convertGraphQLToOpenAPI(content);

      const schema = result.document.components.schemas.Test;
      expect(schema.properties.name.type).toBe('string');
    });
  });

  describe('Enum Types Conversion', () => {
    test('should convert enum types', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '03-enum-types.graphql'));
      const result = convertGraphQLToOpenAPI(content);

      expect(result.success).toBe(true);
      expect(result.document.components.schemas.UserRole).toBeDefined();
      expect(result.document.components.schemas.OrderStatus).toBeDefined();
    });

    test('should preserve enum values', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '03-enum-types.graphql'));
      const result = convertGraphQLToOpenAPI(content);

      const roleSchema = result.document.components.schemas.UserRole;
      expect(roleSchema.type).toBe('string');
      expect(roleSchema.enum).toContain('USER');
      expect(roleSchema.enum).toContain('ADMIN');
    });
  });

  describe('Input Types Conversion', () => {
    test('should convert input types', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '04-input-types.graphql'));
      const result = convertGraphQLToOpenAPI(content);

      expect(result.success).toBe(true);
      expect(result.document.components.schemas.CreateUserInput).toBeDefined();
      expect(result.document.components.schemas.UpdateUserInput).toBeDefined();
    });

    test('should convert input type with nested inputs', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '04-input-types.graphql'));
      const result = convertGraphQLToOpenAPI(content);

      const createInput = result.document.components.schemas.CreateUserInput;
      expect(createInput.properties.profile).toBeDefined();
    });
  });

  describe('Interface Types Conversion', () => {
    test('should convert interface types', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '05-interfaces.graphql'));
      const result = convertGraphQLToOpenAPI(content);

      expect(result.success).toBe(true);
      expect(result.document.components.schemas.Node).toBeDefined();
    });

    test('should mark interfaces with x-graphql-interface', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '05-interfaces.graphql'));
      const result = convertGraphQLToOpenAPI(content);

      const nodeSchema = result.document.components.schemas.Node;
      expect(nodeSchema['x-graphql-interface']).toBe(true);
    });

    test('should handle types implementing interfaces', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '05-interfaces.graphql'));
      const result = convertGraphQLToOpenAPI(content);

      const postSchema = result.document.components.schemas.Post;
      expect(postSchema.allOf).toBeDefined();
      expect(postSchema.allOf.some((a: any) => a.$ref === '#/components/schemas/Node')).toBe(true);
    });
  });

  describe('Union Types Conversion', () => {
    test('should convert union types', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '06-union-types.graphql'));
      const result = convertGraphQLToOpenAPI(content);

      expect(result.success).toBe(true);
      expect(result.document.components.schemas.SearchResult).toBeDefined();
    });

    test('should use oneOf for union types', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '06-union-types.graphql'));
      const result = convertGraphQLToOpenAPI(content);

      const unionSchema = result.document.components.schemas.SearchResult;
      expect(unionSchema.oneOf).toBeDefined();
      expect(unionSchema.oneOf.length).toBeGreaterThan(0);
    });
  });

  describe('Nested Types Conversion', () => {
    test('should convert nested types', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '07-nested-types.graphql'));
      const result = convertGraphQLToOpenAPI(content);

      expect(result.success).toBe(true);
      expect(result.document.components.schemas.Company).toBeDefined();
      expect(result.document.components.schemas.Department).toBeDefined();
      expect(result.document.components.schemas.Employee).toBeDefined();
    });

    test('should handle type references', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '07-nested-types.graphql'));
      const result = convertGraphQLToOpenAPI(content);

      const companySchema = result.document.components.schemas.Company;
      expect(companySchema.properties.headquarters.$ref).toBe('#/components/schemas/Address');
    });

    test('should handle array types', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '07-nested-types.graphql'));
      const result = convertGraphQLToOpenAPI(content);

      const companySchema = result.document.components.schemas.Company;
      expect(companySchema.properties.departments.type).toBe('array');
      expect(companySchema.properties.departments.items.$ref).toBe('#/components/schemas/Department');
    });
  });

  describe('Arguments and Defaults', () => {
    test('should convert types with arguments', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '08-arguments-defaults.graphql'));
      const result = convertGraphQLToOpenAPI(content);

      expect(result.success).toBe(true);
    });

    test('should store arguments in x-graphql-arguments', () => {
      const content = 'type User { posts(limit: Int = 10, offset: Int): [Post!]! }';
      const result = convertGraphQLToOpenAPI(content);

      const userSchema = result.document.components.schemas.User;
      const postsField = userSchema.properties.posts;
      expect(postsField['x-graphql-arguments']).toBeDefined();
    });
  });

  describe('Custom Scalars', () => {
    test('should convert custom scalars', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '09-custom-scalars.graphql'));
      const result = convertGraphQLToOpenAPI(content);

      expect(result.success).toBe(true);
    });

    test('should map known scalars correctly', () => {
      const content = 'scalar DateTime\ntype Test { date: DateTime! }';
      const result = convertGraphQLToOpenAPI(content);

      const testSchema = result.document.components.schemas.Test;
      expect(testSchema.properties.date.format).toBe('date-time');
    });

    test('should mark unknown scalars with x-graphql-scalar', () => {
      const content = 'scalar CustomType\ntype Test { value: CustomType! }';
      const result = convertGraphQLToOpenAPI(content);

      expect(result.warnings.some(w => w.includes('CustomType'))).toBe(true);
    });
  });

  describe('Comprehensive E-Commerce Schema', () => {
    test('should convert comprehensive schema', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '10-comprehensive-ecommerce.graphql'));
      const result = convertGraphQLToOpenAPI(content);

      expect(result.success).toBe(true);
      expect(Object.keys(result.document.components.schemas).length).toBeGreaterThan(20);
    });

    test('should convert all major types', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '10-comprehensive-ecommerce.graphql'));
      const result = convertGraphQLToOpenAPI(content);

      expect(result.document.components.schemas.User).toBeDefined();
      expect(result.document.components.schemas.Product).toBeDefined();
      expect(result.document.components.schemas.Order).toBeDefined();
      expect(result.document.components.schemas.Cart).toBeDefined();
    });

    test('should convert enums', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '10-comprehensive-ecommerce.graphql'));
      const result = convertGraphQLToOpenAPI(content);

      expect(result.document.components.schemas.OrderStatus).toBeDefined();
      expect(result.document.components.schemas.UserRole).toBeDefined();
    });

    test('should convert interfaces', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '10-comprehensive-ecommerce.graphql'));
      const result = convertGraphQLToOpenAPI(content);

      expect(result.document.components.schemas.Node).toBeDefined();
    });

    test('should convert unions', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '10-comprehensive-ecommerce.graphql'));
      const result = convertGraphQLToOpenAPI(content);

      expect(result.document.components.schemas.PaymentMethod).toBeDefined();
    });

    test('should convert input types', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '10-comprehensive-ecommerce.graphql'));
      const result = convertGraphQLToOpenAPI(content);

      expect(result.document.components.schemas.CreateUserInput).toBeDefined();
      expect(result.document.components.schemas.AddressInput).toBeDefined();
    });
  });

  describe('OpenAPI Analyzer with GraphQL', () => {
    test('should analyze GraphQL specification', async () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '01-simple-user.graphql'));
      const result = await analyzeSpecification(content, '01-simple-user.graphql');

      expect(result.syntaxValid).toBe(true);
      expect(result.isValid).toBe(true);
    });

    test('should detect GraphQL syntax', async () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '01-simple-user.graphql'));
      const result = await analyzeSpecification(content, '01-simple-user.graphql');

      // After conversion it should be openapi
      expect(result.format).toBe('openapi');
    });

    test('should count schemas correctly', async () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '03-enum-types.graphql'));
      const result = await analyzeSpecification(content, '03-enum-types.graphql');

      expect(result.metrics.schemaCount).toBeGreaterThan(0);
    });
  });

  describe('File Metadata Extraction', () => {
    test('should extract metadata from GraphQL file', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '01-simple-user.graphql'));
      const metadata = extractFileMetadata(content);

      expect(metadata.syntaxValid).toBe(true);
      expect(metadata.syntax).toBe('graphql');
      expect(metadata.format).toBe('graphql');
      expect(metadata.formatSupported).toBe(true);
    });
  });

  describe('OpenAPI Import with GraphQL', () => {
    test('should parse simple GraphQL schema successfully', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '01-simple-user.graphql'));
      const result = parseOpenAPISpec(content);

      expect(result.success).toBe(true);
      expect(result.classes.length).toBeGreaterThan(0);
    });

    test('should extract types as classes', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '01-simple-user.graphql'));
      const result = parseOpenAPISpec(content);

      const userClass = result.classes.find(c => c.name === 'User');
      expect(userClass).toBeDefined();
    });

    test('should extract properties from types', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '01-simple-user.graphql'));
      const result = parseOpenAPISpec(content);

      const userClass = result.classes.find(c => c.name === 'User');
      expect(userClass).toBeDefined();

      const propNames = userClass!.properties.map(p => p.name);
      expect(propNames).toContain('id');
      expect(propNames).toContain('name');
      expect(propNames).toContain('email');
    });

    test('should include conversion info in warnings', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '01-simple-user.graphql'));
      const result = parseOpenAPISpec(content);

      const hasConversionInfo = result.warnings.some(w =>
        w.toLowerCase().includes('graphql') || w.toLowerCase().includes('convert')
      );
      expect(hasConversionInfo).toBe(true);
    });

    test('should parse comprehensive e-commerce schema', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '10-comprehensive-ecommerce.graphql'));
      const result = parseOpenAPISpec(content);

      expect(result.success).toBe(true);
      expect(result.classes.length).toBeGreaterThan(20);

      const classNames = result.classes.map(c => c.name);
      expect(classNames).toContain('User');
      expect(classNames).toContain('Product');
      expect(classNames).toContain('Order');
    });
  });

  describe('All Example Files Validation', () => {
    test('should have GraphQL example files', () => {
      const files = getExampleFiles();
      expect(files.length).toBeGreaterThanOrEqual(10);
    });

    test('should convert all example files successfully', () => {
      const files = getExampleFiles();
      const failures: string[] = [];

      for (const file of files) {
        const content = loadFileContent(file);
        const result = convertGraphQLToOpenAPI(content, path.basename(file));

        if (!result.success) {
          failures.push(`${path.basename(file)}: ${result.error}`);
        }
      }

      if (failures.length > 0) {
        console.error('Conversion failures:', failures);
      }
      expect(failures.length).toBe(0);
    });

    test('should parse all example files with parseOpenAPISpec', () => {
      const files = getExampleFiles();
      const failures: string[] = [];

      for (const file of files) {
        const content = loadFileContent(file);
        const result = parseOpenAPISpec(content);

        if (!result.success) {
          failures.push(`${path.basename(file)}: ${result.error}`);
        }
      }

      if (failures.length > 0) {
        console.error('Parse failures:', failures);
      }
      expect(failures.length).toBe(0);
    });

    test('should analyze all example files successfully', async () => {
      const files = getExampleFiles();
      const failures: string[] = [];

      for (const file of files) {
        const content = loadFileContent(file);
        const result = await analyzeSpecification(content, path.basename(file));

        if (!result.isValid) {
          failures.push(`${path.basename(file)}: ${result.errors.map(e => e.message).join(', ')}`);
        }
      }

      if (failures.length > 0) {
        console.error('Analysis failures:', failures);
      }
      expect(failures.length).toBe(0);
    });
  });

  describe('Edge Cases', () => {
    test('should handle empty content', () => {
      const result = convertGraphQLToOpenAPI('');
      expect(result.success).toBe(false);
      expect(result.error).toBeDefined();
    });

    test('should handle null content', () => {
      const result = convertGraphQLToOpenAPI(null as any);
      expect(result.success).toBe(false);
    });

    test('should handle content with only comments', () => {
      const result = convertGraphQLToOpenAPI('# This is a comment\n# Another comment');
      expect(result.success).toBe(false);
      expect(result.error).toContain('No type definitions found');
    });

    test('should skip Query/Mutation/Subscription types', () => {
      const content = `
        type Query { users: [User!]! }
        type Mutation { createUser(name: String!): User! }
        type Subscription { userCreated: User! }
        type User { id: ID! name: String! }
      `;
      const result = convertGraphQLToOpenAPI(content);

      expect(result.success).toBe(true);
      expect(result.document.components.schemas.Query).toBeUndefined();
      expect(result.document.components.schemas.Mutation).toBeUndefined();
      expect(result.document.components.schemas.Subscription).toBeUndefined();
      expect(result.document.components.schemas.User).toBeDefined();
    });

    test('should handle nullable list items', () => {
      const content = 'type Test { items: [String]! }';
      const result = convertGraphQLToOpenAPI(content);

      const schema = result.document.components.schemas.Test;
      expect(schema.properties.items.type).toBe('array');
      expect(schema.required).toContain('items');
    });

    test('should handle nullable list', () => {
      const content = 'type Test { items: [String!] }';
      const result = convertGraphQLToOpenAPI(content);

      const schema = result.document.components.schemas.Test;
      expect(schema.properties.items.type).toBe('array');
      // Required array might be undefined if there are no required fields
      if (schema.required) {
        expect(schema.required).not.toContain('items');
      }
    });

    test('should derive title from filename', () => {
      const content = 'type User { id: ID! }';
      const result = convertGraphQLToOpenAPI(content, 'my-awesome-api.graphql');

      expect(result.document.info.title).toBe('My Awesome Api');
    });
  });

  describe('GraphQL Introspection Conversion', () => {
    test('should convert simple introspection result', () => {
      const introspection = {
        __schema: {
          types: [
            {
              kind: 'OBJECT',
              name: 'User',
              description: 'A user',
              fields: [
                { name: 'id', type: { kind: 'NON_NULL', ofType: { kind: 'SCALAR', name: 'ID' } } },
                { name: 'name', type: { kind: 'SCALAR', name: 'String' } }
              ]
            }
          ]
        }
      };

      const result = convertGraphQLIntrospectionToOpenAPI(introspection);

      expect(result.success).toBe(true);
      expect(result.document.components.schemas.User).toBeDefined();
    });

    test('should handle data wrapper', () => {
      const introspection = {
        data: {
          __schema: {
            types: [
              {
                kind: 'OBJECT',
                name: 'Test',
                fields: [
                  { name: 'value', type: { kind: 'SCALAR', name: 'String' } }
                ]
              }
            ]
          }
        }
      };

      const result = convertGraphQLIntrospectionToOpenAPI(introspection);

      expect(result.success).toBe(true);
      expect(result.document.components.schemas.Test).toBeDefined();
    });

    test('should convert enum from introspection', () => {
      const introspection = {
        __schema: {
          types: [
            {
              kind: 'ENUM',
              name: 'Status',
              enumValues: [
                { name: 'ACTIVE' },
                { name: 'INACTIVE' }
              ]
            }
          ]
        }
      };

      const result = convertGraphQLIntrospectionToOpenAPI(introspection);

      expect(result.success).toBe(true);
      expect(result.document.components.schemas.Status.enum).toContain('ACTIVE');
      expect(result.document.components.schemas.Status.enum).toContain('INACTIVE');
    });

    test('should skip built-in types in introspection', () => {
      const introspection = {
        __schema: {
          types: [
            { kind: 'OBJECT', name: '__Schema', fields: [] },
            { kind: 'OBJECT', name: '__Type', fields: [] },
            { kind: 'OBJECT', name: 'User', fields: [{ name: 'id', type: { kind: 'SCALAR', name: 'ID' } }] }
          ]
        }
      };

      const result = convertGraphQLIntrospectionToOpenAPI(introspection);

      expect(result.success).toBe(true);
      expect(result.document.components.schemas.__Schema).toBeUndefined();
      expect(result.document.components.schemas.__Type).toBeUndefined();
      expect(result.document.components.schemas.User).toBeDefined();
    });
  });
});

