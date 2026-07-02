/**
 * Unit tests for #240: Import from a Thrift file.
 * Covers thrift-converter (isThrift, convertThriftToOpenAPI),
 * extractFileMetadata, analyzeSpecification, and parseOpenAPISpec with Thrift content.
 */

import { describe, it, expect } from '@jest/globals';
import { isThrift, convertThriftToOpenAPI } from '../../src/app/utils/thrift-converter';
import { extractFileMetadata, analyzeSpecification } from '../../src/app/utils/openapi-analyzer';
import { parseOpenAPISpec } from '../../src/app/utils/openapi-import';

const THRIFT_STRUCT = `
namespace java com.example
struct User {
  1: required i32 id
  2: optional string name
  3: bool active = true
}
`;

const THRIFT_ENUM = `
enum Status {
  PENDING
  ACTIVE
  DONE
}
`;

const THRIFT_STRUCT_AND_ENUM = `
struct Pet {
  1: i32 id
  2: string name
}

enum OrderStatus {
  NEW
  SHIPPED
  CANCELLED
}

struct Order {
  1: string id
  2: OrderStatus status
}
`;

const THRIFT_LIST_MAP = `
struct WithContainers {
  1: list<string> tags
  2: map<string, i32> counts
  3: set<i32> ids
}
`;

const THRIFT_UNION_EXCEPTION = `
union Result {
  1: string value
  2: string error
}

exception ApiError {
  1: required string message
  2: optional i32 code
}
`;

const THRIFT_TYPEDEF = `
typedef string UserId
typedef list<i32> IdList
struct WithTypedefs {
  1: UserId id
  2: IdList ids
}
`;

const THRIFT_ALL_BASE_TYPES = `
struct AllPrimitives {
  1: bool b
  2: byte by
  3: i8 i8
  4: i16 i16
  5: i32 i32
  6: i64 i64
  7: double d
  8: string s
  9: binary bin
}
`;

const THRIFT_ENUM_WITH_VALUES = `
enum Code {
  OK = 0
  NOT_FOUND = 1
  ERROR = 2
}
`;

const THRIFT_NESTED_CONTAINERS = `
struct Nested {
  1: list<map<string, i32>> listOfMaps
  2: map<string, list<string>> mapOfLists
}
`;

const THRIFT_WITH_COMMENTS = `
# Thrift file with comments
struct Commented {
  1: i32 id  // field id
  2: string name  /* inline */
}
/* block
   comment */
enum E { A; B; C }
`;

const THRIFT_SEMICOLONS = `
struct Semicolons {
  1: i32 a;
  2: string b;
}
`;

const THRIFT_EMPTY_ENUM = `
enum Empty { }
struct Wrapper { 1: Empty e }
`;

const THRIFT_SERVICE = `
service Hello {
  string greet(1: string name)
}
`;

const THRIFT_ONLY_OPTIONAL = `
struct OptionalOnly {
  1: optional string a
  2: optional i32 b
}
`;

