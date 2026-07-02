/**
 * Unit tests for #239: Import from an Avro source.
 * Covers avro-converter (isAvro, isAvroSchemaObject, convertAvroToOpenAPI),
 * extractFileMetadata, analyzeSpecification, and parseOpenAPISpec with Avro content.
 */

import { describe, it, expect } from '@jest/globals';
import { isAvro, isAvroSchemaObject, convertAvroToOpenAPI } from '../../src/app/utils/avro-converter';
import { extractFileMetadata, analyzeSpecification } from '../../src/app/utils/openapi-analyzer';
import { parseOpenAPISpec } from '../../src/app/utils/openapi-import';

const AVRO_RECORD = JSON.stringify({
  type: 'record',
  name: 'User',
  namespace: 'com.example',
  fields: [
    { name: 'id', type: 'long' },
    { name: 'name', type: 'string' },
    { name: 'active', type: 'boolean', default: true },
  ],
});

const AVRO_ENUM = JSON.stringify({
  type: 'enum',
  name: 'Status',
  symbols: ['PENDING', 'ACTIVE', 'DONE'],
});

const AVRO_RECORD_NO_NAMESPACE = JSON.stringify({
  type: 'record',
  name: 'Pet',
  fields: [
    { name: 'id', type: 'int' },
    { name: 'name', type: 'string' },
  ],
});

const AVRO_NESTED = JSON.stringify({
  type: 'record',
  name: 'Outer',
  fields: [
    {
      name: 'inner',
      type: {
        type: 'record',
        name: 'Inner',
        fields: [{ name: 'value', type: 'string' }],
      },
    },
  ],
});

const AVRO_RECORD_WITH_ENUM_REF = JSON.stringify({
  type: 'record',
  name: 'Order',
  fields: [
    { name: 'id', type: 'string' },
    {
      name: 'status',
      type: {
        type: 'enum',
        name: 'OrderStatus',
        symbols: ['NEW', 'SHIPPED', 'CANCELLED'],
      },
    },
  ],
});

