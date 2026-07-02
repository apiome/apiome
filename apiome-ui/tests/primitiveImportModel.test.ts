/**
 * Tests for the Primitives import wizard model (#3469).
 *
 * Exercises the pure parsing / request-building / review helpers that back the wizard so the
 * source -> review -> commit flow stays aligned with the REST import pipeline contract.
 */

import {
  parseSchemaContent,
  isStandalonePrimitiveSchema,
  extractPrimitiveNameFromSchema,
  determineCategoryFromSchema,
  extractDefinitions,
  buildImportRequestBody,
  filterResolutions,
  defaultResolutions,
  defaultSelectedNames,
  validateSelection,
  summarizeImportResult,
  describeImportResult,
  sourceKindLabel,
  type ImportOptions,
  type ReviewType,
} from '../src/app/ade/dashboard/primitives/primitiveImportModel';

const baseOptions: ImportOptions = {
  sourceKind: 'json-schema',
  targetNamespace: '',
  mapCoreFormats: true,
  dedupe: true,
};

const reviewType = (overrides: Partial<ReviewType>): ReviewType => ({
  name: 'Type',
  status: 'new',
  valid: true,
  validation_errors: [],
  error: null,
  schema_id: null,
  existing_id: null,
  ref_count: 0,
  unresolved_refs: [],
  allowed_resolutions: [],
  ...overrides,
});

describe('parseSchemaContent', () => {
  it('parses JSON', () => {
    expect(parseSchemaContent('{"a":1}')).toEqual({ a: 1 });
  });

  it('falls back to YAML', () => {
    const parsed = parseSchemaContent('$defs:\n  Email:\n    type: string');
    expect((parsed?.$defs as Record<string, unknown>).Email).toEqual({ type: 'string' });
  });

  it('returns null for non-object content', () => {
    expect(parseSchemaContent('"just a string"')).toBeNull();
    expect(parseSchemaContent('42')).toBeNull();
  });

  it('returns null for unparseable content', () => {
    expect(parseSchemaContent('not: : valid: yaml: {')).toBeNull();
  });
});

describe('isStandalonePrimitiveSchema', () => {
  it('treats a bare type as standalone', () => {
    expect(isStandalonePrimitiveSchema({ type: 'string' })).toBe(true);
    expect(isStandalonePrimitiveSchema({ enum: ['a', 'b'] })).toBe(true);
    expect(isStandalonePrimitiveSchema({ anyOf: [{ const: 'a' }] })).toBe(true);
  });

  it('treats a container as not standalone', () => {
    expect(isStandalonePrimitiveSchema({ $defs: { A: {} } })).toBe(false);
    expect(isStandalonePrimitiveSchema({ definitions: { A: {} } })).toBe(false);
    expect(isStandalonePrimitiveSchema({ types: { A: {} } })).toBe(false);
  });

  it('returns false for a schema with no type indicators', () => {
    expect(isStandalonePrimitiveSchema({ properties: {} })).toBe(false);
  });
});

describe('extractPrimitiveNameFromSchema', () => {
  it('prefers the last $id segment', () => {
    expect(extractPrimitiveNameFromSchema({ $id: 'https://x/iso/percentage', title: 'P' })).toBe('percentage');
  });

  it('slugifies the title when there is no $id', () => {
    expect(extractPrimitiveNameFromSchema({ title: 'ISO 80000-1:2022 Percentage' })).toBe('iso_8000012022_percentage');
  });

  it('falls back to the filename', () => {
    expect(extractPrimitiveNameFromSchema({ type: 'string' }, 'my-type.json')).toBe('my_type');
  });

  it('uses a stable default', () => {
    expect(extractPrimitiveNameFromSchema({ type: 'object' })).toBe('imported_primitive');
  });
});

describe('determineCategoryFromSchema', () => {
  it('reads an explicit type', () => {
    expect(determineCategoryFromSchema({ type: 'number' })).toBe('number');
    expect(determineCategoryFromSchema({ type: ['string', 'null'] })).toBe('string');
  });

  it('infers from anyOf consts', () => {
    expect(determineCategoryFromSchema({ anyOf: [{ const: 'a' }] })).toBe('string');
    expect(determineCategoryFromSchema({ anyOf: [{ const: 1 }] })).toBe('number');
  });

  it('infers from enum', () => {
    expect(determineCategoryFromSchema({ enum: ['a'] })).toBe('string');
  });

  it('defaults to object', () => {
    expect(determineCategoryFromSchema({ properties: {} })).toBe('object');
  });
});

describe('extractDefinitions', () => {
  it('reads $defs and definitions for JSON Schema', () => {
    const defs = extractDefinitions(
      { $defs: { Email: { type: 'string' } }, definitions: { Phone: { type: 'string' } } },
      'json-schema'
    );
    expect(Object.keys(defs).sort()).toEqual(['Email', 'Phone']);
  });

  it('reads the types container for a bundle', () => {
    const defs = extractDefinitions({ types: { Money: { type: 'object' } } }, 'type-def-bundle');
    expect(Object.keys(defs)).toEqual(['Money']);
  });

  it('wraps a standalone JSON Schema under a derived name', () => {
    const defs = extractDefinitions({ $id: 'https://x/email', type: 'string' }, 'json-schema');
    expect(Object.keys(defs)).toEqual(['email']);
  });

  it('does not treat a standalone document as a bundle member', () => {
    // A bundle is expected to be a container; a bare type yields no definitions.
    expect(extractDefinitions({ type: 'string' }, 'type-def-bundle')).toEqual({});
  });
});

