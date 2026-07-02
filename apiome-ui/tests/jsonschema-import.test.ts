/**
 * JSON Schema Import Test Suite
 *
 * Tests the conversion of JSON Schema documents to OpenAPI 3.1.x
 * and validates the import functionality.
 */

import { describe, test, expect } from '@jest/globals';
import * as fs from 'fs';
import * as path from 'path';
import {
  convertJsonSchemaToOpenAPI,
  isJsonSchema,
  getJsonSchemaVersion,
  inferSchemaType
} from '../src/app/utils/jsonschema-converter';
import { parseOpenAPISpec } from '../src/app/utils/openapi-import';
import { analyzeSpecification, extractFileMetadata } from '../src/app/utils/openapi-analyzer';

// Test configuration
const EXAMPLES_DIR = path.join(__dirname, '../examples/json-schema');

/**
 * Load a JSON file and parse it
 */
function loadJsonFile(filePath: string): any {
  const content = fs.readFileSync(filePath, 'utf-8');
  return JSON.parse(content);
}

/**
 * Load file content as string
 */
function loadFileContent(filePath: string): string {
  return fs.readFileSync(filePath, 'utf-8');
}

/**
 * Get all JSON Schema example files
 */
function getExampleFiles(): string[] {
  if (!fs.existsSync(EXAMPLES_DIR)) {
    return [];
  }

  return fs.readdirSync(EXAMPLES_DIR)
    .filter(file => file.endsWith('.json'))
    .map(file => path.join(EXAMPLES_DIR, file))
    .sort();
}

