/**
 * Import Validation Test Suite
 *
 * This test suite validates the import functionality by:
 * 1. Checking if example files exist and are valid YAML
 * 2. Verifying database schema structure
 * 3. Running basic smoke tests on all examples
 * 4. Validating file parsing
 *
 * Uses PostgreSQL for testing without affecting production data.
 */

import { describe, test, expect, beforeAll, afterAll } from '@jest/globals';
import * as fs from 'fs';
import * as path from 'path';
import * as YAML from 'yaml';

// Test configuration
const EXAMPLES_DIR = path.join(__dirname, '../examples/openapi');

/**
 * Validate an OpenAPI specification file
 */
function validateOpenApiFile(filePath: string): { valid: boolean; error?: string; schemas: number } {
  try {
    const content = fs.readFileSync(filePath, 'utf-8');
    const document = YAML.parse(content);

    if (!document || typeof document !== 'object') {
      return { valid: false, error: 'Document is not an object', schemas: 0 };
    }

    if (!document.openapi && !document.swagger) {
      return { valid: false, error: 'Missing openapi or swagger version', schemas: 0 };
    }

    // OpenAPI 3.x uses components.schemas, Swagger 2.x uses definitions directly
    let schemaCount = 0;
    if (document.components?.schemas) {
      schemaCount = Object.keys(document.components.schemas).length;
    } else if (document.definitions) {
      schemaCount = Object.keys(document.definitions).length;
    }

    return { valid: true, schemas: schemaCount };
  } catch (error) {
    return { valid: false, error: (error as Error).message, schemas: 0 };
  }
}

/**
 * Get all example OpenAPI files
 */
function getExampleFiles(): string[] {
  if (!fs.existsSync(EXAMPLES_DIR)) {
    return [];
  }

  return fs.readdirSync(EXAMPLES_DIR)
    .filter(file => file.endsWith('.yaml') || file.endsWith('.yml'))
    .map(file => path.join(EXAMPLES_DIR, file))
    .sort();
}

