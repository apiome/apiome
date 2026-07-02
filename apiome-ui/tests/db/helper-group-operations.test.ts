/**
 * Unit tests for group-level helper functions (#156):
 * - duplicateClassesInGroup
 * - bulkApplyEditsToGroupClasses
 */

import { describe, test, expect, jest, beforeEach } from '@jest/globals';

// Mock the database connection pool
jest.mock('../../lib/db/db', () => ({
  query: jest.fn(),
  connect: jest.fn(),
}));

// Mock auth/server-session so 'use server' functions can be imported in tests
jest.mock('../../lib/auth/server-session', () => ({
  getAuthSession: jest.fn().mockResolvedValue({ user: { id: 'test-user' } }),
}));

describe('duplicateClassesInGroup', () => {
  let mockDb: any;
  let mockClient: any;

  beforeEach(() => {
    jest.resetModules();
    mockDb = require('../../lib/db/db');
    mockClient = {
      query: jest.fn(),
      release: jest.fn(),
    };
    mockDb.connect = jest.fn().mockResolvedValue(mockClient);
    mockDb.query = jest.fn();
  });

  test('returns empty idMap for empty sourceClassIds', async () => {
    const { duplicateClassesInGroup } = await import('../../lib/db/helper');
    const result = JSON.parse(await duplicateClassesInGroup('ver-1', []));
    expect(result.success).toBe(true);
    expect(result.idMap).toEqual({});
    // Should NOT begin a transaction for empty input
    expect(mockClient.query).not.toHaveBeenCalled();
  });

  test('returns error when class not found in version', async () => {
    const { duplicateClassesInGroup } = await import('../../lib/db/helper');

    // BEGIN, then classesResult returns 0 rows (mismatch)
    mockClient.query
      .mockResolvedValueOnce(undefined) // BEGIN
      .mockResolvedValueOnce({ rowCount: 0, rows: [] }); // SELECT classes

    const result = JSON.parse(await duplicateClassesInGroup('ver-1', ['missing-id']));
    expect(result.success).toBe(false);
    expect(result.error).toMatch(/not found/i);
    // Should ROLLBACK on mismatch
    expect(mockClient.query).toHaveBeenCalledWith('ROLLBACK');
  });

  test('duplicates a single class with properties and commits', async () => {
    const { duplicateClassesInGroup } = await import('../../lib/db/helper');

    mockClient.query
      .mockResolvedValueOnce(undefined) // BEGIN
      .mockResolvedValueOnce({         // SELECT classes
        rowCount: 1,
        rows: [{ id: 'c1', name: 'Foo', description: 'desc', schema: '{"type":"object"}', enabled: true }],
      })
      .mockResolvedValueOnce({ rows: [{ name: 'Foo' }] }) // SELECT existing names
      .mockResolvedValueOnce({ rows: [{ id: 'c2' }] })   // INSERT new class
      .mockResolvedValueOnce({ rows: [] })                 // SELECT class_properties
      .mockResolvedValueOnce(undefined)                    // INSERT class_tags
      .mockResolvedValueOnce(undefined);                   // COMMIT

    const result = JSON.parse(await duplicateClassesInGroup('ver-1', ['c1']));
    expect(result.success).toBe(true);
    expect(result.idMap['c1']).toBe('c2');
    expect(mockClient.query).toHaveBeenCalledWith('COMMIT');
    expect(mockClient.release).toHaveBeenCalled();
  });

  test('rewrites $ref in property data to new class names', async () => {
    const { duplicateClassesInGroup } = await import('../../lib/db/helper');

    mockClient.query
      .mockResolvedValueOnce(undefined) // BEGIN
      .mockResolvedValueOnce({         // SELECT classes (two classes: Foo and Bar)
        rowCount: 2,
        rows: [
          { id: 'c1', name: 'Foo', description: null, schema: '{}', enabled: true },
          { id: 'c2', name: 'Bar', description: null, schema: '{}', enabled: true },
        ],
      })
      .mockResolvedValueOnce({ rows: [{ name: 'Foo' }, { name: 'Bar' }] }) // existing names
      // Insert Foo Copy
      .mockResolvedValueOnce({ rows: [{ id: 'c3' }] })
      // SELECT properties for c1 (one property referencing Bar)
      .mockResolvedValueOnce({
        rows: [{ id: 'p1', property_id: null, name: 'ref', description: null,
                 data: JSON.stringify({ $ref: '#/components/schemas/Bar' }), parent_id: null }],
      })
      // INSERT property copy
      .mockResolvedValueOnce({ rows: [{ id: 'p2' }] })
      // INSERT class_tags for c1
      .mockResolvedValueOnce(undefined)
      // Insert Bar Copy
      .mockResolvedValueOnce({ rows: [{ id: 'c4' }] })
      // SELECT properties for c2 (no properties)
      .mockResolvedValueOnce({ rows: [] })
      // INSERT class_tags for c2
      .mockResolvedValueOnce(undefined)
      // COMMIT
      .mockResolvedValueOnce(undefined);

    const result = JSON.parse(await duplicateClassesInGroup('ver-1', ['c1', 'c2']));
    expect(result.success).toBe(true);
    expect(result.idMap['c1']).toBe('c3');
    expect(result.idMap['c2']).toBe('c4');

    // Find the INSERT property call and verify the $ref was rewritten
    const insertPropCall = mockClient.query.mock.calls.find(
      (c: any[]) => typeof c[0] === 'string' && c[0].includes('INSERT INTO apiome.class_properties')
    );
    expect(insertPropCall).toBeDefined();
    const insertedData = JSON.parse(insertPropCall![1][4]);
    expect(insertedData.$ref).toContain('Bar Copy');
  });

  test('rolls back and returns error on database failure', async () => {
    const { duplicateClassesInGroup } = await import('../../lib/db/helper');

    mockClient.query
      .mockResolvedValueOnce(undefined) // BEGIN
      .mockRejectedValueOnce(new Error('DB error')); // SELECT classes throws

    const result = JSON.parse(await duplicateClassesInGroup('ver-1', ['c1']));
    expect(result.success).toBe(false);
    expect(result.error).toBe('DB error');
    expect(mockClient.query).toHaveBeenCalledWith('ROLLBACK');
    expect(mockClient.release).toHaveBeenCalled();
  });
});

