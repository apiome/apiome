/**
 * Source-descriptor derivation tests (RAR-1.3, #3514)
 *
 * The descriptor (`format_override`, `content_type`) is persisted at import time
 * so an auto-refresh routes/parses a repository file identically to the first
 * import. These tests pin the format normalization and the syntax → content-type
 * mapping that produce those stored values.
 */

import { describe, test, expect } from '@jest/globals';

import {
  contentTypeForSyntax,
  formatOverrideForFormat,
  deriveRepositoryImportSourceDescriptor,
} from '../lib/repository-import-source-descriptor';

describe('contentTypeForSyntax (RAR-1.3)', () => {
  test.each([
    ['json', 'application/json'],
    ['yaml', 'application/yaml'],
    ['graphql', 'application/graphql'],
    ['protobuf', 'application/x-protobuf'],
    ['thrift', 'application/x-thrift'],
  ])('maps %s syntax to %s', (syntax, expected) => {
    expect(contentTypeForSyntax(syntax)).toBe(expected);
  });

  test('is case- and whitespace-insensitive', () => {
    expect(contentTypeForSyntax('  JSON ')).toBe('application/json');
    expect(contentTypeForSyntax('Yaml')).toBe('application/yaml');
  });

  test('returns null for unrecognized, empty, or missing syntax', () => {
    expect(contentTypeForSyntax('xml')).toBeNull();
    expect(contentTypeForSyntax('')).toBeNull();
    expect(contentTypeForSyntax(null)).toBeNull();
    expect(contentTypeForSyntax(undefined)).toBeNull();
  });
});

describe('formatOverrideForFormat (RAR-1.3)', () => {
  test.each(['openapi', 'swagger', 'arazzo', 'jsonschema', 'asyncapi'])(
    'keeps the resolved format %s',
    (format) => {
      expect(formatOverrideForFormat(format)).toBe(format);
    }
  );

  test('trims surrounding whitespace', () => {
    expect(formatOverrideForFormat('  swagger ')).toBe('swagger');
  });

  test('returns null when the format is unknown, empty, or missing', () => {
    expect(formatOverrideForFormat('unknown')).toBeNull();
    expect(formatOverrideForFormat('UNKNOWN')).toBeNull();
    expect(formatOverrideForFormat('')).toBeNull();
    expect(formatOverrideForFormat('   ')).toBeNull();
    expect(formatOverrideForFormat(null)).toBeNull();
    expect(formatOverrideForFormat(undefined)).toBeNull();
  });
});

describe('deriveRepositoryImportSourceDescriptor (RAR-1.3)', () => {
  test('derives both descriptor fields from a resolved analysis', () => {
    expect(
      deriveRepositoryImportSourceDescriptor({ format: 'openapi', syntax: 'yaml' })
    ).toEqual({ formatOverride: 'openapi', contentType: 'application/yaml' });
  });

  test('captures the granular format distinct from the importer kind (swagger)', () => {
    // A Swagger 2.0 file routes through the OpenAPI importer (source_kind=openapi)
    // but its resolved format is swagger — the descriptor preserves that.
    expect(
      deriveRepositoryImportSourceDescriptor({ format: 'swagger', syntax: 'json' })
    ).toEqual({ formatOverride: 'swagger', contentType: 'application/json' });
  });

  test('yields null fields when format/syntax are unresolved', () => {
    expect(
      deriveRepositoryImportSourceDescriptor({ format: 'unknown', syntax: '' })
    ).toEqual({ formatOverride: null, contentType: null });
  });
});
