/**
 * Import Verification Tests
 *
 * Tests for the import sanity check that verifies imported data in the database
 * matches the original schema that was imported.
 */

// Utility functions extracted from import-helper for testing
function stableStringify(obj: any): string {
  if (obj === null || obj === undefined) return JSON.stringify(obj);
  if (typeof obj !== 'object') return JSON.stringify(obj);
  if (Array.isArray(obj)) {
    return '[' + obj.map(item => stableStringify(item)).join(',') + ']';
  }
  const sortedKeys = Object.keys(obj).sort();
  const pairs = sortedKeys.map(key => JSON.stringify(key) + ':' + stableStringify(obj[key]));
  return '{' + pairs.join(',') + '}';
}

function normalizePropertyData(data: any): any {
  if (!data || typeof data !== 'object') return data;

  const normalized: any = {};
  const keysToSkip = ['description'];

  for (const key of Object.keys(data).sort()) {
    if (keysToSkip.includes(key)) continue;
    const value = data[key];
    if (value === null || value === undefined) continue;
    if (typeof value === 'object') {
      normalized[key] = normalizePropertyData(value);
    } else {
      normalized[key] = value;
    }
  }

  return normalized;
}

function comparePropertyData(expected: any, actual: any): { match: boolean; diff?: string } {
  const expectedNorm = normalizePropertyData(expected);
  const actualNorm = normalizePropertyData(actual);

  const expectedStr = stableStringify(expectedNorm);
  const actualStr = stableStringify(actualNorm);

  if (expectedStr === actualStr) {
    return { match: true };
  }

  return {
    match: false,
    diff: `Expected: ${expectedStr.substring(0, 200)}... Actual: ${actualStr.substring(0, 200)}...`
  };
}

function buildPropertyTree(properties: any[]): Map<string, any> {
  const byId = new Map<string, any>();
  const roots = new Map<string, any>();

  for (const p of properties) {
    byId.set(p.id, { ...p, children: [] });
  }

  for (const p of properties) {
    const node = byId.get(p.id)!;
    if (p.parent_id && byId.has(p.parent_id)) {
      byId.get(p.parent_id)!.children.push(node);
    } else {
      roots.set(p.name, node);
    }
  }

  return roots;
}