describe('bulkApplyEditsToGroupClasses', () => {
  let mockDb: any;

  beforeEach(() => {
    jest.resetModules();
    mockDb = require('../../lib/db/db');
    mockDb.query = jest.fn();
    mockDb.connect = jest.fn();
  });

  test('returns success for empty classIds', async () => {
    const { bulkApplyEditsToGroupClasses } = await import('../../lib/db/helper');
    const result = JSON.parse(await bulkApplyEditsToGroupClasses('ver-1', [], {}));
    expect(result.success).toBe(true);
    expect(mockDb.query).not.toHaveBeenCalled();
  });

  test('rejects class IDs that do not belong to the version', async () => {
    const { bulkApplyEditsToGroupClasses } = await import('../../lib/db/helper');

    // Ownership check returns empty (no classes belong to version)
    mockDb.query.mockResolvedValueOnce({ rows: [] });

    const result = JSON.parse(
      await bulkApplyEditsToGroupClasses('ver-1', ['c1', 'c2'], { descriptionPrefix: 'prefix-' })
    );
    expect(result.success).toBe(false);
    expect(result.error).toMatch(/No valid class IDs/i);
  });

  test('applies description prefix/suffix only to valid (owned) classes', async () => {
    const { bulkApplyEditsToGroupClasses } = await import('../../lib/db/helper');

    // Ownership check: c1 is owned, c2 is not
    mockDb.query
      .mockResolvedValueOnce({ rows: [{ id: 'c1' }] })   // ownership check
      .mockResolvedValueOnce({                             // SELECT class for c1
        rowCount: 1,
        rows: [{ id: 'c1', name: 'Foo', description: 'original', schema: '{"type":"object"}' }],
      })
      // updateClass internals: SELECT old name, UPDATE, SELECT updated refs…
      .mockResolvedValue({ rows: [{ id: 'c1', name: 'Foo', version_id: 'ver-1' }] });

    const result = JSON.parse(
      await bulkApplyEditsToGroupClasses('ver-1', ['c1', 'c2'], { descriptionPrefix: '[TEST] ' })
    );
    expect(result.success).toBe(true);
    // Only 1 class was valid (c1); ownership query should have been called
    const ownershipCall = mockDb.query.mock.calls[0];
    expect(ownershipCall[0]).toContain('version_id = $1');
  });

  test('wraps readOnly updates in a transaction (BEGIN/COMMIT)', async () => {
    const { bulkApplyEditsToGroupClasses } = await import('../../lib/db/helper');

    mockDb.query
      .mockResolvedValueOnce({ rows: [{ id: 'c1' }] })  // ownership
      .mockResolvedValueOnce(undefined)                   // BEGIN
      .mockResolvedValueOnce({                            // SELECT class_properties
        rows: [{ id: 'p1', data: '{"type":"string"}' }],
      })
      .mockResolvedValueOnce(undefined)                   // UPDATE class_properties
      .mockResolvedValueOnce(undefined);                  // COMMIT

    const result = JSON.parse(
      await bulkApplyEditsToGroupClasses('ver-1', ['c1'], { topLevelPropertyReadOnly: true })
    );
    expect(result.success).toBe(true);

    const calls = mockDb.query.mock.calls.map((c: any[]) => c[0]);
    expect(calls).toContain('BEGIN');
    expect(calls).toContain('COMMIT');

    // Verify readOnly was set in the UPDATE
    const updateCall = mockDb.query.mock.calls.find(
      (c: any[]) => typeof c[0] === 'string' && c[0].includes('UPDATE apiome.class_properties')
    );
    expect(updateCall).toBeDefined();
    const updatedData = JSON.parse(updateCall![1][0]);
    expect(updatedData.readOnly).toBe(true);
  });

  test('rolls back readOnly updates on failure', async () => {
    const { bulkApplyEditsToGroupClasses } = await import('../../lib/db/helper');

    mockDb.query
      .mockResolvedValueOnce({ rows: [{ id: 'c1' }] }) // ownership
      .mockResolvedValueOnce(undefined)                  // BEGIN
      .mockRejectedValueOnce(new Error('DB failure'));   // SELECT class_properties throws

    const result = JSON.parse(
      await bulkApplyEditsToGroupClasses('ver-1', ['c1'], { topLevelPropertyReadOnly: false })
    );
    expect(result.success).toBe(false);
    expect(result.error).toBe('DB failure');

    const calls = mockDb.query.mock.calls.map((c: any[]) => c[0]);
    expect(calls).toContain('ROLLBACK');
  });

  test('removes readOnly flag when topLevelPropertyReadOnly is false', async () => {
    const { bulkApplyEditsToGroupClasses } = await import('../../lib/db/helper');

    mockDb.query
      .mockResolvedValueOnce({ rows: [{ id: 'c1' }] })
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce({
        rows: [{ id: 'p1', data: '{"type":"string","readOnly":true}' }],
      })
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce(undefined);

    const result = JSON.parse(
      await bulkApplyEditsToGroupClasses('ver-1', ['c1'], { topLevelPropertyReadOnly: false })
    );
    expect(result.success).toBe(true);

    const updateCall = mockDb.query.mock.calls.find(
      (c: any[]) => typeof c[0] === 'string' && c[0].includes('UPDATE apiome.class_properties')
    );
    const updatedData = JSON.parse(updateCall![1][0]);
    expect(updatedData.readOnly).toBeUndefined();
  });
});
