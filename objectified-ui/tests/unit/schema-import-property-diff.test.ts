import {
  computeSchemaPropertyDiff,
  schemaSnippet,
} from '../../src/app/utils/schema-import-property-diff';

describe('schema-import-property-diff (#298)', () => {
  test('detects added, removed, and modified properties', () => {
    const existing = {
      type: 'object',
      properties: {
        id: { type: 'integer', format: 'int64' },
        name: { type: 'string' },
        category: { $ref: '#/components/schemas/Category' },
        legacyTag: { type: 'string' },
      },
    };
    const imported = {
      type: 'object',
      properties: {
        id: { type: 'integer', format: 'int64' },
        name: { type: 'string' },
        status: { type: 'string', enum: ['available', 'pending'] },
        category: {
          $ref: '#/components/schemas/Category',
          description: 'Pet category',
        },
      },
    };

    const { rows, addedCount, modifiedCount, removedCount } = computeSchemaPropertyDiff(
      existing,
      imported
    );

    expect(addedCount).toBe(1);
    expect(modifiedCount).toBe(1);
    expect(removedCount).toBe(1);

    const byName = Object.fromEntries(rows.map((r) => [r.name, r.status]));
    expect(byName.id).toBe('unchanged');
    expect(byName.name).toBe('unchanged');
    expect(byName.status).toBe('added');
    expect(byName.category).toBe('modified');
    expect(byName.legacyTag).toBe('removed');
  });

  test('empty schemas yield empty diff', () => {
    const r = computeSchemaPropertyDiff({}, {});
    expect(r.rows).toEqual([]);
    expect(r.addedCount).toBe(0);
    expect(r.modifiedCount).toBe(0);
    expect(r.removedCount).toBe(0);
  });

  test('schemaSnippet truncates long JSON', () => {
    const big = { x: 'y'.repeat(2000) };
    const s = schemaSnippet(big, 100);
    expect(s.length).toBeLessThanOrEqual(104);
    expect(s).toContain('…');
  });
});
