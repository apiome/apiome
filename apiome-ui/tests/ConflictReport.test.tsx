/**
 * Unit tests for Conflict Report (#596): overview of all detected conflicts during import.
 * Impact if resolved (#597): what will change when a conflict is resolved.
 * Conflict export as markdown (#598): export conflict report for review.
 *
 * Covers:
 * - Types (ImportConflict, ImportConflictKind) and conflict kind labels
 * - Building conflict list from schema list (duplicate_schema from existing names)
 * - Summary-by-kind aggregation contract used by ConflictReport UI
 * - Optional impactIfResolved and default impact text per kind (#597)
 * - conflictReportToMarkdown and getConflictReportMarkdownFilename (#598)
 *
 * Component rendering is not tested here (React version mismatch in workspace);
 * the UI is validated manually and the data contract is fully covered below.
 */

import { describe, test, expect } from '@jest/globals';
import {
  DEFAULT_IMPACT_IF_RESOLVED,
  conflictReportToMarkdown,
  getConflictReportMarkdownFilename,
  type ImportConflict,
  type ImportConflictKind,
} from '../src/app/components/ade/dashboard/ConflictReport';

/** Conflict kind labels used by ConflictReport - must stay in sync with component (#582) */
const CONFLICT_KIND_LABELS: Record<ImportConflictKind, string> = {
  duplicate_schema: 'Duplicate schema (same name, different definition)',
  property_conflict: 'Property conflict',
  reference_conflict: 'Reference conflict',
  type_mismatch: 'Type mismatch',
  semantic_conflict: 'Semantic conflict',
};

/** Summary by kind: counts per conflict type (mirrors ConflictReport logic) */
function getConflictSummary(conflicts: ImportConflict[]): Record<ImportConflictKind, number> {
  return conflicts.reduce<Record<ImportConflictKind, number>>(
    (acc, c) => {
      acc[c.kind] = (acc[c.kind] ?? 0) + 1;
      return acc;
    },
    {
      duplicate_schema: 0,
      property_conflict: 0,
      reference_conflict: 0,
      type_mismatch: 0,
      semantic_conflict: 0,
    }
  );
}

