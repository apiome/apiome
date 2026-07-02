/**
 * Unit tests for #238: Import from Protobuf Definitions.
 * Covers protobuf-converter (isProtobuf, convertProtobufToOpenAPI),
 * extractFileMetadata, analyzeSpecification, and parseOpenAPISpec with Protobuf content.
 */

import { describe, it, expect } from '@jest/globals';
import { isProtobuf, convertProtobufToOpenAPI } from '../../src/app/utils/protobuf-converter';
import { extractFileMetadata } from '../../src/app/utils/openapi-analyzer';
import { analyzeSpecification } from '../../src/app/utils/openapi-analyzer';
import { parseOpenAPISpec } from '../../src/app/utils/openapi-import';

// Sample .proto fixtures for integration tests
const PROTO_MINIMAL = `syntax = "proto3";
message SearchRequest {
  string query = 1;
  int32 page_number = 2;
}
`;

const PROTO_WITH_ENUM_AND_MESSAGE = `syntax = "proto3";
enum Status { UNKNOWN = 0; OK = 1; ERROR = 2; }
message Result {
  string id = 1;
  Status status = 2;
}
`;

const PROTO_NESTED_MESSAGE = `syntax = "proto3";
message Outer {
  message Inner {
    string value = 1;
  }
  Inner inner = 1;
}
`;

const PROTO_MULTIPLE_SCHEMAS = `syntax = "proto3";
message A { string x = 1; }
message B { int32 y = 1; }
enum E { X = 0; Y = 1; }
`;

