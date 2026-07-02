/**
 * Unit tests for schema-diff utility
 * Tests the comparison logic for OpenAPI schema differences
 */

import {
  compareSchemas,
  buildClassLevelDiff,
  compactJsonValue,
  formatClassDiffStatLines,
  formatPropertyDiffLine,
  getClassChangeDiffs,
  getPathLabel,
  groupSchemaConflictPathsByClass,
} from '../../lib/schema-diff';

describe('Schema Diff Utility', () => {
  describe('compareSchemas', () => {
    it('should detect added classes', () => {
      const spec1 = {
        openapi: '3.1.0',
        components: {
          schemas: {
            User: {
              type: 'object',
              properties: {
                id: { type: 'string' }
              }
            }
          }
        }
      };

      const spec2 = {
        openapi: '3.1.0',
        components: {
          schemas: {
            User: {
              type: 'object',
              properties: {
                id: { type: 'string' }
              }
            },
            Product: {
              type: 'object',
              properties: {
                name: { type: 'string' }
              }
            }
          }
        }
      };

      const result = compareSchemas(spec1, spec2);

      expect(result.added.length).toBeGreaterThan(0);
      const addedSchema = result.added.find(d => d.path === 'schemas.Product' && d.itemType === 'schema');
      expect(addedSchema).toBeDefined();
      expect(addedSchema?.type).toBe('added');
    });

    it('should detect removed classes', () => {
      const spec1 = {
        openapi: '3.1.0',
        components: {
          schemas: {
            User: {
              type: 'object',
              properties: {
                id: { type: 'string' }
              }
            },
            OldClass: {
              type: 'object',
              properties: {
                data: { type: 'string' }
              }
            }
          }
        }
      };

      const spec2 = {
        openapi: '3.1.0',
        components: {
          schemas: {
            User: {
              type: 'object',
              properties: {
                id: { type: 'string' }
              }
            }
          }
        }
      };

      const result = compareSchemas(spec1, spec2);

      expect(result.removed.length).toBeGreaterThan(0);
      const removedSchema = result.removed.find(d => d.path === 'schemas.OldClass' && d.itemType === 'schema');
      expect(removedSchema).toBeDefined();
      expect(removedSchema?.type).toBe('removed');
    });

    it('should detect added properties', () => {
      const spec1 = {
        openapi: '3.1.0',
        components: {
          schemas: {
            User: {
              type: 'object',
              properties: {
                id: { type: 'string' }
              }
            }
          }
        }
      };

      const spec2 = {
        openapi: '3.1.0',
        components: {
          schemas: {
            User: {
              type: 'object',
              properties: {
                id: { type: 'string' },
                email: { type: 'string', format: 'email' }
              }
            }
          }
        }
      };

      const result = compareSchemas(spec1, spec2);

      const addedProperty = result.added.find(d => d.path === 'schemas.User.properties.email');
      expect(addedProperty).toBeDefined();
      expect(addedProperty?.itemType).toBe('property');
      expect(addedProperty?.type).toBe('added');
    });

    it('should detect removed properties', () => {
      const spec1 = {
        openapi: '3.1.0',
        components: {
          schemas: {
            User: {
              type: 'object',
              properties: {
                id: { type: 'string' },
                deprecated: { type: 'string' }
              }
            }
          }
        }
      };

      const spec2 = {
        openapi: '3.1.0',
        components: {
          schemas: {
            User: {
              type: 'object',
              properties: {
                id: { type: 'string' }
              }
            }
          }
        }
      };

      const result = compareSchemas(spec1, spec2);

      const removedProperty = result.removed.find(d => d.path === 'schemas.User.properties.deprecated');
      expect(removedProperty).toBeDefined();
      expect(removedProperty?.itemType).toBe('property');
      expect(removedProperty?.type).toBe('removed');
    });

    it('should detect modified properties', () => {
      const spec1 = {
        openapi: '3.1.0',
        components: {
          schemas: {
            User: {
              type: 'object',
              properties: {
                age: { type: 'string' }
              }
            }
          }
        }
      };

      const spec2 = {
        openapi: '3.1.0',
        components: {
          schemas: {
            User: {
              type: 'object',
              properties: {
                age: { type: 'number', minimum: 0 }
              }
            }
          }
        }
      };

      const result = compareSchemas(spec1, spec2);

      const modifiedProperty = result.modified.find(d => d.path === 'schemas.User.properties.age');
      expect(modifiedProperty).toBeDefined();
      expect(modifiedProperty?.itemType).toBe('property');
      expect(modifiedProperty?.type).toBe('modified');
      expect(modifiedProperty?.changes).toContain('type');
    });

    it('should detect default and nullable changes on properties', () => {
      const spec1 = {
        openapi: '3.1.0',
        components: {
          schemas: {
            Order: {
              type: 'object',
              properties: {
                total: { type: 'number', default: 0, nullable: false },
              },
            },
          },
        },
      };
      const spec2 = {
        openapi: '3.1.0',
        components: {
          schemas: {
            Order: {
              type: 'object',
              properties: {
                total: { type: 'string', default: '0', nullable: true },
              },
            },
          },
        },
      };
      const result = compareSchemas(spec1, spec2);
      const m = result.modified.find((d) => d.path === 'schemas.Order.properties.total');
      expect(m?.changes).toContain('default');
      expect(m?.changes).toContain('nullable');
      expect(m?.changes).toContain('type');
    });

    it('should detect modified schema with required changes', () => {
      const spec1 = {
        openapi: '3.1.0',
        components: {
          schemas: {
            User: {
              type: 'object',
              required: ['id'],
              properties: {
                id: { type: 'string' },
                email: { type: 'string' }
              }
            }
          }
        }
      };

      const spec2 = {
        openapi: '3.1.0',
        components: {
          schemas: {
            User: {
              type: 'object',
              required: ['id', 'email'],
              properties: {
                id: { type: 'string' },
                email: { type: 'string' }
              }
            }
          }
        }
      };

      const result = compareSchemas(spec1, spec2);

      const modifiedSchema = result.modified.find(d => d.path === 'schemas.User' && d.itemType === 'schema');
      expect(modifiedSchema).toBeDefined();
      expect(modifiedSchema?.changes).toContain('required');
    });
  });

  describe('buildClassLevelDiff', () => {
    it('lists all classes with added/removed/modified/unchanged', () => {
      const spec1 = {
        openapi: '3.1.0',
        components: {
          schemas: {
            Stay: { type: 'object', properties: { id: { type: 'string' } } },
            Gone: { type: 'object', properties: { x: { type: 'string' } } },
          },
        },
      };
      const spec2 = {
        openapi: '3.1.0',
        components: {
          schemas: {
            Stay: {
              type: 'object',
              properties: { id: { type: 'string' }, email: { type: 'string' } },
            },
            NewOne: { type: 'object', properties: { n: { type: 'number' } } },
          },
        },
      };

      const rows = buildClassLevelDiff(spec1, spec2);
      expect(rows.map((r) => r.stableId)).toEqual(['Gone', 'NewOne', 'Stay']);

      const gone = rows.find((r) => r.stableId === 'Gone');
      expect(gone?.status).toBe('removed');

      const neu = rows.find((r) => r.stableId === 'NewOne');
      expect(neu?.status).toBe('added');
      expect(neu?.propertyAdded).toBe(1);

      const stay = rows.find((r) => r.stableId === 'Stay');
      expect(stay?.status).toBe('modified');
      expect(stay?.propertyAdded).toBe(1);
    });
  });

  describe('getClassChangeDiffs', () => {
    it('returns property and schema rows for one class', () => {
      const spec1 = {
        openapi: '3.1.0',
        components: { schemas: { User: { type: 'object', properties: { a: { type: 'string' } } } } },
      };
      const spec2 = {
        openapi: '3.1.0',
        components: {
          schemas: {
            User: {
              type: 'object',
              required: ['a'],
              properties: { a: { type: 'string' }, b: { type: 'string' } },
            },
          },
        },
      };
      const summary = compareSchemas(spec1, spec2);
      const drill = getClassChangeDiffs(summary, 'User');
      expect(drill.some((d) => d.itemType === 'schema')).toBe(true);
      expect(drill.some((d) => d.path.endsWith('.properties.b'))).toBe(true);
    });
  });

  describe('formatClassDiffStatLines', () => {
    it('emits git-style lines', () => {
      const rows = buildClassLevelDiff(
        { openapi: '3.1.0', components: { schemas: { A: { type: 'object', properties: {} } } } },
        { openapi: '3.1.0', components: { schemas: {} } }
      );
      const text = formatClassDiffStatLines(rows, { includeUnchanged: false });
      expect(text).toContain('- A:');
      expect(text).toContain('removed');
    });
  });

  describe('formatPropertyDiffLine', () => {
    it('formats modified property with old → new for changed fields', () => {
      const spec1 = {
        openapi: '3.1.0',
        components: { schemas: { Order: { type: 'object', properties: { total: { type: 'number' } } } } },
      };
      const spec2 = {
        openapi: '3.1.0',
        components: { schemas: { Order: { type: 'object', properties: { total: { type: 'string' } } } } },
      };
      const summary = compareSchemas(spec1, spec2);
      const d = summary.modified.find((x) => x.path === 'schemas.Order.properties.total');
      if (!d) {
        throw new Error('expected modified Order.total');
      }
      const line = formatPropertyDiffLine(d);
      expect(line).toContain('property total:');
      expect(line).toContain('type');
      expect(line).toContain('→');
    });
  });

  describe('groupSchemaConflictPathsByClass', () => {
    it('groups schemas.* paths by component name', () => {
      const g = groupSchemaConflictPathsByClass([
        'schemas.B.properties.y',
        'schemas.A.properties.x',
        'foo.bar',
      ]);
      expect(g.map((x) => x.className)).toEqual(['A', 'B', 'Other']);
      expect(g.find((x) => x.className === 'B')?.paths).toEqual(['schemas.B.properties.y']);
      expect(g.find((x) => x.className === 'Other')?.paths).toEqual(['foo.bar']);
    });
  });

  describe('compactJsonValue', () => {
    it('renders primitives and truncates long strings', () => {
      expect(compactJsonValue(null)).toBe('null');
      expect(compactJsonValue(undefined)).toBe('—');
      expect(compactJsonValue('x'.repeat(200)).endsWith('…"')).toBe(true);
    });
  });

  describe('getPathLabel', () => {
    it('should format schema paths correctly', () => {
      expect(getPathLabel('schemas.User')).toBe('User');
      expect(getPathLabel('schemas.Product')).toBe('Product');
    });

    it('should format property paths correctly', () => {
      expect(getPathLabel('schemas.User.properties.email')).toBe('User.email');
      expect(getPathLabel('schemas.Product.properties.price')).toBe('Product.price');
    });

    it('should return original path for unknown formats', () => {
      expect(getPathLabel('unknown.path')).toBe('unknown.path');
    });
  });

  describe('complex scenarios', () => {
    it('should handle schemas with no components', () => {
      const spec1 = { openapi: '3.1.0' };
      const spec2 = { openapi: '3.1.0' };

      const result = compareSchemas(spec1, spec2);

      expect(result.added.length).toBe(0);
      expect(result.removed.length).toBe(0);
      expect(result.modified.length).toBe(0);
    });

    it('should handle multiple simultaneous changes', () => {
      const spec1 = {
        openapi: '3.1.0',
        components: {
          schemas: {
            User: {
              type: 'object',
              properties: {
                id: { type: 'string' },
                name: { type: 'string' }
              }
            },
            OldClass: {
              type: 'object',
              properties: {
                data: { type: 'string' }
              }
            }
          }
        }
      };

      const spec2 = {
        openapi: '3.1.0',
        components: {
          schemas: {
            User: {
              type: 'object',
              properties: {
                id: { type: 'string' },
                name: { type: 'string' },
                email: { type: 'string' }
              }
            },
            NewClass: {
              type: 'object',
              properties: {
                value: { type: 'number' }
              }
            }
          }
        }
      };

      const result = compareSchemas(spec1, spec2);

      // Should have additions (NewClass and User.email)
      expect(result.added.length).toBeGreaterThan(0);

      // Should have removals (OldClass)
      expect(result.removed.length).toBeGreaterThan(0);

      // User schema should remain (with modifications)
      const userInAdded = result.added.find(d => d.path.includes('User'));
      expect(userInAdded).toBeDefined();
    });
  });
});