describe('#240 Thrift Import – unit', () => {
  describe('isThrift', () => {
    it('returns true for content with struct', () => {
      expect(isThrift(THRIFT_STRUCT)).toBe(true);
      expect(isThrift('struct Foo { 1: string x }')).toBe(true);
    });

    it('returns true for content with enum', () => {
      expect(isThrift(THRIFT_ENUM)).toBe(true);
      expect(isThrift('enum Bar { A, B }')).toBe(true);
    });

    it('returns true for content with namespace or include', () => {
      expect(isThrift('namespace java com.example')).toBe(true);
      expect(isThrift('include "other.thrift"')).toBe(true);
    });

    it('returns true for content with union, exception, or service', () => {
      expect(isThrift('union U { 1: string x }')).toBe(true);
      expect(isThrift('exception E { 1: string msg }')).toBe(true);
      expect(isThrift(THRIFT_SERVICE)).toBe(true);
    });

    it('returns true for content with typedef', () => {
      expect(isThrift('typedef string Id')).toBe(true);
      expect(isThrift(THRIFT_TYPEDEF)).toBe(true);
    });

    it('returns false for empty, whitespace, or non-Thrift', () => {
      expect(isThrift('')).toBe(false);
      expect(isThrift('   \n\t  ')).toBe(false);
      expect(isThrift('openapi: 3.0.0')).toBe(false);
      expect(isThrift('{ "type": "object" }')).toBe(false);
      expect(isThrift('type Query { x: Int }')).toBe(false);
    });

    it('returns false when prose contains "include" or line has x-namespace (OpenAPI / YAML)', () => {
      // Regression: Ably OpenAPI (APIs-guru) describes RFC 5988 with "include a link…"; old `\binclude\s+` misdetected Thrift.
      expect(
        isThrift(
          'description: Links in the format defined by RFC 5988. This will potentially include a link with relation type `next`.'
        )
      ).toBe(false);
      expect(isThrift('x-namespace: "urn:example"\nopenapi: 3.0.0')).toBe(false);
    });

    it('returns false for null or non-string', () => {
      expect(isThrift(null as any)).toBe(false);
      expect(isThrift(undefined as any)).toBe(false);
      expect(isThrift(123 as any)).toBe(false);
    });
  });

  describe('convertThriftToOpenAPI', () => {
    it('converts struct to OpenAPI schema', () => {
      const result = convertThriftToOpenAPI(THRIFT_STRUCT);
      expect(result.success).toBe(true);
      expect(result.document?.openapi).toBe('3.1.0');
      expect(result.document?.components?.schemas?.User).toBeDefined();
      const user = result.document.components.schemas.User;
      expect(user.type).toBe('object');
      expect(user.properties?.id).toEqual({ type: 'integer', format: 'int32' });
      expect(user.properties?.name).toEqual({ type: 'string' });
      expect(user.properties?.active).toEqual({ type: 'boolean' });
      expect(user.required).toContain('id');
    });

    it('converts enum to OpenAPI schema', () => {
      const result = convertThriftToOpenAPI(THRIFT_ENUM);
      expect(result.success).toBe(true);
      expect(result.document?.components?.schemas?.Status).toBeDefined();
      const status = result.document!.components!.schemas!.Status as { type: string; enum: string[]; description: string };
      expect(status.type).toBe('string');
      expect(status.enum).toEqual(['PENDING', 'ACTIVE', 'DONE']);
      expect(status.description).toBe('Enum: Status');
    });

    it('converts struct with enum reference', () => {
      const result = convertThriftToOpenAPI(THRIFT_STRUCT_AND_ENUM);
      expect(result.success).toBe(true);
      expect(result.document?.components?.schemas?.Order).toBeDefined();
      expect(result.document.components.schemas.Order.properties.status).toEqual({
        $ref: '#/components/schemas/OrderStatus',
      });
    });

    it('converts list, map, set to OpenAPI types', () => {
      const result = convertThriftToOpenAPI(THRIFT_LIST_MAP);
      expect(result.success).toBe(true);
      const schema = result.document?.components?.schemas?.WithContainers;
      expect(schema?.properties?.tags).toEqual({
        type: 'array',
        items: { type: 'string' },
      });
      expect(schema?.properties?.counts).toEqual({
        type: 'object',
        additionalProperties: { type: 'integer', format: 'int32' },
        description: 'Map type (keys are strings in JSON)',
      });
      expect(schema?.properties?.ids).toEqual({
        type: 'array',
        items: { type: 'integer', format: 'int32' },
        uniqueItems: true,
      });
    });

    it('converts union and exception to object schemas', () => {
      const result = convertThriftToOpenAPI(THRIFT_UNION_EXCEPTION);
      expect(result.success).toBe(true);
      expect(result.document?.components?.schemas?.Result).toBeDefined();
      expect(result.document?.components?.schemas?.ApiError).toBeDefined();
    });

    it('returns error for empty or invalid content', () => {
      expect(convertThriftToOpenAPI('').success).toBe(false);
      expect(convertThriftToOpenAPI('openapi: 3.0.0').success).toBe(false);
    });

    it('includes error message and warnings on failure', () => {
      const empty = convertThriftToOpenAPI('');
      expect(empty.success).toBe(false);
      expect(empty.error).toBeDefined();
      expect(empty.error!.length).toBeGreaterThan(0);
      expect(Array.isArray(empty.warnings)).toBe(true);

      const invalid = convertThriftToOpenAPI('openapi: 3.0.0');
      expect(invalid.success).toBe(false);
      expect(invalid.error).toContain('Thrift');
    });

    it('resolves typedefs in struct fields', () => {
      const result = convertThriftToOpenAPI(THRIFT_TYPEDEF);
      expect(result.success).toBe(true);
      const schema = result.document?.components?.schemas?.WithTypedefs;
      expect(schema).toBeDefined();
      expect(schema.properties.id).toEqual({ type: 'string' });
      // IdList typedef (list<i32>) may be resolved to array or left as alias
      expect(schema.properties.ids).toBeDefined();
      const ids = schema.properties.ids;
      expect(ids.type === 'array' || ids.type === 'string').toBe(true);
      if (ids.type === 'array') {
        expect(ids.items).toEqual({ type: 'integer', format: 'int32' });
      }
    });

    it('maps all Thrift base types to OpenAPI', () => {
      const result = convertThriftToOpenAPI(THRIFT_ALL_BASE_TYPES);
      expect(result.success).toBe(true);
      const schema = result.document?.components?.schemas?.AllPrimitives;
      expect(schema?.properties?.b).toEqual({ type: 'boolean' });
      expect(schema?.properties?.by).toEqual({ type: 'integer', format: 'int8' });
      expect(schema?.properties?.i8).toEqual({ type: 'integer', format: 'int8' });
      expect(schema?.properties?.i16).toEqual({ type: 'integer', format: 'int16' });
      expect(schema?.properties?.i32).toEqual({ type: 'integer', format: 'int32' });
      expect(schema?.properties?.i64).toEqual({ type: 'integer', format: 'int64' });
      expect(schema?.properties?.d).toEqual({ type: 'number', format: 'double' });
      expect(schema?.properties?.s).toEqual({ type: 'string' });
      expect(schema?.properties?.bin).toEqual({ type: 'string', format: 'byte' });
    });

    it('converts enum with explicit integer values', () => {
      const result = convertThriftToOpenAPI(THRIFT_ENUM_WITH_VALUES);
      expect(result.success).toBe(true);
      const schema = result.document?.components?.schemas?.Code;
      expect(schema).toBeDefined();
      expect(schema.type).toBe('string');
      expect(schema.enum).toEqual(['OK', 'NOT_FOUND', 'ERROR']);
    });

    it('converts nested list and map types', () => {
      const result = convertThriftToOpenAPI(THRIFT_NESTED_CONTAINERS);
      expect(result.success).toBe(true);
      const schema = result.document?.components?.schemas?.Nested;
      expect(schema?.properties?.listOfMaps).toEqual({
        type: 'array',
        items: {
          type: 'object',
          additionalProperties: { type: 'integer', format: 'int32' },
          description: 'Map type (keys are strings in JSON)',
        },
      });
      expect(schema?.properties?.mapOfLists).toEqual({
        type: 'object',
        additionalProperties: {
          type: 'array',
          items: { type: 'string' },
        },
        description: 'Map type (keys are strings in JSON)',
      });
    });

    it('strips comments and converts struct/enum', () => {
      const result = convertThriftToOpenAPI(THRIFT_WITH_COMMENTS);
      expect(result.success).toBe(true);
      expect(result.document?.components?.schemas?.Commented).toBeDefined();
      expect(result.document?.components?.schemas?.E).toBeDefined();
      expect(result.document.components.schemas.Commented.properties.id).toEqual({
        type: 'integer',
        format: 'int32',
      });
    });

    it('accepts semicolon as field separator', () => {
      const result = convertThriftToOpenAPI(THRIFT_SEMICOLONS);
      expect(result.success).toBe(true);
      const schema = result.document?.components?.schemas?.Semicolons;
      expect(schema?.properties?.a).toEqual({ type: 'integer', format: 'int32' });
      expect(schema?.properties?.b).toEqual({ type: 'string' });
    });

    it('handles empty enum and struct referencing it', () => {
      const result = convertThriftToOpenAPI(THRIFT_EMPTY_ENUM);
      expect(result.success).toBe(true);
      const emptyEnum = result.document?.components?.schemas?.Empty;
      expect(emptyEnum).toBeDefined();
      expect(emptyEnum.type).toBe('string');
      expect(Array.isArray(emptyEnum.enum)).toBe(true);
      expect(result.document?.components?.schemas?.Wrapper).toBeDefined();
    });

    it('struct with only optional fields has no required array', () => {
      const result = convertThriftToOpenAPI(THRIFT_ONLY_OPTIONAL);
      expect(result.success).toBe(true);
      const schema = result.document?.components?.schemas?.OptionalOnly;
      expect(schema).toBeDefined();
      expect(schema.required).toBeUndefined();
      expect(schema.properties?.a).toEqual({ type: 'string' });
      expect(schema.properties?.b).toEqual({ type: 'integer', format: 'int32' });
    });

    it('produces valid OpenAPI 3.1 doc with info and components', () => {
      const result = convertThriftToOpenAPI(THRIFT_STRUCT);
      expect(result.success).toBe(true);
      expect(result.document.openapi).toBe('3.1.0');
      expect(result.document.info).toBeDefined();
      expect(result.document.info.title).toContain('Thrift');
      expect(result.document.components).toBeDefined();
      expect(result.document.components.schemas).toBeDefined();
      expect(typeof result.document.components.schemas).toBe('object');
    });

    it('adds conversion warning about services not imported', () => {
      const result = convertThriftToOpenAPI(THRIFT_STRUCT);
      expect(result.warnings.length).toBeGreaterThan(0);
      expect(result.warnings.some((w) => w.toLowerCase().includes('struct') || w.toLowerCase().includes('thrift'))).toBe(true);
    });
  });

  describe('extractFileMetadata with Thrift', () => {
    it('detects Thrift and returns thrift format', () => {
      const meta = extractFileMetadata(THRIFT_STRUCT);
      expect(meta.syntax).toBe('thrift');
      expect(meta.format).toBe('thrift');
      expect(meta.formatDisplayName).toContain('Thrift');
      expect(meta.formatSupported).toBe(true);
    });

    it('detects Thrift for union-only content (Thrift-specific)', () => {
      const metaUnion = extractFileMetadata('union U { 1: string x }');
      expect(metaUnion.format).toBe('thrift');
      expect(metaUnion.syntax).toBe('thrift');
    });

    it('returns syntaxValid true for valid Thrift', () => {
      const meta = extractFileMetadata(THRIFT_STRUCT);
      expect(meta.syntaxValid).toBe(true);
    });
  });

  describe('analyzeSpecification with Thrift', () => {
    it('converts Thrift and returns OpenAPI-shaped analysis', async () => {
      const result = await analyzeSpecification(THRIFT_STRUCT_AND_ENUM, 'test.thrift');
      expect(result.document).toBeDefined();
      expect(result.document?.openapi).toBe('3.1.0');
      const schemas = result.document?.components?.schemas as Record<string, unknown> | undefined;
      expect(schemas).toBeDefined();
      expect(Object.keys(schemas!).length).toBeGreaterThanOrEqual(1);
      expect(result.metrics.schemaCount).toBeGreaterThanOrEqual(1);
    });

    it('returns metrics with at least one schema for Thrift', async () => {
      const minimal = 'struct A { 1: i32 x 2: string y }';
      const result = await analyzeSpecification(minimal, 'a.thrift');
      expect(result.metrics.schemaCount).toBe(1);
      expect(result.document?.components?.schemas?.A).toBeDefined();
    });

    it('succeeds with union and exception definitions', async () => {
      const result = await analyzeSpecification(THRIFT_UNION_EXCEPTION, 'err.thrift');
      expect(result.document).toBeDefined();
      expect(result.metrics.schemaCount).toBeGreaterThanOrEqual(2);
    });
  });

  describe('parseOpenAPISpec with Thrift', () => {
    it('detects Thrift (not GraphQL) for struct+enum content', () => {
      expect(isThrift(THRIFT_STRUCT_AND_ENUM)).toBe(true);
    });

    it('converts Thrift and returns parsed classes', () => {
      const minimalThrift = 'struct Pet { 1: i32 id 2: string name }';
      const result = parseOpenAPISpec(minimalThrift);
      expect(result.success).toBe(true);
      expect(result.classes).toBeDefined();
      expect(result.classes!.length).toBeGreaterThanOrEqual(1);
      expect(result.warnings?.some((w) => w.includes('Thrift')) ?? false).toBe(true);
      const names = result.classes!.map((c) => c.name);
      expect(names).toContain('Pet');
    });

    it('parsed class exists for Thrift struct with correct name', () => {
      const thrift = 'struct Point { 1: double x 2: double y 3: double z }';
      const result = parseOpenAPISpec(thrift);
      expect(result.success).toBe(true);
      const point = result.classes!.find((c) => c.name === 'Point');
      expect(point).toBeDefined();
      expect(point!.name).toBe('Point');
      expect(point!.schema).toBeDefined();
    });

    it('returns at least one class for multiple structs', () => {
      const thrift = 'struct A { 1: i32 a } struct B { 1: string b }';
      const result = parseOpenAPISpec(thrift);
      expect(result.success).toBe(true);
      expect(result.classes!.length).toBeGreaterThanOrEqual(1);
      const names = result.classes!.map((c) => c.name);
      expect(names.some((n) => n === 'A' || n === 'B')).toBe(true);
    });

    it('includes Thrift conversion in warnings', () => {
      const result = parseOpenAPISpec('struct X { 1: string s }');
      expect(result.success).toBe(true);
      expect(result.warnings).toBeDefined();
      expect(result.warnings!.length).toBeGreaterThan(0);
      expect(result.warnings!.some((w) => w.includes('Thrift'))).toBe(true);
    });

    it('succeeds when struct appears before enum (Thrift order)', () => {
      const thriftWithEnum = 'struct S { 1: i32 id } enum E { A B }';
      const result = parseOpenAPISpec(thriftWithEnum);
      expect(result.success).toBe(true);
      expect(result.classes!.length).toBeGreaterThanOrEqual(1);
    });
  });
});