describe('#238 Protobuf Import – unit', () => {
  describe('isProtobuf', () => {
    it('returns true when content has syntax = "proto3"', () => {
      expect(isProtobuf('syntax = "proto3";')).toBe(true);
      expect(isProtobuf('  syntax = "proto3";\nmessage X {}')).toBe(true);
    });

    it('returns true when content has syntax = "proto2"', () => {
      expect(isProtobuf('syntax = "proto2";')).toBe(true);
    });

    it('returns true when content has message X {', () => {
      expect(isProtobuf('message SearchRequest { string q = 1; }')).toBe(true);
      expect(isProtobuf('enum X {} message Y { int32 z = 1; }')).toBe(true);
    });

    it('returns true when content has enum X {', () => {
      expect(isProtobuf('enum Status { UNKNOWN = 0; OK = 1; }')).toBe(true);
    });

    it('returns false for empty or non-string', () => {
      expect(isProtobuf('')).toBe(false);
      expect(isProtobuf(null as any)).toBe(false);
      expect(isProtobuf(undefined as any)).toBe(false);
    });

    it('returns false for OpenAPI-like content', () => {
      expect(isProtobuf('openapi: 3.1.0')).toBe(false);
      expect(isProtobuf('{"openapi":"3.1.0"}')).toBe(false);
    });

    it('returns false for GraphQL-like content without message/enum', () => {
      expect(isProtobuf('type Query { x: String }')).toBe(false);
    });
  });

  describe('convertProtobufToOpenAPI', () => {
    it('returns failure for null or empty content', () => {
      const r1 = convertProtobufToOpenAPI('');
      expect(r1.success).toBe(false);
      expect(r1.error).toContain('Invalid');

      const r2 = convertProtobufToOpenAPI(null as any);
      expect(r2.success).toBe(false);
    });

    it('returns failure when content is not Protobuf', () => {
      const r = convertProtobufToOpenAPI('openapi: 3.1.0');
      expect(r.success).toBe(false);
      expect(r.error).toContain('does not appear');
    });

    it('returns failure when no message or enum definitions', () => {
      const r = convertProtobufToOpenAPI('syntax = "proto3";\npackage foo;');
      expect(r.success).toBe(false);
      expect(r.error).toContain('No message or enum');
    });

    it('converts proto3 message with scalar fields to OpenAPI 3.1 schema', () => {
      const proto = `
syntax = "proto3";
message SearchRequest {
  string query = 1;
  int32 page_number = 2;
  int32 results_per_page = 3;
}
`;
      const r = convertProtobufToOpenAPI(proto);
      expect(r.success).toBe(true);
      expect(r.document).not.toBeNull();
      expect(r.document.openapi).toBe('3.1.0');
      expect(r.document.components.schemas.SearchRequest).toBeDefined();
      const schema = r.document.components.schemas.SearchRequest;
      expect(schema.type).toBe('object');
      expect(schema.properties.query).toEqual({ type: 'string' });
      expect(schema.properties.page_number).toEqual({ type: 'integer', format: 'int32' });
      expect(schema.properties.results_per_page).toEqual({ type: 'integer', format: 'int32' });
    });

    it('converts enum to OpenAPI schema with string and enum array', () => {
      const proto = `
syntax = "proto3";
enum Status {
  UNKNOWN = 0;
  OK = 1;
  ERROR = 2;
}
`;
      const r = convertProtobufToOpenAPI(proto);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.Status).toEqual({
        type: 'string',
        enum: ['UNKNOWN', 'OK', 'ERROR'],
        description: 'Enum: Status',
      });
    });

    it('converts message with enum field to $ref to enum schema', () => {
      const proto = `
syntax = "proto3";
enum Status { UNKNOWN = 0; OK = 1; }
message Result {
  string id = 1;
  Status status = 2;
}
`;
      const r = convertProtobufToOpenAPI(proto);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.Result.properties.status).toMatchObject({
        type: 'string',
        enum: ['UNKNOWN', 'OK'],
      });
    });

    it('converts repeated field to array', () => {
      const proto = `
syntax = "proto3";
message Item { string name = 1; }
message List {
  repeated string tags = 1;
  repeated Item items = 2;
}
`;
      const r = convertProtobufToOpenAPI(proto);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.List.properties.tags).toEqual({
        type: 'array',
        items: { type: 'string' },
      });
      expect(r.document.components.schemas.List.properties.items).toEqual({
        type: 'array',
        items: { $ref: '#/components/schemas/Item' },
      });
    });

    it('converts map field to object with additionalProperties', () => {
      const proto = `
syntax = "proto3";
message Data {
  map<string, int32> counts = 1;
}
`;
      const r = convertProtobufToOpenAPI(proto);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.Data.properties.counts).toEqual({
        type: 'object',
        additionalProperties: { type: 'integer', format: 'int32' },
      });
    });

    it('strips comments before parsing', () => {
      const proto = `
// comment
syntax = "proto3";
message X {
  string y = 1; // field comment
}
`;
      const r = convertProtobufToOpenAPI(proto);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.X.properties.y).toEqual({ type: 'string' });
    });

    it('adds conversion warning about services not imported', () => {
      const proto = 'syntax = "proto3";\nmessage M { string f = 1; }';
      const r = convertProtobufToOpenAPI(proto);
      expect(r.success).toBe(true);
      expect(r.warnings.some((w) => w.includes('Protocol Buffers') && w.includes('Services'))).toBe(true);
    });

    it('accepts optional fileName parameter without affecting result', () => {
      const proto = 'syntax = "proto3";\nmessage M { string f = 1; }';
      const r1 = convertProtobufToOpenAPI(proto);
      const r2 = convertProtobufToOpenAPI(proto, 'api.proto');
      expect(r1.success).toBe(r2.success);
      expect(r1.document).toEqual(r2.document);
    });

    it('converts all scalar types to correct JSON Schema types', () => {
      const proto = `
syntax = "proto3";
message Scalars {
  double d = 1;
  float f = 2;
  int64 i64 = 3;
  uint32 u32 = 4;
  bool b = 5;
  bytes by = 6;
}
`;
      const r = convertProtobufToOpenAPI(proto);
      expect(r.success).toBe(true);
      const s = r.document.components.schemas.Scalars.properties;
      expect(s.d).toEqual({ type: 'number', format: 'double' });
      expect(s.f).toEqual({ type: 'number', format: 'float' });
      expect(s.i64).toEqual({ type: 'integer', format: 'int64' });
      expect(s.u32).toEqual({ type: 'integer', format: 'int32' });
      expect(s.b).toEqual({ type: 'boolean' });
      expect(s.by).toEqual({ type: 'string', format: 'byte' });
    });

    it('proto2 required fields appear in schema required array', () => {
      const proto = `
syntax = "proto2";
message Person {
  required string name = 1;
  optional int32 age = 2;
}
`;
      const r = convertProtobufToOpenAPI(proto);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.Person.required).toEqual(['name']);
      expect(r.document.components.schemas.Person.properties.name).toEqual({ type: 'string' });
      expect(r.document.components.schemas.Person.properties.age).toEqual({ type: 'integer', format: 'int32' });
    });

    it('nested message gets fullName and ref from parent', () => {
      const proto = `
syntax = "proto3";
message Outer {
  message Inner { string value = 1; }
  Inner inner = 1;
}
`;
      const r = convertProtobufToOpenAPI(proto);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.Outer_Inner).toBeDefined();
      expect(r.document.components.schemas.Outer_Inner.properties.value).toEqual({ type: 'string' });
      const innerRef = r.document.components.schemas.Outer.properties.inner;
      expect(innerRef).toHaveProperty('$ref');
      expect(innerRef.$ref).toMatch(/#\/components\/schemas\/(Inner|Outer_Inner)/);
    });

    it('strips block comments before parsing', () => {
      const proto = `
/* header comment */
syntax = "proto3";
message X {
  /* field comment */ string y = 1;
}
`;
      const r = convertProtobufToOpenAPI(proto);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.X.properties.y).toEqual({ type: 'string' });
    });

    it('empty enum gets UNSPECIFIED fallback', () => {
      const proto = `
syntax = "proto3";
enum Empty {}
`;
      const r = convertProtobufToOpenAPI(proto);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.Empty).toEqual({
        type: 'string',
        enum: ['UNSPECIFIED'],
        description: 'Enum: Empty',
      });
    });

    it('map with message value type uses $ref in additionalProperties', () => {
      const proto = `
syntax = "proto3";
message Val { string s = 1; }
message WithMap {
  map<string, Val> meta = 1;
}
`;
      const r = convertProtobufToOpenAPI(proto);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.WithMap.properties.meta).toEqual({
        type: 'object',
        additionalProperties: { $ref: '#/components/schemas/Val' },
      });
    });

    it('map with enum value type uses string enum in additionalProperties', () => {
      const proto = `
syntax = "proto3";
enum Kind { A = 0; B = 1; }
message WithMap {
  map<string, Kind> kinds = 1;
}
`;
      const r = convertProtobufToOpenAPI(proto);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.WithMap.properties.kinds).toEqual({
        type: 'object',
        additionalProperties: { type: 'string', enum: ['A', 'B'] },
      });
    });

    it('forward reference resolves when message defined later', () => {
      const proto = `
syntax = "proto3";
message A { B b = 1; }
message B { string x = 1; }
`;
      const r = convertProtobufToOpenAPI(proto);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.A.properties.b).toEqual({
        $ref: '#/components/schemas/B',
      });
    });

    it('output document has OpenAPI info title and description', () => {
      const proto = 'syntax = "proto3";\nmessage M { string f = 1; }';
      const r = convertProtobufToOpenAPI(proto);
      expect(r.success).toBe(true);
      expect(r.document.info.title).toBe('Imported from Protocol Buffers');
      expect(r.document.info.version).toBe('1.0.0');
      expect(r.document.info.description).toContain('Converted from');
      expect(r.document.info.description).toContain('message and enum');
    });

    it('repeated enum field becomes array of string enum', () => {
      const proto = `
syntax = "proto3";
enum Flag { OFF = 0; ON = 1; }
message Item {
  repeated Flag flags = 1;
}
`;
      const r = convertProtobufToOpenAPI(proto);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.Item.properties.flags).toEqual({
        type: 'array',
        items: { type: 'string', enum: ['OFF', 'ON'] },
      });
    });

    it('message with no fields has empty properties object', () => {
      const proto = 'syntax = "proto3";\nmessage Empty {}';
      const r = convertProtobufToOpenAPI(proto);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.Empty.type).toBe('object');
      expect(r.document.components.schemas.Empty.properties).toEqual({});
    });

    it('does not mutate the input string', () => {
      const proto = 'syntax = "proto3";\nmessage M { string f = 1; }';
      const before = proto;
      convertProtobufToOpenAPI(proto);
      expect(proto).toBe(before);
    });

    it('produces one schema per message and one per enum', () => {
      const r = convertProtobufToOpenAPI(PROTO_MULTIPLE_SCHEMAS);
      expect(r.success).toBe(true);
      const keys = Object.keys(r.document.components.schemas);
      expect(keys).toContain('A');
      expect(keys).toContain('B');
      expect(keys).toContain('E');
      expect(keys.length).toBe(3);
    });
  });

  describe('extractFileMetadata with Protobuf', () => {
    it('detects Protobuf and returns formatSupported true', () => {
      const meta = extractFileMetadata(PROTO_MINIMAL);
      expect(meta.syntaxValid).toBe(true);
      expect(meta.format).toBe('protobuf');
      expect(meta.formatSupported).toBe(true);
      expect(meta.formatDisplayName).toMatch(/Protocol Buffers|OpenAPI 3\.1/);
    });

    it('detects Protobuf from content without syntax line (message pattern)', () => {
      const content = 'message X { string y = 1; }';
      const meta = extractFileMetadata(content);
      expect(meta.format).toBe('protobuf');
      expect(meta.formatSupported).toBe(true);
    });

    it('returns syntax protobuf for Protobuf content', () => {
      const meta = extractFileMetadata(PROTO_WITH_ENUM_AND_MESSAGE);
      expect(meta.syntax).toBe('protobuf');
      expect(meta.format).toBe('protobuf');
    });
  });

  describe('analyzeSpecification with Protobuf', () => {
    it('converts Protobuf and returns valid analysis with openapi format', async () => {
      const result = await analyzeSpecification(PROTO_MINIMAL, 'api.proto');
      expect(result.isValid).toBe(true);
      expect(result.formatSupported).toBe(true);
      expect(result.document).not.toBeNull();
      expect(result.document.openapi).toBe('3.1.0');
      expect(result.document.components.schemas.SearchRequest).toBeDefined();
      expect(result.metrics.schemaCount).toBeGreaterThanOrEqual(1);
    });

    it('includes conversion warnings in analysis', async () => {
      const result = await analyzeSpecification(PROTO_MINIMAL, 'api.proto');
      expect(result.warnings.some((w) => w.message && (w.message.includes('Protocol Buffers') || w.message.includes('Converted')))).toBe(true);
    });

    it('analyzes Protobuf with enum and message', async () => {
      const result = await analyzeSpecification(PROTO_WITH_ENUM_AND_MESSAGE, 'spec.proto');
      expect(result.isValid).toBe(true);
      expect(result.document.components.schemas.Status).toBeDefined();
      expect(result.document.components.schemas.Result).toBeDefined();
      expect(result.metrics.schemaCount).toBe(2);
    });

    it('analyzes Protobuf with nested message', async () => {
      const result = await analyzeSpecification(PROTO_NESTED_MESSAGE, 'nested.proto');
      expect(result.isValid).toBe(true);
      expect(result.document.components.schemas.Outer).toBeDefined();
      expect(result.document.components.schemas.Outer_Inner).toBeDefined();
    });

    it('returns invalid when Protobuf conversion fails (no messages/enums)', async () => {
      const result = await analyzeSpecification('syntax = "proto3";\npackage foo;', 'bad.proto');
      expect(result.isValid).toBe(false);
      expect(result.format).toBe('protobuf');
      expect(result.errors.length).toBeGreaterThan(0);
    });
  });

  describe('parseOpenAPISpec with Protobuf', () => {
    it('parses Protobuf content and returns classes', () => {
      const result = parseOpenAPISpec(PROTO_MINIMAL);
      expect(result.success).toBe(true);
      expect(result.classes).toBeDefined();
      expect(result.classes!.length).toBeGreaterThanOrEqual(1);
      const searchRequest = result.classes!.find((c) => c.name === 'SearchRequest');
      expect(searchRequest).toBeDefined();
      expect(searchRequest!.properties.some((p) => p.name === 'query' || p.name === 'page_number')).toBe(true);
    });

    it('parses Protobuf with enum and message into separate classes', () => {
      const result = parseOpenAPISpec(PROTO_WITH_ENUM_AND_MESSAGE);
      expect(result.success).toBe(true);
      expect(result.classes!.length).toBeGreaterThanOrEqual(1);
      const names = result.classes!.map((c) => c.name);
      expect(names.some((n) => n === 'Status' || n === 'Result')).toBe(true);
    });

    it('parses Protobuf with multiple schemas', () => {
      const result = parseOpenAPISpec(PROTO_MULTIPLE_SCHEMAS);
      expect(result.success).toBe(true);
      expect(result.classes!.length).toBeGreaterThanOrEqual(1);
      const names = result.classes!.map((c) => c.name);
      expect(names.some((n) => ['A', 'B', 'E'].includes(n))).toBe(true);
    });

    it('parses nested message and includes Outer_Inner as class', () => {
      const result = parseOpenAPISpec(PROTO_NESTED_MESSAGE);
      expect(result.success).toBe(true);
      expect(result.classes!.some((c) => c.name === 'Outer_Inner')).toBe(true);
      expect(result.classes!.some((c) => c.name === 'Outer')).toBe(true);
    });

    it('returns failure and error when Protobuf has no message or enum', () => {
      const result = parseOpenAPISpec('syntax = "proto3";\npackage only;');
      expect(result.success).toBe(false);
      expect(result.error).toMatch(/Protobuf|No message|enum/);
      expect(result.classes).toEqual([]);
    });

    it('includes conversion warning in parse result', () => {
      const result = parseOpenAPISpec(PROTO_MINIMAL);
      expect(result.success).toBe(true);
      expect(result.warnings.some((w) => w.includes('Protocol Buffers') || w.includes('Converted'))).toBe(true);
    });
  });
});
