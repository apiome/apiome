/**
 * Unit tests for type mismatch detection (#585): incompatible type assignments
 * within a schema (e.g. same property with different types in allOf branches).
 */
import { detectTypeMismatches } from '../../src/app/utils/type-mismatch-detection';

describe('detectTypeMismatches (#585)', () => {
  test('returns empty when no document', () => {
    expect(detectTypeMismatches({ document: null, schemaNames: ['A'] })).toEqual([]);
    expect(detectTypeMismatches({ document: undefined, schemaNames: ['A'] })).toEqual([]);
  });

  test('returns empty when schemaNames is empty', () => {
    const doc = {
      components: {
        schemas: {
          User: { type: 'object', properties: { id: { type: 'string' } } },
        },
      },
    };
    expect(detectTypeMismatches({ document: doc, schemaNames: [] })).toEqual([]);
  });

  test('returns empty when schema has no conflicting type assignments', () => {
    const doc = {
      components: {
        schemas: {
          User: {
            type: 'object',
            properties: {
              id: { type: 'string' },
              name: { type: 'string' },
            },
          },
        },
      },
    };
    expect(detectTypeMismatches({ document: doc, schemaNames: ['User'] })).toEqual([]);
  });

  test('detects incompatible types for same property in allOf branches', () => {
    const doc = {
      components: {
        schemas: {
          Mixed: {
            type: 'object',
            allOf: [
              { properties: { id: { type: 'string' } } },
              { properties: { id: { type: 'integer' } } },
            ],
          },
        },
      },
    };
    const conflicts = detectTypeMismatches({ document: doc, schemaNames: ['Mixed'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].kind).toBe('type_mismatch');
    expect(conflicts[0].schemaName).toBe('Mixed');
    expect(conflicts[0].message).toContain('"id"');
    expect(conflicts[0].message).toContain('incompatible type assignments');
    expect(conflicts[0].detail).toMatch(/string|integer/);
    expect(conflicts[0].impactIfResolved).toBeDefined();
  });

  test('detects top-level property vs allOf branch with different type', () => {
    const doc = {
      components: {
        schemas: {
          Override: {
            type: 'object',
            properties: { code: { type: 'string' } },
            allOf: [{ properties: { code: { type: 'integer' } } }],
          },
        },
      },
    };
    const conflicts = detectTypeMismatches({ document: doc, schemaNames: ['Override'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].kind).toBe('type_mismatch');
    expect(conflicts[0].schemaName).toBe('Override');
    expect(conflicts[0].message).toContain('"code"');
    expect(conflicts[0].detail).toMatch(/string|integer/);
  });

  test('detects array vs non-array for same property', () => {
    const doc = {
      components: {
        schemas: {
          Bad: {
            type: 'object',
            properties: { tags: { type: 'string' } },
            allOf: [{ properties: { tags: { type: 'array', items: { type: 'string' } } } }],
          },
        },
      },
    };
    const conflicts = detectTypeMismatches({ document: doc, schemaNames: ['Bad'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].kind).toBe('type_mismatch');
    expect(conflicts[0].message).toContain('"tags"');
    expect(conflicts[0].detail).toMatch(/string|array/);
  });

  test('detects array<X> vs array<Y> for same property', () => {
    const doc = {
      components: {
        schemas: {
          Bad: {
            type: 'object',
            allOf: [
              { properties: { ids: { type: 'array', items: { type: 'string' } } } },
              { properties: { ids: { type: 'array', items: { type: 'integer' } } } },
            ],
          },
        },
      },
    };
    const conflicts = detectTypeMismatches({ document: doc, schemaNames: ['Bad'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].kind).toBe('type_mismatch');
    expect(conflicts[0].message).toContain('"ids"');
    expect(conflicts[0].detail).toMatch(/string|integer/);
  });

  test('detects $ref vs primitive type for same property', () => {
    const doc = {
      components: {
        schemas: {
          Bad: {
            type: 'object',
            properties: { ref: { $ref: '#/components/schemas/Other' } },
            allOf: [{ properties: { ref: { type: 'string' } } }],
          },
          Other: { type: 'object', properties: {} },
        },
      },
    };
    const conflicts = detectTypeMismatches({ document: doc, schemaNames: ['Bad'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].kind).toBe('type_mismatch');
    expect(conflicts[0].schemaName).toBe('Bad');
    expect(conflicts[0].message).toContain('"ref"');
    expect(conflicts[0].detail).toMatch(/\$ref|string|Other/);
  });

  test('no conflict when same property has same type in multiple branches', () => {
    const doc = {
      components: {
        schemas: {
          Same: {
            type: 'object',
            properties: { id: { type: 'string' } },
            allOf: [
              { properties: { id: { type: 'string' } } },
              { properties: { name: { type: 'string' } } },
            ],
          },
        },
      },
    };
    const conflicts = detectTypeMismatches({ document: doc, schemaNames: ['Same'] });
    expect(conflicts).toEqual([]);
  });

  test('multiple properties with type mismatch yield one conflict per property', () => {
    const doc = {
      components: {
        schemas: {
          Multi: {
            type: 'object',
            allOf: [
              {
                properties: {
                  a: { type: 'string' },
                  b: { type: 'integer' },
                  c: { type: 'boolean' },
                },
              },
              {
                properties: {
                  a: { type: 'integer' },
                  b: { type: 'string' },
                  c: { type: 'number' },
                },
              },
            ],
          },
        },
      },
    };
    const conflicts = detectTypeMismatches({ document: doc, schemaNames: ['Multi'] });
    expect(conflicts).toHaveLength(3);
    const messages = conflicts.map((c) => c.message);
    expect(messages.some((m) => m.includes('"a"'))).toBe(true);
    expect(messages.some((m) => m.includes('"b"'))).toBe(true);
    expect(messages.some((m) => m.includes('"c"'))).toBe(true);
    expect(conflicts.every((c) => c.kind === 'type_mismatch' && c.schemaName === 'Multi')).toBe(true);
  });

  test('multiple schemas: only those with type mismatches are reported', () => {
    const doc = {
      components: {
        schemas: {
          Good: { type: 'object', properties: { x: { type: 'string' } } },
          Bad: {
            type: 'object',
            allOf: [
              { properties: { x: { type: 'string' } } },
              { properties: { x: { type: 'integer' } } },
            ],
          },
        },
      },
    };
    const conflicts = detectTypeMismatches({
      document: doc,
      schemaNames: ['Good', 'Bad'],
    });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].schemaName).toBe('Bad');
  });

  test('uses definitions when document has definitions (OpenAPI 2)', () => {
    const doc = {
      definitions: {
        Legacy: {
          type: 'object',
          properties: { k: { type: 'string' } },
          allOf: [{ properties: { k: { type: 'integer' } } }],
        },
      },
    };
    const conflicts = detectTypeMismatches({ document: doc, schemaNames: ['Legacy'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].schemaName).toBe('Legacy');
    expect(conflicts[0].message).toContain('"k"');
  });

  test('each conflict has required ImportConflict shape', () => {
    const doc = {
      components: {
        schemas: {
          S: {
            type: 'object',
            allOf: [
              { properties: { p: { type: 'string' } } },
              { properties: { p: { type: 'integer' } } },
            ],
          },
        },
      },
    };
    const conflicts = detectTypeMismatches({ document: doc, schemaNames: ['S'] });
    expect(conflicts).toHaveLength(1);
    const c = conflicts[0];
    expect(c).toMatchObject({
      kind: 'type_mismatch',
      schemaName: 'S',
    });
    expect(typeof c.message).toBe('string');
    expect(c.message.length).toBeGreaterThan(0);
    expect(c.detail).toBeDefined();
    expect(c.impactIfResolved).toBeDefined();
  });

  test('skips allOf entries that are $ref only', () => {
    const doc = {
      components: {
        schemas: {
          WithRef: {
            type: 'object',
            properties: { id: { type: 'string' } },
            allOf: [
              { $ref: '#/components/schemas/Base' },
              { properties: { id: { type: 'string' } } },
            ],
          },
          Base: { type: 'object', properties: {} },
        },
      },
    };
    const conflicts = detectTypeMismatches({ document: doc, schemaNames: ['WithRef'] });
    expect(conflicts).toEqual([]);
  });

  test('skips schema names that are not in the document', () => {
    const doc = {
      components: {
        schemas: {
          Present: {
            type: 'object',
            allOf: [
              { properties: { x: { type: 'string' } } },
              { properties: { x: { type: 'integer' } } },
            ],
          },
        },
      },
    };
    const conflicts = detectTypeMismatches({
      document: doc,
      schemaNames: ['Present', 'Missing'],
    });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].schemaName).toBe('Present');
  });

  test('detects same type with different format as incompatible', () => {
    const doc = {
      components: {
        schemas: {
          Formatted: {
            type: 'object',
            properties: { id: { type: 'string' } },
            allOf: [{ properties: { id: { type: 'string', format: 'uuid' } } }],
          },
        },
      },
    };
    const conflicts = detectTypeMismatches({ document: doc, schemaNames: ['Formatted'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].kind).toBe('type_mismatch');
    expect(conflicts[0].message).toContain('"id"');
  });

  test('detects number vs integer', () => {
    const doc = {
      components: {
        schemas: {
          Num: {
            type: 'object',
            allOf: [
              { properties: { value: { type: 'number' } } },
              { properties: { value: { type: 'integer' } } },
            ],
          },
        },
      },
    };
    const conflicts = detectTypeMismatches({ document: doc, schemaNames: ['Num'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].message).toContain('"value"');
    expect(conflicts[0].detail).toMatch(/number|integer/);
  });

  test('detects object vs string for same property', () => {
    const doc = {
      components: {
        schemas: {
          Obj: {
            type: 'object',
            allOf: [
              { properties: { payload: { type: 'object' } } },
              { properties: { payload: { type: 'string' } } },
            ],
          },
        },
      },
    };
    const conflicts = detectTypeMismatches({ document: doc, schemaNames: ['Obj'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].message).toContain('"payload"');
    expect(conflicts[0].detail).toMatch(/object|string/);
  });

  test('detects missing type (any) vs explicit type', () => {
    const doc = {
      components: {
        schemas: {
          Any: {
            type: 'object',
            properties: { flex: {} },
            allOf: [{ properties: { flex: { type: 'string' } } }],
          },
        },
      },
    };
    const conflicts = detectTypeMismatches({ document: doc, schemaNames: ['Any'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].message).toContain('"flex"');
  });

  test('detail truncates when more than 4 distinct types', () => {
    const doc = {
      components: {
        schemas: {
          Many: {
            type: 'object',
            allOf: [
              { properties: { x: { type: 'string' } } },
              { properties: { x: { type: 'integer' } } },
              { properties: { x: { type: 'boolean' } } },
              { properties: { x: { type: 'number' } } },
              { properties: { x: { type: 'array', items: { type: 'string' } } } },
            ],
          },
        },
      },
    };
    const conflicts = detectTypeMismatches({ document: doc, schemaNames: ['Many'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].detail).toMatch(/and \d+ more/);
  });

  test('skips allOf entries with if (conditional schema)', () => {
    const doc = {
      components: {
        schemas: {
          Conditional: {
            type: 'object',
            properties: { id: { type: 'string' } },
            allOf: [
              { if: { type: 'object' }, then: { properties: { id: { type: 'integer' } } } },
              { properties: { id: { type: 'string' } } },
            ],
          },
        },
      },
    };
    const conflicts = detectTypeMismatches({ document: doc, schemaNames: ['Conditional'] });
    expect(conflicts).toEqual([]);
  });

  test('returns empty for schema with no properties and no allOf', () => {
    const doc = {
      components: {
        schemas: {
          Empty: { type: 'object' },
        },
      },
    };
    expect(detectTypeMismatches({ document: doc, schemaNames: ['Empty'] })).toEqual([]);
  });

  test('returns empty for schema with empty allOf', () => {
    const doc = {
      components: {
        schemas: {
          NoProps: { type: 'object', allOf: [{ type: 'object' }] },
        },
      },
    };
    expect(detectTypeMismatches({ document: doc, schemaNames: ['NoProps'] })).toEqual([]);
  });

  test('TypeMismatchInput is accepted with document and schemaNames', () => {
    const doc = { components: { schemas: {} } };
    expect(() =>
      detectTypeMismatches({ document: doc, schemaNames: ['A'] })
    ).not.toThrow();
  });
});