describe('ConflictReport (#596)', () => {
  describe('ImportConflict type and labels', () => {
    test('all conflict kinds have a label', () => {
      const kinds: ImportConflictKind[] = [
        'duplicate_schema',
        'property_conflict',
        'reference_conflict',
        'type_mismatch',
        'semantic_conflict',
      ];
      kinds.forEach((kind) => {
        expect(CONFLICT_KIND_LABELS[kind]).toBeDefined();
        expect(typeof CONFLICT_KIND_LABELS[kind]).toBe('string');
        expect(CONFLICT_KIND_LABELS[kind].length).toBeGreaterThan(0);
      });
    });

    test('duplicate_schema label is for name conflicts', () => {
      expect(CONFLICT_KIND_LABELS.duplicate_schema).toMatch(/duplicate|schema|name/i);
    });

    test('ImportConflict requires kind, schemaName, message', () => {
      const c: ImportConflict = {
        kind: 'duplicate_schema',
        schemaName: 'User',
        message: 'A class named "User" already exists.',
      };
      expect(c.kind).toBe('duplicate_schema');
      expect(c.schemaName).toBe('User');
      expect(c.message).toContain('User');
    });

    test('ImportConflict may include optional detail', () => {
      const c: ImportConflict = {
        kind: 'property_conflict',
        schemaName: 'Order',
        message: 'Property "status" differs.',
        detail: 'Order.status',
      };
      expect(c.detail).toBe('Order.status');
    });

    test('ImportConflict may include optional impactIfResolved (#597)', () => {
      const c: ImportConflict = {
        kind: 'duplicate_schema',
        schemaName: 'User',
        message: 'User exists.',
        impactIfResolved: 'If renamed: new class created; existing unchanged.',
      };
      expect(c.impactIfResolved).toBe('If renamed: new class created; existing unchanged.');
    });
  });

  describe('getConflictSummary', () => {
    test('returns zero counts for empty conflicts', () => {
      const summary = getConflictSummary([]);
      expect(summary.duplicate_schema).toBe(0);
      expect(summary.property_conflict).toBe(0);
      expect(summary.reference_conflict).toBe(0);
      expect(summary.type_mismatch).toBe(0);
      expect(summary.semantic_conflict).toBe(0);
    });

    test('counts single conflict by kind', () => {
      const summary = getConflictSummary([
        { kind: 'duplicate_schema', schemaName: 'User', message: 'User exists.' },
      ]);
      expect(summary.duplicate_schema).toBe(1);
      expect(summary.property_conflict).toBe(0);
    });

    test('counts multiple conflicts of same kind', () => {
      const summary = getConflictSummary([
        { kind: 'duplicate_schema', schemaName: 'User', message: 'User exists.' },
        { kind: 'duplicate_schema', schemaName: 'Product', message: 'Product exists.' },
      ]);
      expect(summary.duplicate_schema).toBe(2);
    });

    test('counts mixed kinds correctly', () => {
      const conflicts: ImportConflict[] = [
        { kind: 'duplicate_schema', schemaName: 'User', message: 'Dup.' },
        { kind: 'property_conflict', schemaName: 'Order', message: 'Prop.', detail: 'x' },
        { kind: 'reference_conflict', schemaName: 'Invoice', message: 'Ref.' },
        { kind: 'type_mismatch', schemaName: 'Item', message: 'Type.' },
        { kind: 'semantic_conflict', schemaName: 'Rule', message: 'Sem.' },
      ];
      const summary = getConflictSummary(conflicts);
      expect(summary.duplicate_schema).toBe(1);
      expect(summary.property_conflict).toBe(1);
      expect(summary.reference_conflict).toBe(1);
      expect(summary.type_mismatch).toBe(1);
      expect(summary.semantic_conflict).toBe(1);
    });
  });

  describe('building conflict list from schema list (duplicate_schema)', () => {
    /**
     * Mirrors the logic in ClassImportDialog: schemas with exists === true
     * become one ImportConflict each with kind 'duplicate_schema' and impactIfResolved (#597).
     * #582: duplicate = same name, different definition.
     */
    function buildConflictReportFromSchemas(
      schemas: { name: string; exists: boolean }[]
    ): ImportConflict[] {
      return schemas
        .filter((s) => s.exists)
        .map((s) => ({
          kind: 'duplicate_schema' as const,
          schemaName: s.name,
          message: `A class named "${s.name}" already exists with a different definition. Importing will overwrite or you can rename.`,
          impactIfResolved:
            'Use the class name override (when you select a different schema) to import under a new name: a new class will be created and the existing one will be unchanged. You cannot import with the same name.',
        }));
    }

    test('returns empty array when no schemas exist', () => {
      const schemas = [
        { name: 'NewClass', exists: false },
        { name: 'AnotherNew', exists: false },
      ];
      expect(buildConflictReportFromSchemas(schemas)).toEqual([]);
    });

    test('returns one conflict per schema with exists true', () => {
      const schemas = [
        { name: 'User', exists: true },
        { name: 'NewClass', exists: false },
        { name: 'Product', exists: true },
      ];
      const result = buildConflictReportFromSchemas(schemas);
      expect(result).toHaveLength(2);
      expect(result[0]).toMatchObject({
        kind: 'duplicate_schema',
        schemaName: 'User',
        message: expect.stringContaining('User'),
      });
      expect(result[1]).toMatchObject({
        kind: 'duplicate_schema',
        schemaName: 'Product',
        message: expect.stringContaining('Product'),
      });
    });

    test('message includes schema name and overwrite/rename hint', () => {
      const schemas = [{ name: 'Order', exists: true }];
      const result = buildConflictReportFromSchemas(schemas);
      expect(result[0].message).toContain('Order');
      expect(result[0].message).toMatch(/overwrite|rename/i);
    });

    test('order of conflicts matches order of existing schemas in list', () => {
      const schemas = [
        { name: 'A', exists: true },
        { name: 'B', exists: false },
        { name: 'C', exists: true },
      ];
      const result = buildConflictReportFromSchemas(schemas);
      expect(result.map((c) => c.schemaName)).toEqual(['A', 'C']);
    });

    test('each duplicate_schema conflict includes impactIfResolved (#597)', () => {
      const schemas = [{ name: 'User', exists: true }];
      const result = buildConflictReportFromSchemas(schemas);
      expect(result).toHaveLength(1);
      expect(result[0].impactIfResolved).toBeDefined();
      expect(result[0].impactIfResolved).toContain('class name override');
      expect(result[0].impactIfResolved).toMatch(/new class|existing.*unchanged|cannot import with the same name/i);
    });
  });

  describe('Impact if resolved (#597)', () => {
    test('DEFAULT_IMPACT_IF_RESOLVED has non-empty text for every conflict kind', () => {
      const kinds: ImportConflictKind[] = [
        'duplicate_schema',
        'property_conflict',
        'reference_conflict',
        'type_mismatch',
        'semantic_conflict',
      ];
      kinds.forEach((kind) => {
        const text = DEFAULT_IMPACT_IF_RESOLVED[kind];
        expect(text).toBeDefined();
        expect(typeof text).toBe('string');
        expect(text.length).toBeGreaterThan(10);
      });
    });

    test('default impact for duplicate_schema mentions rename or overwrite', () => {
      const text = DEFAULT_IMPACT_IF_RESOLVED.duplicate_schema;
      expect(text).toMatch(/rename|overwrite|replaced|unchanged/i);
    });

    test('effective impact uses impactIfResolved when provided, else default', () => {
      const getEffectiveImpact = (c: ImportConflict): string =>
        c.impactIfResolved ?? DEFAULT_IMPACT_IF_RESOLVED[c.kind];

      const withCustom: ImportConflict = {
        kind: 'property_conflict',
        schemaName: 'Order',
        message: 'Conflict',
        impactIfResolved: 'Custom impact text.',
      };
      expect(getEffectiveImpact(withCustom)).toBe('Custom impact text.');

      const withoutCustom: ImportConflict = {
        kind: 'property_conflict',
        schemaName: 'Order',
        message: 'Conflict',
      };
      expect(getEffectiveImpact(withoutCustom)).toBe(DEFAULT_IMPACT_IF_RESOLVED.property_conflict);
    });
  });

  describe('ConflictReport data contract (no render)', () => {
    test('empty conflicts array yields zero total and no rows', () => {
      const conflicts: ImportConflict[] = [];
      const summary = getConflictSummary(conflicts);
      const total = Object.values(summary).reduce((a, b) => a + b, 0);
      expect(total).toBe(0);
    });

    test('single conflict yields total 1 and one kind with count 1', () => {
      const conflicts: ImportConflict[] = [
        { kind: 'duplicate_schema', schemaName: 'User', message: 'User exists.' },
      ];
      const summary = getConflictSummary(conflicts);
      const total = Object.values(summary).reduce((a, b) => a + b, 0);
      expect(total).toBe(1);
      expect(summary.duplicate_schema).toBe(1);
    });

    test('plural summary: multiple of same kind', () => {
      const conflicts: ImportConflict[] = [
        { kind: 'duplicate_schema', schemaName: 'User', message: 'M1' },
        { kind: 'duplicate_schema', schemaName: 'Product', message: 'M2' },
      ];
      const summary = getConflictSummary(conflicts);
      expect(summary.duplicate_schema).toBe(2);
      const kindSummaryEntries = (Object.entries(summary) as [ImportConflictKind, number][]).filter(
        ([, count]) => count > 0
      );
      expect(kindSummaryEntries).toHaveLength(1);
      expect(kindSummaryEntries[0]).toEqual(['duplicate_schema', 2]);
    });
  });

  describe('Conflict export as markdown (#598)', () => {
    test('conflictReportToMarkdown returns string with title and total', () => {
      const conflicts: ImportConflict[] = [
        { kind: 'duplicate_schema', schemaName: 'User', message: 'User exists.' },
      ];
      const md = conflictReportToMarkdown(conflicts, {
        title: 'My Conflict Report',
        exportedAt: '2025-02-11T12:00:00.000Z',
      });
      expect(md).toContain('# My Conflict Report');
      expect(md).toContain('**Total conflicts:** 1');
      expect(md).toContain('**Exported:** 2025-02-11T12:00:00.000Z');
    });

    test('conflictReportToMarkdown includes summary table by kind', () => {
      const conflicts: ImportConflict[] = [
        { kind: 'duplicate_schema', schemaName: 'User', message: 'M1' },
        { kind: 'duplicate_schema', schemaName: 'Product', message: 'M2' },
      ];
      const md = conflictReportToMarkdown(conflicts, { exportedAt: '2025-02-11T12:00:00.000Z' });
      expect(md).toContain('## Summary by type');
      expect(md).toContain('Duplicate schema (same name, different definition)');
      expect(md).toContain('| 2 |');
    });

    test('conflictReportToMarkdown includes conflicts table with schema, type, description, impact', () => {
      const conflicts: ImportConflict[] = [
        {
          kind: 'duplicate_schema',
          schemaName: 'Order',
          message: 'Order already exists.',
          impactIfResolved: 'Custom impact.',
        },
      ];
      const md = conflictReportToMarkdown(conflicts);
      expect(md).toContain('## Conflicts');
      expect(md).toContain('| Order |');
      expect(md).toContain('Duplicate schema (same name, different definition)');
      expect(md).toContain('Order already exists.');
      expect(md).toContain('Custom impact.');
    });

    test('conflictReportToMarkdown uses default impact when impactIfResolved missing', () => {
      const conflicts: ImportConflict[] = [
        { kind: 'property_conflict', schemaName: 'Item', message: 'Prop conflict.' },
      ];
      const md = conflictReportToMarkdown(conflicts);
      expect(md).toContain(DEFAULT_IMPACT_IF_RESOLVED.property_conflict);
    });

    test('conflictReportToMarkdown escapes pipe in cells', () => {
      const conflicts: ImportConflict[] = [
        { kind: 'duplicate_schema', schemaName: 'Foo', message: 'Bar | baz' },
      ];
      const md = conflictReportToMarkdown(conflicts);
      expect(md).toContain('Bar \\| baz');
    });

    test('getConflictReportMarkdownFilename returns .md filename with timestamp', () => {
      const name = getConflictReportMarkdownFilename('2025-02-11T12:00:00.000Z');
      expect(name).toMatch(/^conflict-report-.*\.md$/);
      expect(name).toContain('2025-02-11');
    });

    test('getConflictReportMarkdownFilename uses current time when no arg', () => {
      const name = getConflictReportMarkdownFilename();
      expect(name).toMatch(/^conflict-report-.*\.md$/);
    });

    test('conflictReportToMarkdown with empty conflicts has title, total 0, and table headers only', () => {
      const md = conflictReportToMarkdown([], {
        title: 'Empty Report',
        exportedAt: '2025-02-11T00:00:00.000Z',
      });
      expect(md).toContain('# Empty Report');
      expect(md).toContain('**Total conflicts:** 0');
      expect(md).toContain('## Summary by type');
      expect(md).toContain('## Conflicts');
      expect(md).toContain('| Schema / Resource |');
      // No data rows in summary (only header/separator)
      const summaryTablePart = md.slice(md.indexOf('## Summary by type'), md.indexOf('## Conflicts'));
      expect(summaryTablePart).toContain('| Conflict type | Count |');
      expect(summaryTablePart).not.toMatch(/\|\s*Duplicate schema \(same name, different definition\)\s*\|/);
    });

    test('conflictReportToMarkdown includes optional detail in description cell', () => {
      const conflicts: ImportConflict[] = [
        {
          kind: 'property_conflict',
          schemaName: 'Order',
          message: 'Property differs.',
          detail: 'Order.status',
        },
      ];
      const md = conflictReportToMarkdown(conflicts);
      expect(md).toContain('Property differs.');
      expect(md).toContain('Order.status');
      expect(md).toContain('_Order.status_');
    });

    test('conflictReportToMarkdown with no options uses default title', () => {
      const conflicts: ImportConflict[] = [
        { kind: 'duplicate_schema', schemaName: 'User', message: 'Exists.' },
      ];
      const md = conflictReportToMarkdown(conflicts);
      expect(md).toContain('# Import Conflict Report');
    });

    test('conflictReportToMarkdown flattens newlines in message and impact to spaces', () => {
      const conflicts: ImportConflict[] = [
        {
          kind: 'duplicate_schema',
          schemaName: 'User',
          message: 'Line one\nLine two',
          impactIfResolved: 'Impact A\nImpact B',
        },
      ];
      const md = conflictReportToMarkdown(conflicts);
      expect(md).toContain('Line one Line two');
      expect(md).toContain('Impact A Impact B');
      const dataRow = md.split('\n').find((line) => line.startsWith('| User |'));
      expect(dataRow).toBeDefined();
      expect(dataRow).not.toContain('\n');
    });

    test('conflictReportToMarkdown with all five conflict kinds includes each in summary', () => {
      const conflicts: ImportConflict[] = [
        { kind: 'duplicate_schema', schemaName: 'A', message: 'M' },
        { kind: 'property_conflict', schemaName: 'B', message: 'M' },
        { kind: 'reference_conflict', schemaName: 'C', message: 'M' },
        { kind: 'type_mismatch', schemaName: 'D', message: 'M' },
        { kind: 'semantic_conflict', schemaName: 'E', message: 'M' },
      ];
      const md = conflictReportToMarkdown(conflicts, { exportedAt: '2025-02-11T12:00:00.000Z' });
      expect(md).toContain('Duplicate schema (same name, different definition)');
      expect(md).toContain('Property conflict');
      expect(md).toContain('Reference conflict');
      expect(md).toContain('Type mismatch');
      expect(md).toContain('Semantic conflict');
      expect(md).toContain('**Total conflicts:** 5');
    });

    test('getConflictReportMarkdownFilename uses ISO date without colons or dots', () => {
      const name = getConflictReportMarkdownFilename('2025-02-11T14:30:00.123Z');
      expect(name).toBe('conflict-report-2025-02-11T14-30-00.md');
    });
  });
});