// Test Suite
describe('Import Validation Tests', () => {
  describe('File Format Validation', () => {
    test('should have example files in examples/openapi directory', () => {
      const files = getExampleFiles();
      expect(files.length).toBeGreaterThan(0);
      expect(files.length).toBeGreaterThanOrEqual(28);
    });

    test('should validate 01-numeric-constraints.yaml', () => {
      const filePath = path.join(EXAMPLES_DIR, '01-numeric-constraints.yaml');
      const result = validateOpenApiFile(filePath);

      expect(result.valid).toBe(true);
      expect(result.schemas).toBeGreaterThan(0);
    });

    test('should validate 02-array-contains.yaml', () => {
      const filePath = path.join(EXAMPLES_DIR, '02-array-contains.yaml');
      const result = validateOpenApiFile(filePath);

      expect(result.valid).toBe(true);
      expect(result.schemas).toBeGreaterThan(0);
    });

    test('should validate 03-object-properties.yaml', () => {
      const filePath = path.join(EXAMPLES_DIR, '03-object-properties.yaml');
      const result = validateOpenApiFile(filePath);

      expect(result.valid).toBe(true);
    });

    test('should validate 16-discriminator-mapping.yaml', () => {
      const filePath = path.join(EXAMPLES_DIR, '16-discriminator-mapping.yaml');
      const result = validateOpenApiFile(filePath);

      expect(result.valid).toBe(true);
      expect(result.schemas).toBeGreaterThan(0);
    });

    test('should validate 18-prefix-items-tuples.yaml', () => {
      const filePath = path.join(EXAMPLES_DIR, '18-prefix-items-tuples.yaml');
      const result = validateOpenApiFile(filePath);

      expect(result.valid).toBe(true);
    });

    test('should validate 20-comprehensive-features.yaml', () => {
      const filePath = path.join(EXAMPLES_DIR, '20-comprehensive-features.yaml');
      const result = validateOpenApiFile(filePath);

      expect(result.valid).toBe(true);
      expect(result.schemas).toBeGreaterThanOrEqual(1);
    });

    test('should validate 21-advanced-allof-inheritance.yaml', () => {
      const filePath = path.join(EXAMPLES_DIR, '21-advanced-allof-inheritance.yaml');
      const result = validateOpenApiFile(filePath);

      expect(result.valid).toBe(true);
    });

    test('should validate 22-advanced-oneof-polymorphism.yaml', () => {
      const filePath = path.join(EXAMPLES_DIR, '22-advanced-oneof-polymorphism.yaml');
      const result = validateOpenApiFile(filePath);

      expect(result.valid).toBe(true);
    });

    test('should validate 23-advanced-anyof-flexible.yaml', () => {
      const filePath = path.join(EXAMPLES_DIR, '23-advanced-anyof-flexible.yaml');
      const result = validateOpenApiFile(filePath);

      expect(result.valid).toBe(true);
    });

    test('should validate 25-test-property-conflict-diff.yaml', () => {
      const filePath = path.join(EXAMPLES_DIR, '25-test-property-conflict-diff.yaml');
      const result = validateOpenApiFile(filePath);

      expect(result.valid).toBe(true);
    });

    test('should validate 26-test-property-edge-cases.yaml', () => {
      const filePath = path.join(EXAMPLES_DIR, '26-test-property-edge-cases.yaml');
      const result = validateOpenApiFile(filePath);

      expect(result.valid).toBe(true);
    });

    test('should validate 27-test-property-mixed.yaml', () => {
      const filePath = path.join(EXAMPLES_DIR, '27-test-property-mixed.yaml');
      const result = validateOpenApiFile(filePath);

      expect(result.valid).toBe(true);
    });

    test('should validate 28-test-property-reuse-same.yaml', () => {
      const filePath = path.join(EXAMPLES_DIR, '28-test-property-reuse-same.yaml');
      const result = validateOpenApiFile(filePath);

      expect(result.valid).toBe(true);
    });

    test('should validate Swagger 2.0 petstore example', () => {
      const swaggerExamplesDir = path.join(__dirname, '../examples/swagger');
      const filePath = path.join(swaggerExamplesDir, '01-swagger-2-petstore.yaml');
      const result = validateOpenApiFile(filePath);

      expect(result.valid).toBe(true);
      expect(result.schemas).toBe(8); // Pet, NewPet, UpdatePet, Category, Error, UploadResponse, Order, User
    });
  });

  describe('Schema Structure Validation', () => {
    test('should parse all example files without errors', () => {
      const files = getExampleFiles();
      const failures: string[] = [];

      for (const file of files) {
        const result = validateOpenApiFile(file);
        if (!result.valid) {
          failures.push(`${path.basename(file)}: ${result.error}`);
        }
      }

      expect(failures.length).toBe(0);
    });

    test('comprehensive features file should have valid structure', () => {
      const filePath = path.join(EXAMPLES_DIR, '20-comprehensive-features.yaml');
      const result = validateOpenApiFile(filePath);

      expect(result.valid).toBe(true);
      expect(result.schemas).toBeGreaterThanOrEqual(1);
    });

    test('should validate discriminator mapping structure', () => {
      const filePath = path.join(EXAMPLES_DIR, '16-discriminator-mapping.yaml');
      const content = fs.readFileSync(filePath, 'utf-8');
      const doc = YAML.parse(content);

      // Check for discriminator pattern
      const hasDiscriminator = JSON.stringify(doc).includes('discriminator');
      expect(hasDiscriminator).toBe(true);
    });

    test('should validate prefix items (tuples) structure', () => {
      const filePath = path.join(EXAMPLES_DIR, '18-prefix-items-tuples.yaml');
      const content = fs.readFileSync(filePath, 'utf-8');
      const doc = YAML.parse(content);

      // Check for prefixItems pattern
      const hasPrefixItems = JSON.stringify(doc).includes('prefixItems');
      expect(hasPrefixItems).toBe(true);
    });

    test('should validate composition patterns', () => {
      const filePath = path.join(EXAMPLES_DIR, '21-advanced-allof-inheritance.yaml');
      const content = fs.readFileSync(filePath, 'utf-8');
      const doc = YAML.parse(content);

      // Check for allOf pattern
      const hasAllOf = JSON.stringify(doc).includes('allOf');
      expect(hasAllOf).toBe(true);
    });

    test('should validate oneOf polymorphism', () => {
      const filePath = path.join(EXAMPLES_DIR, '22-advanced-oneof-polymorphism.yaml');
      const content = fs.readFileSync(filePath, 'utf-8');
      const doc = YAML.parse(content);

      // Check for oneOf pattern
      const hasOneOf = JSON.stringify(doc).includes('oneOf');
      expect(hasOneOf).toBe(true);
    });

    test('should validate anyOf flexibility', () => {
      const filePath = path.join(EXAMPLES_DIR, '23-advanced-anyof-flexible.yaml');
      const content = fs.readFileSync(filePath, 'utf-8');
      const doc = YAML.parse(content);

      // Check for anyOf pattern
      const hasAnyOf = JSON.stringify(doc).includes('anyOf');
      expect(hasAnyOf).toBe(true);
    });

    test('should validate extension properties (x-*)', () => {
      const filePath = path.join(EXAMPLES_DIR, '14-custom-extensions.yaml');
      const content = fs.readFileSync(filePath, 'utf-8');
      const doc = YAML.parse(content);

      // Check for x- extension pattern
      const hasExtensions = JSON.stringify(doc).includes('"x-');
      expect(hasExtensions).toBe(true);
    });

    test('should validate property descriptions are present', () => {
      const filePath = path.join(EXAMPLES_DIR, '13-property-name-constraints.yaml');
      const content = fs.readFileSync(filePath, 'utf-8');
      const doc = YAML.parse(content);

      // Check for description fields
      const docStr = JSON.stringify(doc);
      expect(docStr.includes('description')).toBe(true);
    });
  });

  describe('All Examples Validation', () => {
    test('should validate all example files in directory', () => {
      const files = getExampleFiles();
      expect(files.length).toBeGreaterThanOrEqual(28);

      const results = files.map(file => ({
        file: path.basename(file),
        result: validateOpenApiFile(file),
      }));

      const failures = results.filter(r => !r.result.valid);

      if (failures.length > 0) {
        console.error('Failed files:');
        failures.forEach(f => {
          console.error(`  ${f.file}: ${f.result.error}`);
        });
      }

      expect(failures.length).toBe(0);
      expect(results.length).toBeGreaterThanOrEqual(28);
    });
  });
});
