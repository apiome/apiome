/**
 * Unit tests for property conflict detection (#583): incompatible property
 * definitions across schemas in an OpenAPI document.
 */
import { detectPropertyConflicts } from '../../src/app/utils/property-conflict-detection';

describe('detectPropertyConflicts (#583)', () => {
  test('returns empty when no document', () => {
    expect(detectPropertyConflicts({ document: null, schemaNames: ['A'] })).toEqual([]);
    expect(detectPropertyConflicts({ document: undefined, schemaNames: ['A'] })).toEqual([]);
  });

  test('returns empty when schemaNames is empty', () => {
    const doc = {
      components: {
        schemas: {
          User: { type: 'object', properties: { id: { type: 'string' } } },
        },
      },
    };
    expect(detectPropertyConflicts({ document: doc, schemaNames: [] })).toEqual([]);
  });

  test('returns empty when single schema (no cross-schema comparison)', () => {
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
    expect(detectPropertyConflicts({ document: doc, schemaNames: ['User'] })).toEqual([]);
  });

  test('returns empty when same property name has same definition in multiple schemas', () => {
    const doc = {
      components: {
        schemas: {
          Customer: {
            type: 'object',
            properties: {
              id: { type: 'string', format: 'uuid' },
              name: { type: 'string', maxLength: 100 },
            },
          },
          Document: {
            type: 'object',
            properties: {
              id: { type: 'string', format: 'uuid' },
              name: { type: 'string', maxLength: 100 },
            },
          },
        },
      },
    };
    expect(detectPropertyConflicts({ document: doc, schemaNames: ['Customer', 'Document'] })).toEqual([]);
  });

  test('returns one conflict per property name when multiple properties have incompatible definitions', () => {
    const doc = {
      components: {
        schemas: {
          Customer: {
            type: 'object',
            properties: {
              id: { type: 'string', format: 'uuid' },
              status: { type: 'string', enum: ['active', 'inactive'] },
            },
          },
          Transaction: {
            type: 'object',
            properties: {
              id: { type: 'integer', format: 'int64' },
              status: { type: 'string', enum: ['pending', 'completed'] },
            },
          },
        },
      },
    };
    const conflicts = detectPropertyConflicts({ document: doc, schemaNames: ['Customer', 'Transaction'] });
    expect(conflicts).toHaveLength(2); // id and status
    const kinds = conflicts.map((c) => c.kind);
    expect(kinds.every((k) => k === 'property_conflict')).toBe(true);
    const messages = conflicts.map((c) => c.message);
    expect(messages.some((m) => m.includes('"id"'))).toBe(true);
    expect(messages.some((m) => m.includes('"status"'))).toBe(true);
    expect(conflicts[0].schemaName).toBeDefined();
    expect(conflicts[0].detail).toBeDefined();
    expect(conflicts[0].impactIfResolved).toBeDefined();
  });

  test('uses definitions from components.schemas', () => {
    const doc = {
      components: {
        schemas: {
          A: { type: 'object', properties: { x: { type: 'string' } } },
          B: { type: 'object', properties: { x: { type: 'integer' } } },
        },
      },
    };
    const conflicts = detectPropertyConflicts({ document: doc, schemaNames: ['A', 'B'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].message).toContain('"x"');
    expect(conflicts[0].kind).toBe('property_conflict');
  });

  test('uses definitions when document has definitions (OpenAPI 2)', () => {
    const doc = {
      definitions: {
        A: { type: 'object', properties: { p: { type: 'string' } } },
        B: { type: 'object', properties: { p: { type: 'number' } } },
      },
    };
    const conflicts = detectPropertyConflicts({ document: doc, schemaNames: ['A', 'B'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].message).toContain('"p"');
  });

  test('only considers requested schema names', () => {
    const doc = {
      components: {
        schemas: {
          A: { type: 'object', properties: { x: { type: 'string' } } },
          B: { type: 'object', properties: { x: { type: 'integer' } } },
          C: { type: 'object', properties: { x: { type: 'boolean' } } },
        },
      },
    };
    const conflicts = detectPropertyConflicts({ document: doc, schemaNames: ['A'] });
    expect(conflicts).toHaveLength(0);
    const conflictsAB = detectPropertyConflicts({ document: doc, schemaNames: ['A', 'B'] });
    expect(conflictsAB).toHaveLength(1);
    const conflictsAll = detectPropertyConflicts({ document: doc, schemaNames: ['A', 'B', 'C'] });
    expect(conflictsAll).toHaveLength(1);
    expect(conflictsAll[0].detail).toContain('string');
    expect(conflictsAll[0].detail).toContain('integer');
    expect(conflictsAll[0].detail).toContain('boolean');
  });

  test('conflict detail includes schema names and type hints', () => {
    const doc = {
      components: {
        schemas: {
          Customer: { type: 'object', properties: { id: { type: 'string', format: 'uuid' } } },
          Transaction: { type: 'object', properties: { id: { type: 'integer', format: 'int64' } } },
        },
      },
    };
    const conflicts = detectPropertyConflicts({ document: doc, schemaNames: ['Customer', 'Transaction'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].detail).toMatch(/Customer|Transaction/);
    expect(conflicts[0].detail).toMatch(/uuid|int64|string|integer/);
  });

  test('allOf inline properties are included in extraction', () => {
    const doc = {
      components: {
        schemas: {
          A: {
            type: 'object',
            allOf: [
              { properties: { id: { type: 'string' } } },
            ],
          },
          B: {
            type: 'object',
            properties: { id: { type: 'integer' } },
          },
        },
      },
    };
    const conflicts = detectPropertyConflicts({ document: doc, schemaNames: ['A', 'B'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].message).toContain('"id"');
  });

  test('returns empty when document has no components or definitions', () => {
    expect(detectPropertyConflicts({ document: {}, schemaNames: ['A', 'B'] })).toEqual([]);
    expect(detectPropertyConflicts({ document: { components: {} }, schemaNames: ['A'] })).toEqual([]);
    expect(detectPropertyConflicts({ document: { components: { schemas: {} } }, schemaNames: ['A'] })).toEqual([]);
  });

  test('skips schema names that are not in the document', () => {
    const doc = {
      components: {
        schemas: {
          OnlyA: { type: 'object', properties: { x: { type: 'string' } } },
        },
      },
    };
    expect(detectPropertyConflicts({ document: doc, schemaNames: ['OnlyA', 'Missing'] })).toEqual([]);
  });

  test('each conflict has required ImportConflict shape', () => {
    const doc = {
      components: {
        schemas: {
          A: { type: 'object', properties: { p: { type: 'string' } } },
          B: { type: 'object', properties: { p: { type: 'integer' } } },
        },
      },
    };
    const conflicts = detectPropertyConflicts({ document: doc, schemaNames: ['A', 'B'] });
    expect(conflicts).toHaveLength(1);
    const c = conflicts[0];
    expect(c).toMatchObject({
      kind: 'property_conflict',
      schemaName: expect.any(String),
      message: expect.stringContaining('incompatible definitions'),
    });
    expect(c.message).toContain('"p"');
    expect(c.detail).toBeDefined();
    expect(typeof c.detail).toBe('string');
    expect(c.impactIfResolved).toBeDefined();
    expect(c.impactIfResolved).toContain('chosen');
  });

  test('same type and format with different description still produces one definition per description', () => {
    const doc = {
      components: {
        schemas: {
          A: {
            type: 'object',
            properties: {
              id: { type: 'string', format: 'uuid', description: 'Primary key' },
            },
          },
          B: {
            type: 'object',
            properties: {
              id: { type: 'string', format: 'uuid', description: 'Unique ID' },
            },
          },
        },
      },
    };
    const conflicts = detectPropertyConflicts({ document: doc, schemaNames: ['A', 'B'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].message).toContain('"id"');
  });

  test('x- extension keys are ignored so same logical type yields no conflict', () => {
    const doc = {
      components: {
        schemas: {
          A: { type: 'object', properties: { id: { type: 'string', 'x-custom': true } } },
          B: { type: 'object', properties: { id: { type: 'string' } } },
        },
      },
    };
    expect(detectPropertyConflicts({ document: doc, schemaNames: ['A', 'B'] })).toEqual([]);
  });

  test('array type conflict: array of string vs array of integer', () => {
    const doc = {
      components: {
        schemas: {
          A: { type: 'object', properties: { tags: { type: 'array', items: { type: 'string' } } } },
          B: { type: 'object', properties: { tags: { type: 'array', items: { type: 'integer' } } } },
        },
      },
    };
    const conflicts = detectPropertyConflicts({ document: doc, schemaNames: ['A', 'B'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].message).toContain('"tags"');
    expect(conflicts[0].detail).toMatch(/string|integer/);
  });

  test('same $ref in two schemas yields no conflict', () => {
    const doc = {
      components: {
        schemas: {
          A: { type: 'object', properties: { ref: { $ref: '#/components/schemas/Other' } } },
          B: { type: 'object', properties: { ref: { $ref: '#/components/schemas/Other' } } },
          Other: { type: 'object' },
        },
      },
    };
    expect(detectPropertyConflicts({ document: doc, schemaNames: ['A', 'B'] })).toEqual([]);
  });

  test('different $ref for same property name yields conflict', () => {
    const doc = {
      components: {
        schemas: {
          A: { type: 'object', properties: { link: { $ref: '#/components/schemas/Foo' } } },
          B: { type: 'object', properties: { link: { $ref: '#/components/schemas/Bar' } } },
          Foo: { type: 'object' },
          Bar: { type: 'object' },
        },
      },
    };
    const conflicts = detectPropertyConflicts({ document: doc, schemaNames: ['A', 'B'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].message).toContain('"link"');
  });

  test('three schemas with two definitions: one conflict with detail listing all', () => {
    const doc = {
      components: {
        schemas: {
          Customer: { type: 'object', properties: { id: { type: 'string', format: 'uuid' } } },
          Document: { type: 'object', properties: { id: { type: 'string', format: 'uuid' } } },
          Transaction: { type: 'object', properties: { id: { type: 'integer', format: 'int64' } } },
        },
      },
    };
    const conflicts = detectPropertyConflicts({ document: doc, schemaNames: ['Customer', 'Document', 'Transaction'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].message).toContain('"id"');
    expect(conflicts[0].detail).toContain('Customer');
    expect(conflicts[0].detail).toContain('Transaction');
    expect(conflicts[0].detail).toMatch(/uuid|int64/);
  });

  test('multiple conflicting properties return one conflict per property name', () => {
    const doc = {
      components: {
        schemas: {
          X: {
            type: 'object',
            properties: {
              a: { type: 'string' },
              b: { type: 'string' },
              c: { type: 'string' },
            },
          },
          Y: {
            type: 'object',
            properties: {
              a: { type: 'integer' },
              b: { type: 'integer' },
              c: { type: 'integer' },
            },
          },
        },
      },
    };
    const conflicts = detectPropertyConflicts({ document: doc, schemaNames: ['X', 'Y'] });
    expect(conflicts).toHaveLength(3);
    const propNames = conflicts.map((c) => (c.message.match(/"([^"]+)"/) ?? [])[1]).filter(Boolean);
    expect(propNames).toContain('a');
    expect(propNames).toContain('b');
    expect(propNames).toContain('c');
  });

  test('schema with empty properties is ignored for that schema', () => {
    const doc = {
      components: {
        schemas: {
          A: { type: 'object', properties: {} },
          B: { type: 'object', properties: { id: { type: 'integer' } } },
        },
      },
    };
    expect(detectPropertyConflicts({ document: doc, schemaNames: ['A', 'B'] })).toEqual([]);
  });

  test('allOf with $ref item does not add from $ref', () => {
    const doc = {
      components: {
        schemas: {
          A: {
            type: 'object',
            allOf: [
              { $ref: '#/components/schemas/Base' },
              { properties: { id: { type: 'string' } } },
            ],
          },
          B: {
            type: 'object',
            properties: { id: { type: 'integer' } },
          },
          Base: { type: 'object', properties: { name: { type: 'string' } } },
        },
      },
    };
    const conflicts = detectPropertyConflicts({ document: doc, schemaNames: ['A', 'B'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].message).toContain('"id"');
  });

  test('enum difference produces conflict', () => {
    const doc = {
      components: {
        schemas: {
          A: { type: 'object', properties: { status: { type: 'string', enum: ['draft', 'published'] } } },
          B: { type: 'object', properties: { status: { type: 'string', enum: ['open', 'closed'] } } },
        },
      },
    };
    const conflicts = detectPropertyConflicts({ document: doc, schemaNames: ['A', 'B'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].message).toContain('"status"');
    expect(conflicts[0].detail).toMatch(/enum/);
  });
});