describe('#239 Avro Import – unit', () => {
  describe('isAvro', () => {
    it('returns true for JSON with type record and fields', () => {
      expect(isAvro(AVRO_RECORD)).toBe(true);
      expect(isAvro(AVRO_RECORD_NO_NAMESPACE)).toBe(true);
    });

    it('returns true for JSON with type enum and symbols', () => {
      expect(isAvro(AVRO_ENUM)).toBe(true);
    });

    it('returns false for empty or non-JSON', () => {
      expect(isAvro('')).toBe(false);
      expect(isAvro(null as any)).toBe(false);
      expect(isAvro('openapi: 3.1.0')).toBe(false);
      expect(isAvro('{"openapi":"3.1.0"}')).toBe(false);
    });

    it('returns false for plain JSON object without record/enum', () => {
      expect(isAvro('{"foo":"bar"}')).toBe(false);
    });

    it('returns false for invalid JSON', () => {
      expect(isAvro('{ invalid }')).toBe(false);
      expect(isAvro('not json')).toBe(false);
    });

    it('returns true for array of record (multi-schema)', () => {
      const multi = JSON.stringify([
        { type: 'record', name: 'A', fields: [{ name: 'x', type: 'string' }] },
        { type: 'enum', name: 'E', symbols: ['X'] },
      ]);
      expect(isAvro(multi)).toBe(true);
    });
  });

  describe('isAvroSchemaObject', () => {
    it('returns true for record with fields', () => {
      expect(isAvroSchemaObject(JSON.parse(AVRO_RECORD))).toBe(true);
    });

    it('returns true for enum with symbols', () => {
      expect(isAvroSchemaObject(JSON.parse(AVRO_ENUM))).toBe(true);
    });

    it('returns false for OpenAPI-like object', () => {
      expect(isAvroSchemaObject({ openapi: '3.1.0' })).toBe(false);
    });

    it('returns false for record without fields array', () => {
      expect(isAvroSchemaObject({ type: 'record', name: 'X' })).toBe(false);
    });

    it('returns false for enum without symbols array', () => {
      expect(isAvroSchemaObject({ type: 'enum', name: 'E' })).toBe(false);
    });

    it('returns true for array of record and enum', () => {
      const arr = [
        { type: 'record', name: 'R', fields: [] },
        { type: 'enum', name: 'E', symbols: ['A'] },
      ];
      expect(isAvroSchemaObject(arr)).toBe(true);
    });
  });

  describe('convertAvroToOpenAPI', () => {
    it('returns failure for null input', () => {
      const r = convertAvroToOpenAPI(null as any);
      expect(r.success).toBe(false);
      expect(r.error).toContain('Invalid');
    });

    it('returns failure when no record or enum found', () => {
      const r = convertAvroToOpenAPI({ type: 'string' });
      expect(r.success).toBe(false);
      expect(r.error).toMatch(/No Avro record or enum/);
    });

    it('returns failure for empty array input', () => {
      const r = convertAvroToOpenAPI([]);
      expect(r.success).toBe(false);
    });

    it('returns failure for undefined input', () => {
      const r = convertAvroToOpenAPI(undefined as any);
      expect(r.success).toBe(false);
      expect(r.error).toContain('Invalid');
    });

    it('converts a single record to OpenAPI 3.1 components.schemas', () => {
      const r = convertAvroToOpenAPI(JSON.parse(AVRO_RECORD_NO_NAMESPACE));
      expect(r.success).toBe(true);
      expect(r.document.openapi).toBe('3.1.0');
      expect(r.document.components.schemas.Pet).toBeDefined();
      const schema = r.document.components.schemas.Pet;
      expect(schema.type).toBe('object');
      expect(schema.properties.id).toEqual({ type: 'integer', format: 'int32' });
      expect(schema.properties.name).toEqual({ type: 'string' });
      expect(schema.required).toEqual(['id', 'name']);
    });

    it('converts record with namespace to schema key with underscores', () => {
      const r = convertAvroToOpenAPI(JSON.parse(AVRO_RECORD));
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.com_example_User).toBeDefined();
      const schema = r.document.components.schemas.com_example_User;
      expect(schema.properties.id).toEqual({ type: 'integer', format: 'int64' });
      expect(schema.properties.name).toEqual({ type: 'string' });
      expect(schema.properties.active).toEqual({ type: 'boolean' });
    });

    it('converts enum to string schema with enum array', () => {
      const r = convertAvroToOpenAPI(JSON.parse(AVRO_ENUM));
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.Status).toBeDefined();
      expect(r.document.components.schemas.Status).toEqual({
        type: 'string',
        enum: ['PENDING', 'ACTIVE', 'DONE'],
      });
    });

    it('converts empty enum to string schema with UNKNOWN placeholder', () => {
      const r = convertAvroToOpenAPI({ type: 'enum', name: 'Empty', symbols: [] });
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.Empty.enum).toEqual(['UNKNOWN']);
    });

    it('converts record with empty fields to object with empty properties', () => {
      const r = convertAvroToOpenAPI({ type: 'record', name: 'EmptyRecord', fields: [] });
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.EmptyRecord.type).toBe('object');
      expect(r.document.components.schemas.EmptyRecord.properties).toEqual({});
    });

    it('converts nested record and creates separate schemas', () => {
      const r = convertAvroToOpenAPI(JSON.parse(AVRO_NESTED));
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.Outer).toBeDefined();
      expect(r.document.components.schemas.Inner).toBeDefined();
      expect(r.document.components.schemas.Outer.properties.inner).toEqual({
        $ref: '#/components/schemas/Inner',
      });
    });

    it('converts record with enum reference', () => {
      const r = convertAvroToOpenAPI(JSON.parse(AVRO_RECORD_WITH_ENUM_REF));
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.Order).toBeDefined();
      expect(r.document.components.schemas.OrderStatus).toBeDefined();
      expect(r.document.components.schemas.Order.properties.status).toEqual({
        $ref: '#/components/schemas/OrderStatus',
      });
    });

    it('returns warnings array', () => {
      const r = convertAvroToOpenAPI(JSON.parse(AVRO_RECORD_NO_NAMESPACE));
      expect(r.success).toBe(true);
      expect(Array.isArray(r.warnings)).toBe(true);
      expect(r.warnings.some((w) => w.includes('Avro'))).toBe(true);
    });
  });

  describe('extractFileMetadata with Avro', () => {
    it('detects Avro and returns formatSupported true', () => {
      const meta = extractFileMetadata(AVRO_RECORD_NO_NAMESPACE);
      expect(meta.syntaxValid).toBe(true);
      expect(meta.format).toBe('avro');
      expect(meta.formatSupported).toBe(true);
    });

    it('detects Avro from enum schema', () => {
      const meta = extractFileMetadata(AVRO_ENUM);
      expect(meta.format).toBe('avro');
    });
  });

  describe('analyzeSpecification with Avro', () => {
    it('converts Avro and returns valid analysis with openapi format', async () => {
      const result = await analyzeSpecification(AVRO_RECORD_NO_NAMESPACE, 'schema.avsc');
      expect(result.isValid).toBe(true);
      expect(result.format).toBe('openapi');
      expect(result.document?.components?.schemas?.Pet).toBeDefined();
      expect(result.metrics.schemaCount).toBeGreaterThanOrEqual(1);
    });

    it('analyzes Avro with enum and record', async () => {
      const result = await analyzeSpecification(AVRO_RECORD_WITH_ENUM_REF, 'order.avsc');
      expect(result.isValid).toBe(true);
      expect(result.metrics.schemaCount).toBeGreaterThanOrEqual(2);
    });

    it('does not treat arbitrary JSON as Avro', async () => {
      const result = await analyzeSpecification('{"foo":"bar"}', 'x.json');
      expect(result.format).not.toBe('avro');
    });
  });

  describe('parseOpenAPISpec with Avro', () => {
    it('parses Avro content and returns classes', () => {
      const result = parseOpenAPISpec(AVRO_RECORD_NO_NAMESPACE);
      expect(result.success).toBe(true);
      expect(result.classes).toBeDefined();
      expect(result.classes!.length).toBeGreaterThanOrEqual(1);
      const pet = result.classes!.find((c) => c.name === 'Pet');
      expect(pet).toBeDefined();
      expect(pet!.properties.length).toBeGreaterThanOrEqual(2);
    });

    it('parses Avro with enum and record into separate classes', () => {
      const result = parseOpenAPISpec(AVRO_RECORD_WITH_ENUM_REF);
      expect(result.success).toBe(true);
      expect(result.classes!.some((c) => c.name === 'Order')).toBe(true);
      expect(result.classes!.some((c) => c.name === 'OrderStatus')).toBe(true);
    });

    it('parses Avro with multiple schemas (nested)', () => {
      const result = parseOpenAPISpec(AVRO_NESTED);
      expect(result.success).toBe(true);
      expect(result.classes!.some((c) => c.name === 'Outer')).toBe(true);
      expect(result.classes!.some((c) => c.name === 'Inner')).toBe(true);
    });

    it('returns failure for non-OpenAPI, non-Avro JSON', () => {
      const result = parseOpenAPISpec('{"x":1}');
      expect(result.success).toBe(false);
      expect(result.error).toBeDefined();
    });
  });
});