describe('Import Verification', () => {
  describe('stableStringify', () => {
    it('should produce consistent output regardless of key order', () => {
      const obj1 = { b: 2, a: 1, c: 3 };
      const obj2 = { a: 1, c: 3, b: 2 };

      expect(stableStringify(obj1)).toBe(stableStringify(obj2));
    });

    it('should handle nested objects', () => {
      const obj1 = { outer: { b: 2, a: 1 } };
      const obj2 = { outer: { a: 1, b: 2 } };

      expect(stableStringify(obj1)).toBe(stableStringify(obj2));
    });

    it('should handle arrays', () => {
      const obj = { items: [1, 2, 3] };

      expect(stableStringify(obj)).toBe('{"items":[1,2,3]}');
    });

    it('should handle null and undefined', () => {
      expect(stableStringify(null)).toBe('null');
      expect(stableStringify(undefined)).toBe(undefined); // JSON.stringify returns undefined for undefined
    });

    it('should handle primitives', () => {
      expect(stableStringify('hello')).toBe('"hello"');
      expect(stableStringify(42)).toBe('42');
      expect(stableStringify(true)).toBe('true');
    });
  });

  describe('normalizePropertyData', () => {
    it('should remove description field', () => {
      const data = { type: 'string', description: 'A name field' };
      const normalized = normalizePropertyData(data);

      expect(normalized).toEqual({ type: 'string' });
      expect(normalized.description).toBeUndefined();
    });

    it('should remove null and undefined values', () => {
      const data = { type: 'string', format: null, example: undefined, minLength: 1 };
      const normalized = normalizePropertyData(data);

      expect(normalized).toEqual({ minLength: 1, type: 'string' });
    });

    it('should recursively normalize nested objects', () => {
      const data = {
        type: 'object',
        description: 'Should be removed',
        properties: {
          name: { type: 'string', description: 'Also removed' }
        }
      };
      const normalized = normalizePropertyData(data);

      expect(normalized.description).toBeUndefined();
      expect(normalized.properties.name.description).toBeUndefined();
      expect(normalized.properties.name.type).toBe('string');
    });

    it('should handle primitives', () => {
      expect(normalizePropertyData('string')).toBe('string');
      expect(normalizePropertyData(42)).toBe(42);
      expect(normalizePropertyData(null)).toBe(null);
    });
  });

  describe('comparePropertyData', () => {
    it('should return match for identical data', () => {
      const data1 = { type: 'string', minLength: 1 };
      const data2 = { type: 'string', minLength: 1 };

      const result = comparePropertyData(data1, data2);
      expect(result.match).toBe(true);
    });

    it('should return match when only description differs', () => {
      const data1 = { type: 'string', description: 'First description' };
      const data2 = { type: 'string', description: 'Second description' };

      const result = comparePropertyData(data1, data2);
      expect(result.match).toBe(true);
    });

    it('should return mismatch for different types', () => {
      const data1 = { type: 'string' };
      const data2 = { type: 'number' };

      const result = comparePropertyData(data1, data2);
      expect(result.match).toBe(false);
      expect(result.diff).toBeDefined();
    });

    it('should return mismatch for different constraints', () => {
      const data1 = { type: 'string', minLength: 1 };
      const data2 = { type: 'string', minLength: 5 };

      const result = comparePropertyData(data1, data2);
      expect(result.match).toBe(false);
    });

    it('should handle $ref comparisons', () => {
      const data1 = { $ref: '#/components/schemas/User' };
      const data2 = { $ref: '#/components/schemas/User' };

      const result = comparePropertyData(data1, data2);
      expect(result.match).toBe(true);
    });

    it('should detect $ref mismatches', () => {
      const data1 = { $ref: '#/components/schemas/User' };
      const data2 = { $ref: '#/components/schemas/Account' };

      const result = comparePropertyData(data1, data2);
      expect(result.match).toBe(false);
    });
  });

  describe('buildPropertyTree', () => {
    it('should build a tree from flat properties', () => {
      const properties = [
        { id: '1', name: 'address', parent_id: null, data: { type: 'object' } },
        { id: '2', name: 'street', parent_id: '1', data: { type: 'string' } },
        { id: '3', name: 'city', parent_id: '1', data: { type: 'string' } },
        { id: '4', name: 'name', parent_id: null, data: { type: 'string' } },
      ];

      const tree = buildPropertyTree(properties);

      expect(tree.size).toBe(2); // address and name are roots
      expect(tree.has('address')).toBe(true);
      expect(tree.has('name')).toBe(true);

      const addressNode = tree.get('address');
      expect(addressNode.children.length).toBe(2);
      expect(addressNode.children.map((c: any) => c.name).sort()).toEqual(['city', 'street']);
    });

    it('should handle empty properties', () => {
      const tree = buildPropertyTree([]);
      expect(tree.size).toBe(0);
    });

    it('should handle all root properties', () => {
      const properties = [
        { id: '1', name: 'name', parent_id: null, data: { type: 'string' } },
        { id: '2', name: 'email', parent_id: null, data: { type: 'string' } },
      ];

      const tree = buildPropertyTree(properties);

      expect(tree.size).toBe(2);
      expect(tree.get('name').children.length).toBe(0);
      expect(tree.get('email').children.length).toBe(0);
    });

    it('should handle deeply nested properties', () => {
      const properties = [
        { id: '1', name: 'level1', parent_id: null, data: { type: 'object' } },
        { id: '2', name: 'level2', parent_id: '1', data: { type: 'object' } },
        { id: '3', name: 'level3', parent_id: '2', data: { type: 'string' } },
      ];

      const tree = buildPropertyTree(properties);

      expect(tree.size).toBe(1);
      const level1 = tree.get('level1');
      expect(level1.children.length).toBe(1);
      expect(level1.children[0].name).toBe('level2');
      expect(level1.children[0].children.length).toBe(1);
      expect(level1.children[0].children[0].name).toBe('level3');
    });
  });

  describe('Verification Integration', () => {
    it('should verify matching schemas pass', () => {
      // This is a conceptual test - actual integration would need DB
      const expectedClass = {
        name: 'User',
        properties: [
          { name: 'id', data: { type: 'string', format: 'uuid' } },
          { name: 'email', data: { type: 'string', format: 'email' } },
        ]
      };

      // Simulate DB data that matches
      const dbProperties = [
        { id: '1', name: 'id', data: { type: 'string', format: 'uuid' }, parent_id: null },
        { id: '2', name: 'email', data: { type: 'string', format: 'email' }, parent_id: null },
      ];

      const tree = buildPropertyTree(dbProperties);

      let mismatches = 0;
      for (const prop of expectedClass.properties) {
        const dbProp = tree.get(prop.name);
        if (!dbProp) {
          mismatches++;
          continue;
        }
        const result = comparePropertyData(prop.data, dbProp.data);
        if (!result.match) {
          mismatches++;
        }
      }

      expect(mismatches).toBe(0);
    });

    it('should detect missing properties', () => {
      const expectedClass = {
        name: 'User',
        properties: [
          { name: 'id', data: { type: 'string' } },
          { name: 'email', data: { type: 'string' } },
          { name: 'phone', data: { type: 'string' } }, // This is missing
        ]
      };

      const dbProperties = [
        { id: '1', name: 'id', data: { type: 'string' }, parent_id: null },
        { id: '2', name: 'email', data: { type: 'string' }, parent_id: null },
        // phone is missing
      ];

      const tree = buildPropertyTree(dbProperties);

      let missingCount = 0;
      for (const prop of expectedClass.properties) {
        if (!tree.has(prop.name)) {
          missingCount++;
        }
      }

      expect(missingCount).toBe(1);
    });

    it('should detect property type mismatches', () => {
      const expectedProp = { name: 'count', data: { type: 'integer' } };
      const dbProp = { data: { type: 'string' } }; // Wrong type

      const result = comparePropertyData(expectedProp.data, dbProp.data);

      expect(result.match).toBe(false);
    });
  });
});