describe('buildImportRequestBody', () => {
  it('builds a review body with import_all when no selection is given', () => {
    const body = buildImportRequestBody({ $defs: { A: { type: 'string' } } }, baseOptions, 'file.json');
    expect(body).toMatchObject({
      source_kind: 'json-schema',
      source_label: 'file.json',
      map_core_formats: true,
      dedupe: true,
      import_all: true,
    });
    expect(body.selected_definitions).toBeUndefined();
  });

  it('wraps a standalone schema in $defs', () => {
    const body = buildImportRequestBody({ $id: 'https://x/email', type: 'string' }, baseOptions, 'email');
    expect(body.schema).toEqual({ $defs: { email: { $id: 'https://x/email', type: 'string' } } });
  });

  it('sends a bundle document unwrapped', () => {
    const doc = { types: { Money: { type: 'object' } } };
    const body = buildImportRequestBody(doc, { ...baseOptions, sourceKind: 'type-def-bundle' }, 'bundle.json');
    expect(body.schema).toEqual(doc);
  });

  it('includes selection, resolutions, and namespace on commit', () => {
    const body = buildImportRequestBody(
      { $defs: { A: { type: 'string' }, B: { type: 'number' } } },
      { ...baseOptions, targetNamespace: ' acme/v1 ' },
      'file.json',
      { selectedNames: ['A', 'B'], resolutions: { A: { action: 'overwrite' } } }
    );
    expect(body.import_all).toBe(false);
    expect(body.selected_definitions).toEqual(['A', 'B']);
    expect(body.resolutions).toEqual({ A: { action: 'overwrite' } });
    expect(body.target_namespace).toBe('acme/v1');
  });

  it('omits an empty target namespace', () => {
    const body = buildImportRequestBody({ $defs: { A: {} } }, baseOptions, null);
    expect(body.target_namespace).toBeUndefined();
  });
});

describe('filterResolutions', () => {
  it('keeps only selected names and normalizes rename targets', () => {
    const out = filterResolutions(
      { A: { action: 'overwrite' }, B: { action: 'rename', new_name: ' b2 ' }, C: { action: 'keep' } },
      ['A', 'B']
    );
    expect(out).toEqual({ A: { action: 'overwrite' }, B: { action: 'rename', new_name: 'b2' } });
  });
});

describe('defaultResolutions / defaultSelectedNames', () => {
  const types = [
    reviewType({ name: 'New1', status: 'new' }),
    reviewType({ name: 'Conf1', status: 'conflict', allowed_resolutions: ['keep', 'overwrite', 'rename'] }),
    reviewType({ name: 'Same1', status: 'identical' }),
    reviewType({ name: 'Bad1', status: 'invalid', valid: false }),
  ];

  it('seeds keep for each conflict only', () => {
    expect(defaultResolutions(types)).toEqual({ Conf1: { action: 'keep' } });
  });

  it('selects new and conflict types by default', () => {
    expect(defaultSelectedNames(types).sort()).toEqual(['Conf1', 'New1']);
  });
});

describe('validateSelection', () => {
  const types = [
    reviewType({ name: 'New1', status: 'new' }),
    reviewType({ name: 'Conf1', status: 'conflict' }),
    reviewType({ name: 'Bad1', status: 'invalid', valid: false }),
  ];

  it('requires at least one selection', () => {
    expect(validateSelection([], types, {})).toMatch(/at least one/i);
  });

  it('rejects selecting an invalid type', () => {
    expect(validateSelection(['Bad1'], types, {})).toMatch(/not a valid/i);
  });

  it('requires a new name for a rename resolution', () => {
    expect(validateSelection(['Conf1'], types, { Conf1: { action: 'rename', new_name: '' } })).toMatch(/new name/i);
  });

  it('passes for a valid selection', () => {
    expect(validateSelection(['New1', 'Conf1'], types, { Conf1: { action: 'overwrite' } })).toBeNull();
  });

  it('ignores resolutions for unselected names', () => {
    expect(validateSelection(['New1'], types, { Conf1: { action: 'rename', new_name: '' } })).toBeNull();
  });
});

describe('summarizeImportResult / describeImportResult', () => {
  it('normalizes the REST report into stable arrays', () => {
    const result = summarizeImportResult({
      imported: ['A', 'B'],
      overwritten: ['C'],
      renamed: [{ name: 'D', new_name: 'D2' }],
      identical: ['E'],
      skipped: [{ name: 'F', reason: 'kept' }],
      errors: [{ name: 'G', error: 'boom' }],
      warnings: ['w'],
      import_id: 'imp-1',
    });
    expect(result.imported).toEqual(['A', 'B']);
    expect(result.overwritten).toEqual(['C']);
    expect(result.importId).toBe('imp-1');
  });

  it('defaults missing fields to empty arrays', () => {
    const result = summarizeImportResult({ imported: ['A'] });
    expect(result.overwritten).toEqual([]);
    expect(result.importId).toBeNull();
  });

  it('describes the outcome', () => {
    const result = summarizeImportResult({ imported: ['A', 'B'], overwritten: ['C'], errors: [{ name: 'G' }] });
    expect(describeImportResult(result)).toBe('Imported 2, overwritten 1, 1 error(s)');
  });
});

describe('sourceKindLabel', () => {
  it('labels each kind', () => {
    expect(sourceKindLabel('json-schema')).toBe('JSON Schema');
    expect(sourceKindLabel('type-def-bundle')).toBe('Type-def bundle');
    expect(sourceKindLabel('openapi')).toBe('OpenAPI');
  });
});