describe('#239 Avro Import – converter types', () => {
  describe('array and map', () => {
    it('converts array of strings to array schema', () => {
      const avro = {
        type: 'record',
        name: 'WithArray',
        fields: [
          { name: 'tags', type: { type: 'array', items: 'string' } },
          { name: 'counts', type: { type: 'array', items: 'int' } },
        ],
      };
      const r = convertAvroToOpenAPI(avro);
      expect(r.success).toBe(true);
      const schema = r.document.components.schemas.WithArray;
      expect(schema.properties.tags).toEqual({ type: 'array', items: { type: 'string' } });
      expect(schema.properties.counts).toEqual({ type: 'array', items: { type: 'integer', format: 'int32' } });
    });

    it('converts map of string to value type', () => {
      const avro = {
        type: 'record',
        name: 'WithMap',
        fields: [{ name: 'metadata', type: { type: 'map', values: 'string' } }],
      };
      const r = convertAvroToOpenAPI(avro);
      expect(r.success).toBe(true);
      const schema = r.document.components.schemas.WithMap;
      expect(schema.properties.metadata).toEqual({
        type: 'object',
        additionalProperties: { type: 'string' },
      });
    });

    it('converts array of record reference', () => {
      const avro = {
        type: 'record',
        name: 'Parent',
        fields: [
          {
            name: 'children',
            type: {
              type: 'array',
              items: {
                type: 'record',
                name: 'Child',
                fields: [{ name: 'name', type: 'string' }],
              },
            },
          },
        ],
      };
      const r = convertAvroToOpenAPI(avro);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.Parent).toBeDefined();
      expect(r.document.components.schemas.Child).toBeDefined();
      expect(r.document.components.schemas.Parent.properties.children).toEqual({
        type: 'array',
        items: { $ref: '#/components/schemas/Child' },
      });
    });
  });

  describe('union and optional', () => {
    it('converts union with null to oneOf null and type', () => {
      const avro = {
        type: 'record',
        name: 'OptionalField',
        fields: [
          { name: 'maybe', type: ['null', 'string'] },
          { name: 'required', type: 'string' },
        ],
      };
      const r = convertAvroToOpenAPI(avro);
      expect(r.success).toBe(true);
      const schema = r.document.components.schemas.OptionalField;
      expect(schema.required).toEqual(['required']);
      expect(schema.properties.maybe).toEqual({
        oneOf: [{ type: 'null' }, { type: 'string' }],
      });
    });

    it('converts union of multiple types to oneOf', () => {
      const avro = {
        type: 'record',
        name: 'UnionRecord',
        fields: [{ name: 'value', type: ['null', 'string', 'int'] }],
      };
      const r = convertAvroToOpenAPI(avro);
      expect(r.success).toBe(true);
      const schema = r.document.components.schemas.UnionRecord;
      expect(schema.properties.value.oneOf).toHaveLength(3);
    });
  });

  describe('fixed and doc', () => {
    it('converts fixed type to string byte', () => {
      const avro = {
        type: 'record',
        name: 'WithFixed',
        fields: [
          {
            name: 'id',
            type: {
              type: 'fixed',
              name: 'UUID',
              size: 16,
            },
          },
        ],
      };
      const r = convertAvroToOpenAPI(avro);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.UUID).toEqual({
        type: 'string',
        format: 'byte',
        description: expect.stringContaining('16'),
      });
      const idSchema = r.document.components.schemas.WithFixed.properties.id;
      expect(idSchema.type).toBe('string');
      expect(idSchema.format).toBe('byte');
      expect(idSchema.$ref ?? idSchema.description).toBeDefined();
    });

    it('preserves doc on record and enum', () => {
      const avro = {
        type: 'record',
        name: 'Documented',
        doc: 'A documented record',
        fields: [
          {
            name: 'kind',
            type: {
              type: 'enum',
              name: 'Kind',
              doc: 'An enum',
              symbols: ['A', 'B'],
            },
          },
        ],
      };
      const r = convertAvroToOpenAPI(avro);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.Documented.description).toBe('A documented record');
      expect(r.document.components.schemas.Kind.description).toBe('An enum');
    });
  });

  describe('all primitives', () => {
    it('maps int, long, float, double, boolean, string, bytes', () => {
      const avro = {
        type: 'record',
        name: 'Primitives',
        fields: [
          { name: 'a', type: 'int' },
          { name: 'b', type: 'long' },
          { name: 'c', type: 'float' },
          { name: 'd', type: 'double' },
          { name: 'e', type: 'boolean' },
          { name: 'f', type: 'string' },
          { name: 'g', type: 'bytes' },
        ],
      };
      const r = convertAvroToOpenAPI(avro);
      expect(r.success).toBe(true);
      const p = r.document.components.schemas.Primitives.properties;
      expect(p.a).toEqual({ type: 'integer', format: 'int32' });
      expect(p.b).toEqual({ type: 'integer', format: 'int64' });
      expect(p.c).toEqual({ type: 'number', format: 'float' });
      expect(p.d).toEqual({ type: 'number', format: 'double' });
      expect(p.e).toEqual({ type: 'boolean' });
      expect(p.f).toEqual({ type: 'string' });
      expect(p.g).toEqual({ type: 'string', format: 'byte' });
    });
  });
});

