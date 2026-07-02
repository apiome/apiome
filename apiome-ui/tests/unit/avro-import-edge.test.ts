/**
 * Edge-case and multi-suite tests for #239: Import from an Avro source.
 * Covers array-of-schemas, namespaces, failure paths, and pipeline consistency.
 */

import { describe, it, expect } from '@jest/globals';
import { convertAvroToOpenAPI, isAvro, isAvroSchemaObject } from '../../src/app/utils/avro-converter';
import { extractFileMetadata, analyzeSpecification } from '../../src/app/utils/openapi-analyzer';
import { parseOpenAPISpec } from '../../src/app/utils/openapi-import';

describe('#239 Avro Import – edge: multi-schema and array root', () => {
  it('converts array of schemas (multiple roots) into single OpenAPI doc', () => {
    const input = [
      { type: 'record', name: 'SchemaA', fields: [{ name: 'id', type: 'string' }] },
      { type: 'record', name: 'SchemaB', fields: [{ name: 'count', type: 'int' }] },
      { type: 'enum', name: 'Code', symbols: ['OK', 'ERR'] },
    ];
    const r = convertAvroToOpenAPI(input);
    expect(r.success).toBe(true);
    expect(r.document.components.schemas.SchemaA).toBeDefined();
    expect(r.document.components.schemas.SchemaB).toBeDefined();
    expect(r.document.components.schemas.Code).toBeDefined();
    expect(r.document.openapi).toBe('3.1.0');
  });

  it('parseOpenAPISpec accepts Avro as JSON string and returns all top-level schemas', () => {
    const avro = JSON.stringify({
      type: 'record',
      name: 'Root',
      fields: [
        {
          name: 'nested',
          type: {
            type: 'record',
            name: 'Nested',
            fields: [{ name: 'v', type: 'int' }],
          },
        },
      ],
    });
    const result = parseOpenAPISpec(avro);
    expect(result.success).toBe(true);
    expect(result.classes!.some((c) => c.name === 'Root')).toBe(true);
    expect(result.classes!.some((c) => c.name === 'Nested')).toBe(true);
  });
});

describe('#239 Avro Import – edge: namespace and naming', () => {
  it('uses full name with underscores for component key when namespace present', () => {
    const avro = {
      type: 'record',
      name: 'Event',
      namespace: 'org.example.events',
      fields: [{ name: 'id', type: 'string' }],
    };
    const r = convertAvroToOpenAPI(avro);
    expect(r.success).toBe(true);
    expect(r.document.components.schemas.org_example_events_Event).toBeDefined();
    expect(r.document.components.schemas.org_example_events_Event.properties.id).toEqual({ type: 'string' });
  });

  it('resolves short name reference to full name in same document', () => {
    const avro = {
      type: 'record',
      name: 'Wrapper',
      namespace: 'pkg',
      fields: [
        {
          name: 'inner',
          type: {
            type: 'record',
            name: 'Inner',
            namespace: 'pkg',
            fields: [{ name: 'x', type: 'string' }],
          },
        },
      ],
    };
    const r = convertAvroToOpenAPI(avro);
    expect(r.success).toBe(true);
    expect(r.document.components.schemas.pkg_Wrapper.properties.inner).toEqual({
      $ref: '#/components/schemas/pkg_Inner',
    });
  });
});

describe('#239 Avro Import – edge: failure and invalid input', () => {
  it('convertAvroToOpenAPI returns failure for array of primitives', () => {
    const r = convertAvroToOpenAPI([{ type: 'array', items: 'string' }]);
    expect(r.success).toBe(false);
    expect(r.error).toMatch(/No Avro record or enum/);
  });

  it('convertAvroToOpenAPI returns failure for object with only unsupported type', () => {
    const r = convertAvroToOpenAPI({ type: 'array', items: 'int' });
    expect(r.success).toBe(false);
  });

  it('isAvro returns false for empty string', () => {
    expect(isAvro('')).toBe(false);
  });

  it('isAvroSchemaObject returns false for null and non-object', () => {
    expect(isAvroSchemaObject(null)).toBe(false);
    expect(isAvroSchemaObject(undefined)).toBe(false);
    expect(isAvroSchemaObject('string')).toBe(false);
    expect(isAvroSchemaObject(42)).toBe(false);
  });
});

describe('#239 Avro Import – edge: metadata and format display', () => {
  it('extractFileMetadata on nested Avro sets format to avro', () => {
    const nested = JSON.stringify({
      type: 'record',
      name: 'N',
      fields: [
        {
          name: 'child',
          type: {
            type: 'record',
            name: 'Child',
            fields: [{ name: 's', type: 'string' }],
          },
        },
      ],
    });
    const meta = extractFileMetadata(nested);
    expect(meta.format).toBe('avro');
    expect(meta.formatSupported).toBe(true);
    expect(meta.syntaxValid).toBe(true);
  });

  it('analyzeSpecification with Avro produces document with info.title', async () => {
    const avro = JSON.stringify({
      type: 'record',
      name: 'T',
      fields: [{ name: 'x', type: 'string' }],
    });
    const result = await analyzeSpecification(avro, 't.avsc');
    expect(result.isValid).toBe(true);
    expect(result.document?.info?.title).toMatch(/Avro/i);
  });
});

describe('#239 Avro Import – edge: pipeline consistency', () => {
  it('same Avro string produces same classes via parseOpenAPISpec and analyzeSpecification doc', async () => {
    const avro = JSON.stringify({
      type: 'record',
      name: 'Consistent',
      fields: [
        { name: 'a', type: 'string' },
        { name: 'b', type: 'int' },
      ],
    });
    const parseResult = parseOpenAPISpec(avro);
    const analysisResult = await analyzeSpecification(avro);
    expect(parseResult.success).toBe(true);
    expect(analysisResult.isValid).toBe(true);
    const schemaFromAnalysis = analysisResult.document?.components?.schemas?.Consistent;
    expect(schemaFromAnalysis).toBeDefined();
    expect(schemaFromAnalysis.properties.a).toEqual({ type: 'string' });
    expect(schemaFromAnalysis.properties.b).toEqual({ type: 'integer', format: 'int32' });
    const consistentClass = parseResult.classes!.find((c) => c.name === 'Consistent');
    expect(consistentClass).toBeDefined();
    expect(consistentClass!.properties.length).toBe(2);
  });

  it('Avro with required and optional fields results in correct required array', () => {
    const avro = {
      type: 'record',
      name: 'ReqOpt',
      fields: [
        { name: 'required', type: 'string' },
        { name: 'optional', type: ['null', 'string'], default: null },
      ],
    };
    const r = convertAvroToOpenAPI(avro);
    expect(r.success).toBe(true);
    expect(r.document.components.schemas.ReqOpt.required).toEqual(['required']);
  });
});
