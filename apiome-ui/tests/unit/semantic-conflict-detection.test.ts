/**
 * Unit tests for semantic conflict detection (#586): logically incompatible
 * constraints (e.g. minLength > maxLength, minimum > maximum, empty enum).
 */
import { detectSemanticConflicts } from '../../src/app/utils/semantic-conflict-detection';

describe('detectSemanticConflicts (#586)', () => {
  test('returns empty when no document', () => {
    expect(detectSemanticConflicts({ document: null, schemaNames: ['A'] })).toEqual([]);
    expect(detectSemanticConflicts({ document: undefined, schemaNames: ['A'] })).toEqual([]);
  });

  test('returns empty when schemaNames is empty', () => {
    const doc = {
      components: {
        schemas: {
          User: { type: 'string', minLength: 10, maxLength: 5 },
        },
      },
    };
    expect(detectSemanticConflicts({ document: doc, schemaNames: [] })).toEqual([]);
  });

  test('returns empty when schema has no incompatible constraints', () => {
    const doc = {
      components: {
        schemas: {
          User: {
            type: 'object',
            properties: {
              name: { type: 'string', minLength: 1, maxLength: 100 },
              age: { type: 'integer', minimum: 0, maximum: 150 },
            },
          },
        },
      },
    };
    expect(detectSemanticConflicts({ document: doc, schemaNames: ['User'] })).toEqual([]);
  });

  test('detects minLength > maxLength at root', () => {
    const doc = {
      components: {
        schemas: {
          Bad: { type: 'string', minLength: 10, maxLength: 5 },
        },
      },
    };
    const conflicts = detectSemanticConflicts({ document: doc, schemaNames: ['Bad'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].kind).toBe('semantic_conflict');
    expect(conflicts[0].schemaName).toBe('Bad');
    expect(conflicts[0].message).toContain('incompatible constraints');
    expect(conflicts[0].detail).toMatch(/minLength.*maxLength|10.*5/);
    expect(conflicts[0].impactIfResolved).toBeDefined();
  });

  test('detects minLength > maxLength in property', () => {
    const doc = {
      components: {
        schemas: {
          User: {
            type: 'object',
            properties: {
              code: { type: 'string', minLength: 20, maxLength: 8 },
            },
          },
        },
      },
    };
    const conflicts = detectSemanticConflicts({ document: doc, schemaNames: ['User'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].kind).toBe('semantic_conflict');
    expect(conflicts[0].schemaName).toBe('User');
    expect(conflicts[0].detail).toMatch(/code|minLength|maxLength/);
  });

  test('detects minimum > maximum', () => {
    const doc = {
      components: {
        schemas: {
          Range: {
            type: 'object',
            properties: {
              value: { type: 'integer', minimum: 100, maximum: 50 },
            },
          },
        },
      },
    };
    const conflicts = detectSemanticConflicts({ document: doc, schemaNames: ['Range'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].kind).toBe('semantic_conflict');
    expect(conflicts[0].detail).toMatch(/minimum|maximum|100|50/);
  });

  test('detects exclusiveMinimum >= maximum', () => {
    const doc = {
      components: {
        schemas: {
          Excl: {
            type: 'number',
            exclusiveMinimum: 5,
            maximum: 5,
          },
        },
      },
    };
    const conflicts = detectSemanticConflicts({ document: doc, schemaNames: ['Excl'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].kind).toBe('semantic_conflict');
    expect(conflicts[0].detail).toMatch(/exclusiveMinimum|maximum/);
  });

  test('detects minimum >= exclusiveMaximum', () => {
    const doc = {
      components: {
        schemas: {
          ExclMax: {
            type: 'integer',
            minimum: 10,
            exclusiveMaximum: 10,
          },
        },
      },
    };
    const conflicts = detectSemanticConflicts({ document: doc, schemaNames: ['ExclMax'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].kind).toBe('semantic_conflict');
    expect(conflicts[0].detail).toMatch(/minimum|exclusiveMaximum/);
  });

  test('detects minItems > maxItems', () => {
    const doc = {
      components: {
        schemas: {
          Arr: {
            type: 'array',
            items: { type: 'string' },
            minItems: 5,
            maxItems: 2,
          },
        },
      },
    };
    const conflicts = detectSemanticConflicts({ document: doc, schemaNames: ['Arr'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].kind).toBe('semantic_conflict');
    expect(conflicts[0].detail).toMatch(/minItems|maxItems/);
  });

  test('detects minProperties > maxProperties', () => {
    const doc = {
      components: {
        schemas: {
          Obj: {
            type: 'object',
            minProperties: 4,
            maxProperties: 2,
          },
        },
      },
    };
    const conflicts = detectSemanticConflicts({ document: doc, schemaNames: ['Obj'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].kind).toBe('semantic_conflict');
    expect(conflicts[0].detail).toMatch(/minProperties|maxProperties/);
  });

  test('detects empty enum', () => {
    const doc = {
      components: {
        schemas: {
          Status: {
            type: 'string',
            enum: [],
          },
        },
      },
    };
    const conflicts = detectSemanticConflicts({ document: doc, schemaNames: ['Status'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].kind).toBe('semantic_conflict');
    expect(conflicts[0].detail).toMatch(/enum|empty/);
  });

  test('aggregates multiple issues in one schema', () => {
    const doc = {
      components: {
        schemas: {
          Multi: {
            type: 'object',
            properties: {
              a: { type: 'string', minLength: 5, maxLength: 2 },
              b: { type: 'integer', minimum: 10, maximum: 3 },
            },
          },
        },
      },
    };
    const conflicts = detectSemanticConflicts({ document: doc, schemaNames: ['Multi'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].schemaName).toBe('Multi');
    expect(conflicts[0].detail).toMatch(/minLength|minimum/);
  });

  test('checks nested schemas (items)', () => {
    const doc = {
      components: {
        schemas: {
          List: {
            type: 'array',
            items: {
              type: 'string',
              minLength: 8,
              maxLength: 4,
            },
          },
        },
      },
    };
    const conflicts = detectSemanticConflicts({ document: doc, schemaNames: ['List'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].schemaName).toBe('List');
    expect(conflicts[0].detail).toMatch(/items|minLength|maxLength/);
  });

  test('uses definitions when components.schemas missing (OpenAPI 2)', () => {
    const doc = {
      definitions: {
        Old: { type: 'string', minLength: 10, maxLength: 5 },
      },
    };
    const conflicts = detectSemanticConflicts({ document: doc, schemaNames: ['Old'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].schemaName).toBe('Old');
  });

  test('skips schema names not in document', () => {
    const doc = {
      components: {
        schemas: {
          Present: { type: 'string', minLength: 10, maxLength: 5 },
        },
      },
    };
    const conflicts = detectSemanticConflicts({
      document: doc,
      schemaNames: ['Present', 'Missing'],
    });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].schemaName).toBe('Present');
  });

  test('returns one conflict per schema with issues', () => {
    const doc = {
      components: {
        schemas: {
          A: { type: 'string', minLength: 1, maxLength: 0 },
          B: { type: 'string', enum: [] },
          C: { type: 'object', properties: { x: { type: 'string' } } },
        },
      },
    };
    const conflicts = detectSemanticConflicts({
      document: doc,
      schemaNames: ['A', 'B', 'C'],
    });
    expect(conflicts).toHaveLength(2);
    const names = conflicts.map((c) => c.schemaName).sort();
    expect(names).toEqual(['A', 'B']);
  });

  test('SemanticConflictInput is accepted with document and schemaNames', () => {
    const doc = { components: { schemas: {} } };
    expect(() =>
      detectSemanticConflicts({ document: doc, schemaNames: ['A'] })
    ).not.toThrow();
  });

  test('no conflict when minLength equals maxLength (boundary valid)', () => {
    const doc = {
      components: {
        schemas: {
          Exact: { type: 'string', minLength: 5, maxLength: 5 },
        },
      },
    };
    expect(detectSemanticConflicts({ document: doc, schemaNames: ['Exact'] })).toEqual([]);
  });

  test('no conflict when minimum equals maximum (boundary valid)', () => {
    const doc = {
      components: {
        schemas: {
          Exact: { type: 'integer', minimum: 10, maximum: 10 },
        },
      },
    };
    expect(detectSemanticConflicts({ document: doc, schemaNames: ['Exact'] })).toEqual([]);
  });

  test('detects incompatible constraints inside allOf branch', () => {
    const doc = {
      components: {
        schemas: {
          Composed: {
            type: 'object',
            allOf: [
              { properties: { code: { type: 'string', minLength: 10, maxLength: 3 } } },
            ],
          },
        },
      },
    };
    const conflicts = detectSemanticConflicts({ document: doc, schemaNames: ['Composed'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].kind).toBe('semantic_conflict');
    expect(conflicts[0].schemaName).toBe('Composed');
    expect(conflicts[0].detail).toMatch(/allOf|code|minLength|maxLength/);
  });

  test('detects incompatible constraints inside oneOf branch', () => {
    const doc = {
      components: {
        schemas: {
          Variant: {
            type: 'object',
            oneOf: [
              { properties: { count: { type: 'integer', minimum: 5, maximum: 2 } } },
            ],
          },
        },
      },
    };
    const conflicts = detectSemanticConflicts({ document: doc, schemaNames: ['Variant'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].detail).toMatch(/minimum|maximum/);
  });

  test('detects incompatible constraints in additionalProperties schema', () => {
    const doc = {
      components: {
        schemas: {
          Extras: {
            type: 'object',
            additionalProperties: {
              type: 'string',
              minLength: 6,
              maxLength: 2,
            },
          },
        },
      },
    };
    const conflicts = detectSemanticConflicts({ document: doc, schemaNames: ['Extras'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].schemaName).toBe('Extras');
    expect(conflicts[0].detail).toMatch(/additionalProperties|minLength|maxLength/);
  });

  test('skips $ref-only nodes (no crash, no false positive)', () => {
    const doc = {
      components: {
        schemas: {
          WithRef: {
            type: 'object',
            properties: {
              user: { $ref: '#/components/schemas/User' },
              name: { type: 'string', minLength: 1, maxLength: 100 },
            },
          },
          User: { type: 'object' },
        },
      },
    };
    const conflicts = detectSemanticConflicts({ document: doc, schemaNames: ['WithRef'] });
    expect(conflicts).toEqual([]);
  });

  test('detail truncates when more than 5 issues (and N more)', () => {
    const doc = {
      components: {
        schemas: {
          Many: {
            type: 'object',
            properties: {
              a: { type: 'string', minLength: 10, maxLength: 1 },
              b: { type: 'string', minLength: 10, maxLength: 1 },
              c: { type: 'integer', minimum: 10, maximum: 1 },
              d: { type: 'integer', minimum: 10, maximum: 1 },
              e: { type: 'array', minItems: 10, maxItems: 1 },
              f: { type: 'string', minLength: 10, maxLength: 1 },
            },
          },
        },
      },
    };
    const conflicts = detectSemanticConflicts({ document: doc, schemaNames: ['Many'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].detail).toMatch(/and \d+ more/);
  });

  test('returns empty when document has no components or definitions', () => {
    expect(detectSemanticConflicts({ document: {}, schemaNames: ['X'] })).toEqual([]);
    expect(detectSemanticConflicts({ document: { components: {} }, schemaNames: ['X'] })).toEqual([]);
  });

  test('skips when schema is null or undefined for a listed name', () => {
    const doc = {
      components: {
        schemas: {
          Good: { type: 'string', minLength: 1, maxLength: 10 },
          Missing: undefined,
          Null: null,
        },
      },
    };
    const conflicts = detectSemanticConflicts({
      document: doc,
      schemaNames: ['Good', 'Missing', 'Null'],
    });
    expect(conflicts).toEqual([]);
  });

  test('every conflict has required ImportConflict shape', () => {
    const doc = {
      components: {
        schemas: {
          Bad: { type: 'string', enum: [] },
        },
      },
    };
    const conflicts = detectSemanticConflicts({ document: doc, schemaNames: ['Bad'] });
    expect(conflicts).toHaveLength(1);
    const c = conflicts[0];
    expect(c).toMatchObject({
      kind: 'semantic_conflict',
      schemaName: 'Bad',
    });
    expect(typeof c.message).toBe('string');
    expect(c.message.length).toBeGreaterThan(0);
    expect(c.detail).toBeDefined();
    expect(typeof c.impactIfResolved).toBe('string');
    expect(c.impactIfResolved!.length).toBeGreaterThan(0);
  });

  test('tuple-form items: detects incompatible constraint in one slot', () => {
    const doc = {
      components: {
        schemas: {
          Tuple: {
            type: 'array',
            items: [
              { type: 'string' },
              { type: 'string', minLength: 10, maxLength: 2 },
            ],
          },
        },
      },
    };
    const conflicts = detectSemanticConflicts({ document: doc, schemaNames: ['Tuple'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].schemaName).toBe('Tuple');
    expect(conflicts[0].detail).toMatch(/minLength|maxLength|items/);
  });
});