describe('JSON Schema Import Tests', () => {
  describe('JSON Schema Detection', () => {
    test('should detect JSON Schema with $schema field', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '01-simple-person.json'));
      expect(isJsonSchema(doc)).toBe(true);
    });

    test('should detect JSON Schema version', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '01-simple-person.json'));
      const version = getJsonSchemaVersion(doc);
      expect(version).toBe('draft-2020-12');
    });

    test('should detect draft-07 version', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '04-draft07-definitions.json'));
      const version = getJsonSchemaVersion(doc);
      expect(version).toBe('draft-07');
    });

    test('should not detect OpenAPI as JSON Schema', () => {
      const openApiDoc = {
        openapi: '3.1.0',
        info: { title: 'Test', version: '1.0.0' }
      };
      expect(isJsonSchema(openApiDoc)).toBe(false);
    });

    test('should not detect Swagger as JSON Schema', () => {
      const swaggerDoc = {
        swagger: '2.0',
        info: { title: 'Test', version: '1.0.0' }
      };
      expect(isJsonSchema(swaggerDoc)).toBe(false);
    });

    test('should detect schema-like document without $schema', () => {
      const doc = {
        type: 'object',
        properties: {
          name: { type: 'string' }
        }
      };
      expect(isJsonSchema(doc)).toBe(true);
    });

    test('should not detect empty object as JSON Schema', () => {
      expect(isJsonSchema({})).toBe(false);
    });

    test('should return null version for document without $schema', () => {
      const doc = { type: 'object' };
      expect(getJsonSchemaVersion(doc)).toBeNull();
    });
  });

  describe('Schema Type Inference', () => {
    test('should infer object type from properties', () => {
      const schema = { properties: { name: { type: 'string' } } };
      expect(inferSchemaType(schema)).toBe('object');
    });

    test('should infer array type from items', () => {
      const schema = { items: { type: 'string' } };
      expect(inferSchemaType(schema)).toBe('array');
    });

    test('should infer number type from numeric constraints', () => {
      const schema = { minimum: 0, maximum: 100 };
      expect(inferSchemaType(schema)).toBe('number');
    });

    test('should infer string type from string constraints', () => {
      const schema = { minLength: 1, pattern: '^[a-z]+$' };
      expect(inferSchemaType(schema)).toBe('string');
    });

    test('should return explicit type', () => {
      const schema = { type: 'boolean' };
      expect(inferSchemaType(schema)).toBe('boolean');
    });

    test('should return first type from array', () => {
      const schema = { type: ['string', 'null'] };
      expect(inferSchemaType(schema)).toBe('string');
    });
  });

  describe('Basic JSON Schema Conversion', () => {
    test('should convert simple person schema', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '01-simple-person.json'));
      const result = convertJsonSchemaToOpenAPI(doc, '01-simple-person.json');

      expect(result.success).toBe(true);
      expect(result.document).toBeDefined();
      expect(result.document.openapi).toBe('3.1.0');
    });

    test('should extract title from schema', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '01-simple-person.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      expect(result.document.info.title).toBe('Person');
    });

    test('should convert root schema to components/schemas', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '01-simple-person.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      expect(result.document.components.schemas).toBeDefined();
      expect(result.document.components.schemas.Person).toBeDefined();
    });

    test('should preserve properties in converted schema', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '01-simple-person.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      const personSchema = result.document.components.schemas.Person;
      expect(personSchema.properties).toBeDefined();
      expect(personSchema.properties.firstName).toBeDefined();
      expect(personSchema.properties.lastName).toBeDefined();
      expect(personSchema.properties.age).toBeDefined();
      expect(personSchema.properties.email).toBeDefined();
    });

    test('should preserve required array', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '01-simple-person.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      const personSchema = result.document.components.schemas.Person;
      expect(personSchema.required).toContain('firstName');
      expect(personSchema.required).toContain('lastName');
    });
  });

  describe('Product Schema with Various Types', () => {
    test('should convert product schema with nested objects', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '02-product-types.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      expect(result.success).toBe(true);
      const productSchema = result.document.components.schemas.Product;
      expect(productSchema.properties.dimensions).toBeDefined();
      expect(productSchema.properties.dimensions.type).toBe('object');
    });

    test('should preserve array type with items', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '02-product-types.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      const productSchema = result.document.components.schemas.Product;
      expect(productSchema.properties.tags.type).toBe('array');
      expect(productSchema.properties.tags.items.type).toBe('string');
    });

    test('should preserve enum values', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '02-product-types.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      const productSchema = result.document.components.schemas.Product;
      expect(productSchema.properties.category.enum).toContain('electronics');
      expect(productSchema.properties.category.enum).toContain('clothing');
    });

    test('should preserve numeric constraints', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '02-product-types.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      const productSchema = result.document.components.schemas.Product;
      expect(productSchema.properties.price.minimum).toBe(0);
      expect(productSchema.properties.price.exclusiveMinimum).toBe(0);
    });
  });

  describe('Multiple Definitions ($defs)', () => {
    test('should convert all $defs to schemas', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '03-multiple-defs.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      expect(result.success).toBe(true);
      expect(result.document.components.schemas.Contact).toBeDefined();
      expect(result.document.components.schemas.PersonName).toBeDefined();
      expect(result.document.components.schemas.Address).toBeDefined();
      expect(result.document.components.schemas.PhoneNumber).toBeDefined();
    });

    test('should convert $ref paths from $defs to components/schemas', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '03-multiple-defs.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      const contactSchema = result.document.components.schemas.Contact;
      expect(contactSchema.properties.name.$ref).toBe('#/components/schemas/PersonName');
      expect(contactSchema.properties.address.$ref).toBe('#/components/schemas/Address');
    });

    test('should handle array items with $ref', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '03-multiple-defs.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      const contactSchema = result.document.components.schemas.Contact;
      expect(contactSchema.properties.phones.items.$ref).toBe('#/components/schemas/PhoneNumber');
    });
  });

  describe('Draft-07 with definitions', () => {
    test('should convert definitions to schemas', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '04-draft07-definitions.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      expect(result.success).toBe(true);
      expect(result.document.components.schemas.Customer).toBeDefined();
      expect(result.document.components.schemas.OrderItem).toBeDefined();
      expect(result.document.components.schemas.Address).toBeDefined();
      expect(result.document.components.schemas.OrderStatus).toBeDefined();
    });

    test('should convert #/definitions/ refs to #/components/schemas/', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '04-draft07-definitions.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      const orderSchema = result.document.components.schemas.Order;
      expect(orderSchema.properties.customer.$ref).toBe('#/components/schemas/Customer');
      expect(orderSchema.properties.shippingAddress.$ref).toBe('#/components/schemas/Address');
    });
  });

  describe('allOf Inheritance', () => {
    test('should preserve allOf composition', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '05-allof-inheritance.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      expect(result.success).toBe(true);
      expect(result.document.components.schemas.Car).toBeDefined();
      expect(result.document.components.schemas.Car.allOf).toBeDefined();
    });

    test('should convert refs in allOf', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '05-allof-inheritance.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      const carSchema = result.document.components.schemas.Car;
      expect(carSchema.allOf[0].$ref).toBe('#/components/schemas/VehicleBase');
    });

    test('should preserve base schema', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '05-allof-inheritance.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      expect(result.document.components.schemas.VehicleBase).toBeDefined();
      expect(result.document.components.schemas.VehicleBase.properties.manufacturer).toBeDefined();
    });
  });

  describe('oneOf Polymorphism', () => {
    test('should preserve oneOf composition', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '06-oneof-polymorphism.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      expect(result.success).toBe(true);
      expect(result.document.components.schemas.PaymentMethod).toBeDefined();
      expect(result.document.components.schemas.PaymentMethod.oneOf).toBeDefined();
      expect(result.document.components.schemas.PaymentMethod.oneOf.length).toBe(4);
    });

    test('should convert all payment method types', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '06-oneof-polymorphism.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      expect(result.document.components.schemas.CreditCard).toBeDefined();
      expect(result.document.components.schemas.BankTransfer).toBeDefined();
      expect(result.document.components.schemas.PayPal).toBeDefined();
      expect(result.document.components.schemas.Cryptocurrency).toBeDefined();
    });

    test('should preserve const values', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '06-oneof-polymorphism.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      const creditCardSchema = result.document.components.schemas.CreditCard;
      expect(creditCardSchema.properties.type.const).toBe('credit_card');
    });
  });

  describe('anyOf Flexible Validation', () => {
    test('should preserve anyOf composition', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '07-anyof-flexible.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      expect(result.success).toBe(true);
      expect(result.document.components.schemas.DatabaseConfig).toBeDefined();
      expect(result.document.components.schemas.DatabaseConfig.anyOf).toBeDefined();
    });

    test('should convert all database config types', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '07-anyof-flexible.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      expect(result.document.components.schemas.PostgresConfig).toBeDefined();
      expect(result.document.components.schemas.MySQLConfig).toBeDefined();
      expect(result.document.components.schemas.MongoDBConfig).toBeDefined();
      expect(result.document.components.schemas.SQLiteConfig).toBeDefined();
    });
  });

  describe('if-then-else Conditionals', () => {
    test('should preserve if-then-else structure', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '08-if-then-else.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      expect(result.success).toBe(true);
      const addressSchema = result.document.components.schemas.InternationalAddress;
      expect(addressSchema.if).toBeDefined();
      expect(addressSchema.then).toBeDefined();
      expect(addressSchema.else).toBeDefined();
    });

    test('should preserve nested if-then-else', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '08-if-then-else.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      const addressSchema = result.document.components.schemas.InternationalAddress;
      expect(addressSchema.else.if).toBeDefined();
      expect(addressSchema.else.then).toBeDefined();
    });

    test('should preserve allOf with multiple if-then conditions', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '08-if-then-else.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      const formSchema = result.document.components.schemas.EmploymentForm;
      expect(formSchema.allOf).toBeDefined();
      expect(formSchema.allOf.length).toBeGreaterThan(0);
    });
  });

  describe('Advanced Features', () => {
    test('should convert prefixItems (tuple validation)', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '09-advanced-features.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      expect(result.success).toBe(true);
      const tupleSchema = result.document.components.schemas.TupleExample;
      expect(tupleSchema.properties.coordinates.prefixItems).toBeDefined();
      expect(tupleSchema.properties.coordinates.prefixItems.length).toBe(3);
    });

    test('should preserve patternProperties', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '09-advanced-features.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      const patternSchema = result.document.components.schemas.PatternPropertiesExample;
      expect(patternSchema.patternProperties).toBeDefined();
      expect(patternSchema.patternProperties['^attr_']).toBeDefined();
    });

    test('should preserve contains with minContains/maxContains', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '09-advanced-features.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      const containsSchema = result.document.components.schemas.ContainsExample;
      expect(containsSchema.properties.mixedArray.contains).toBeDefined();
      expect(containsSchema.properties.mixedArray.minContains).toBe(1);
      expect(containsSchema.properties.mixedArray.maxContains).toBe(3);
    });

    test('should convert dependentRequired and dependentSchemas', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '09-advanced-features.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      const depSchema = result.document.components.schemas.DependentSchemasExample;
      expect(depSchema.dependentRequired).toBeDefined();
      expect(depSchema.dependentRequired.creditCard).toContain('cvv');
      expect(depSchema.dependentSchemas).toBeDefined();
    });

    test('should preserve propertyNames validation', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '09-advanced-features.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      const propNamesSchema = result.document.components.schemas.PropertyNamesExample;
      expect(propNamesSchema.propertyNames).toBeDefined();
      expect(propNamesSchema.propertyNames.pattern).toBeDefined();
    });

    test('should handle recursive schemas', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '09-advanced-features.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      const recursiveSchema = result.document.components.schemas.RecursiveSchema;
      expect(recursiveSchema.properties.children.items.$ref).toBe('#/components/schemas/RecursiveSchema');
    });

    test('should preserve nullable types', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '09-advanced-features.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      const nullableSchema = result.document.components.schemas.NullableTypes;
      expect(nullableSchema.properties.nullableString.type).toEqual(['string', 'null']);
    });
  });

  describe('Comprehensive E-Commerce Schema', () => {
    test('should convert all e-commerce schemas', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '10-comprehensive-ecommerce.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      expect(result.success).toBe(true);
      expect(result.document.components.schemas.Product).toBeDefined();
      expect(result.document.components.schemas.Category).toBeDefined();
      expect(result.document.components.schemas.Customer).toBeDefined();
      expect(result.document.components.schemas.Order).toBeDefined();
      expect(result.document.components.schemas.Cart).toBeDefined();
    });

    test('should preserve allOf inheritance for entities', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '10-comprehensive-ecommerce.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      const productSchema = result.document.components.schemas.Product;
      expect(productSchema.allOf).toBeDefined();
      expect(productSchema.allOf[0].$ref).toBe('#/components/schemas/BaseEntity');
    });

    test('should convert Money and Timestamp helper schemas', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '10-comprehensive-ecommerce.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      expect(result.document.components.schemas.Money).toBeDefined();
      expect(result.document.components.schemas.Timestamp).toBeDefined();
    });

    test('should count all schemas correctly', () => {
      const doc = loadJsonFile(path.join(EXAMPLES_DIR, '10-comprehensive-ecommerce.json'));
      const result = convertJsonSchemaToOpenAPI(doc);

      const schemaCount = Object.keys(result.document.components.schemas).length;
      expect(schemaCount).toBeGreaterThanOrEqual(15);
    });
  });

  describe('OpenAPI Analyzer with JSON Schema', () => {
    test('should analyze JSON Schema specification', async () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '01-simple-person.json'));
      const result = await analyzeSpecification(content, '01-simple-person.json');

      expect(result.isValid).toBe(true);
      expect(result.formatSupported).toBe(true);
      expect(result.syntaxValid).toBe(true);
    });

    test('should detect format as openapi after conversion', async () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '01-simple-person.json'));
      const result = await analyzeSpecification(content, '01-simple-person.json');

      // After conversion, it should be detected as openapi 3.1.0
      expect(result.format).toBe('openapi');
      expect(result.version).toBe('3.1.0');
    });

    test('should count schemas correctly for multi-def file', async () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '03-multiple-defs.json'));
      const result = await analyzeSpecification(content, '03-multiple-defs.json');

      // Should have Contact, PersonName, Address, PhoneNumber, and root schema
      expect(result.metrics.schemaCount).toBeGreaterThanOrEqual(4);
    });

    test('should have conversion info in warnings', async () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '01-simple-person.json'));
      const result = await analyzeSpecification(content, '01-simple-person.json');

      // Should have some conversion-related warnings
      expect(result.warnings.some(w => w.message.includes('JSON Schema'))).toBe(true);
    });
  });

  describe('File Metadata Extraction', () => {
    test('should extract metadata from JSON Schema file', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '01-simple-person.json'));
      const metadata = extractFileMetadata(content);

      expect(metadata.syntaxValid).toBe(true);
      expect(metadata.syntax).toBe('json');
      expect(metadata.format).toBe('jsonschema');
      expect(metadata.formatSupported).toBe(true);
    });

    test('should extract title', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '01-simple-person.json'));
      const metadata = extractFileMetadata(content);

      expect(metadata.title).toBe('Person');
    });
  });

  describe('OpenAPI Import with JSON Schema', () => {
    test('should parse simple JSON Schema successfully', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '01-simple-person.json'));
      const result = parseOpenAPISpec(content);

      expect(result.success).toBe(true);
      expect(result.classes.length).toBeGreaterThan(0);
    });

    test('should extract schema as class', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '01-simple-person.json'));
      const result = parseOpenAPISpec(content);

      const personClass = result.classes.find(c => c.name === 'Person');
      expect(personClass).toBeDefined();
    });

    test('should extract properties from schema', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '01-simple-person.json'));
      const result = parseOpenAPISpec(content);

      const personClass = result.classes.find(c => c.name === 'Person');
      expect(personClass).toBeDefined();

      const propNames = personClass!.properties.map(p => p.name);
      expect(propNames).toContain('firstName');
      expect(propNames).toContain('lastName');
      expect(propNames).toContain('age');
      expect(propNames).toContain('email');
    });

    test('should parse multiple $defs as separate classes', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '03-multiple-defs.json'));
      const result = parseOpenAPISpec(content);

      expect(result.success).toBe(true);

      const classNames = result.classes.map(c => c.name);
      expect(classNames).toContain('Contact');
      expect(classNames).toContain('PersonName');
      expect(classNames).toContain('Address');
      expect(classNames).toContain('PhoneNumber');
    });

    test('should include conversion info in warnings', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '01-simple-person.json'));
      const result = parseOpenAPISpec(content);

      const hasConversionInfo = result.warnings.some(w =>
        w.toLowerCase().includes('json schema') || w.toLowerCase().includes('convert')
      );
      expect(hasConversionInfo).toBe(true);
    });

    test('should parse comprehensive e-commerce schema', () => {
      const content = loadFileContent(path.join(EXAMPLES_DIR, '10-comprehensive-ecommerce.json'));
      const result = parseOpenAPISpec(content);

      expect(result.success).toBe(true);
      expect(result.classes.length).toBeGreaterThanOrEqual(15);

      const classNames = result.classes.map(c => c.name);
      expect(classNames).toContain('Product');
      expect(classNames).toContain('Category');
      expect(classNames).toContain('Customer');
      expect(classNames).toContain('Order');
    });
  });

  describe('All Example Files Validation', () => {
    test('should have JSON Schema example files', () => {
      const files = getExampleFiles();
      expect(files.length).toBeGreaterThanOrEqual(10);
    });

    test('should convert all example files successfully', () => {
      const files = getExampleFiles();
      const failures: string[] = [];

      for (const file of files) {
        const doc = loadJsonFile(file);
        const result = convertJsonSchemaToOpenAPI(doc, path.basename(file));

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
    test('should handle schema without $schema field', () => {
      const doc = {
        type: 'object',
        properties: {
          name: { type: 'string' }
        }
      };

      const result = convertJsonSchemaToOpenAPI(doc, 'test.json');
      expect(result.success).toBe(true);
      expect(result.document.components.schemas.Test).toBeDefined();
    });

    test('should handle boolean exclusiveMinimum (draft-04 style)', () => {
      const doc = {
        $schema: 'http://json-schema.org/draft-04/schema#',
        type: 'number',
        minimum: 0,
        exclusiveMinimum: true
      };

      const result = convertJsonSchemaToOpenAPI(doc);
      expect(result.success).toBe(true);
      // Should be converted to numeric exclusiveMinimum
      const schema = Object.values(result.document.components.schemas)[0] as any;
      expect(schema.exclusiveMinimum).toBe(0);
      expect(schema.minimum).toBeUndefined();
    });

    test('should handle empty document', () => {
      const result = convertJsonSchemaToOpenAPI({});
      expect(result.success).toBe(false);
      expect(result.error).toContain('No schemas found');
    });

    test('should handle null document', () => {
      const result = convertJsonSchemaToOpenAPI(null);
      expect(result.success).toBe(false);
      expect(result.error).toContain('Invalid JSON Schema');
    });

    test('should derive schema name from filename', () => {
      const doc = { type: 'object' };
      const result = convertJsonSchemaToOpenAPI(doc, 'my-custom-schema.json');
      expect(result.success).toBe(true);
      expect(result.document.components.schemas.MyCustomSchema).toBeDefined();
    });

    test('should use $id for schema name if available', () => {
      const doc = {
        $id: 'https://example.com/widgets/fancy-widget.json',
        type: 'object',
        properties: {
          id: { type: 'string' }
        }
      };
      const result = convertJsonSchemaToOpenAPI(doc);
      expect(result.success).toBe(true);
      expect(result.document.components.schemas.FancyWidget).toBeDefined();
    });

    test('should handle tuple items conversion', () => {
      const doc = {
        type: 'array',
        items: [
          { type: 'string' },
          { type: 'number' }
        ]
      };
      const result = convertJsonSchemaToOpenAPI(doc);
      expect(result.success).toBe(true);
      const schema = Object.values(result.document.components.schemas)[0] as any;
      expect(schema.prefixItems).toBeDefined();
      expect(schema.prefixItems.length).toBe(2);
    });

    test('should handle additionalItems conversion', () => {
      const doc = {
        type: 'array',
        items: [
          { type: 'string' }
        ],
        additionalItems: { type: 'number' }
      };
      const result = convertJsonSchemaToOpenAPI(doc);
      expect(result.success).toBe(true);
      const schema = Object.values(result.document.components.schemas)[0] as any;
      expect(schema.prefixItems).toBeDefined();
      expect(schema.items).toBeDefined();
      expect(schema.items.type).toBe('number');
    });

    test('should convert single example in examples array', () => {
      const doc = {
        type: 'string',
        examples: ['hello']
      };
      const result = convertJsonSchemaToOpenAPI(doc);
      expect(result.success).toBe(true);
      const schema = Object.values(result.document.components.schemas)[0] as any;
      expect(schema.example).toBe('hello');
      expect(schema.examples).toBeUndefined();
    });
  });
});