describe('#239 Avro Import – metadata and analysis', () => {
  it('extractFileMetadata returns formatDisplayName for Avro', () => {
    const meta = extractFileMetadata(AVRO_RECORD);
    expect(meta.formatDisplayName).toMatch(/Avro/i);
    expect(meta.syntax).toBe('json');
  });

  it('analyzeSpecification sets qualityScore and metrics for converted Avro', async () => {
    const result = await analyzeSpecification(AVRO_NESTED, 'nested.avsc');
    expect(result.isValid).toBe(true);
    expect(result.qualityScore).toBeDefined();
    expect(result.qualityScore.overall).toBeGreaterThanOrEqual(0);
    expect(result.metrics.schemaCount).toBe(2);
    expect(result.metrics.propertyCount).toBeGreaterThanOrEqual(1);
  });

  it('parseOpenAPISpec returns classes with correct structure for import pipeline', () => {
    const result = parseOpenAPISpec(AVRO_RECORD_NO_NAMESPACE);
    expect(result.success).toBe(true);
    expect(result.warnings).toBeDefined();
    const pet = result.classes!.find((c) => c.name === 'Pet');
    expect(pet?.isSupported).toBe(true);
    expect(pet?.properties.some((p) => p.name === 'id')).toBe(true);
  });
});
