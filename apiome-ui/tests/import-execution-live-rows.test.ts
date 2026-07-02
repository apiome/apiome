/**
 * Unit tests for Import Execution live checklist helpers (#296).
 */

import { describe, test, expect } from '@jest/globals';
import {
  buildImportLiveChecklist,
  formatProgressPrimaryLine,
  estimateSecondsRemaining,
} from '../lib/import-execution-live-rows';
import type { ImportEventLike } from '../lib/import-execution-error-indicators';

describe('import-execution-live-rows (#296)', () => {
  describe('buildImportLiveChecklist', () => {
    test('marks current schema as importing during creating-classes', () => {
      const selected = ['Pet', 'Order'];
      const events: ImportEventLike[] = [
        { id: '1', ts: 1, level: 'info', code: 'CLASS_CREATED', message: 'Imported class: Pet' },
      ];
      const progress = {
        phase: 'creating-classes' as const,
        total: 4,
        completed: 2,
        currentItem: 'Order',
      };
      const rows = buildImportLiveChecklist(selected, events, progress, 'running');
      expect(rows).toHaveLength(2);
      expect(rows[0].status).toBe('success');
      expect(rows[1].status).toBe('importing');
    });

    test('shows warning with first warn tied to class context', () => {
      const selected = ['Order'];
      const events: ImportEventLike[] = [
        {
          id: 'w',
          ts: 1,
          level: 'warn',
          code: 'SKIP_PROPERTY',
          message: 'Skipping property "shipDate" in class "Order"',
          context: { className: 'Order', propertyName: 'shipDate' },
        },
        { id: 'c', ts: 2, level: 'info', code: 'CLASS_CREATED', message: 'Imported class: Order' },
      ];
      const rows = buildImportLiveChecklist(selected, events, undefined, 'completed');
      expect(rows[0].status).toBe('warning');
      expect(rows[0].detail).toContain('shipDate');
    });

    test('infers order from events when selectedSchemas is empty', () => {
      const events: ImportEventLike[] = [
        { id: 'a', ts: 1, level: 'info', code: 'CLASS_CREATED', message: 'Imported class: Alpha' },
        { id: 'b', ts: 2, level: 'info', code: 'CLASS_CREATED', message: 'Imported class: Beta' },
      ];
      const rows = buildImportLiveChecklist([], events, undefined, 'completed');
      expect(rows.map((r) => r.label)).toEqual(['Alpha', 'Beta']);
      expect(rows.every((r) => r.status === 'success')).toBe(true);
    });
  });

  describe('formatProgressPrimaryLine', () => {
    test('formats creating-classes with schema index and name', () => {
      const line = formatProgressPrimaryLine(
        { phase: 'creating-classes', total: 14, completed: 9, currentItem: 'Order' },
        'running'
      );
      expect(line).toBe('Importing schema 8 of 12: Order');
    });

    test('falls back when no progress', () => {
      expect(formatProgressPrimaryLine(undefined, 'queued')).toBe('Waiting to start…');
    });
  });

  describe('estimateSecondsRemaining', () => {
    test('returns null at 0% or 100%', () => {
      expect(estimateSecondsRemaining(0, 1000)).toBeNull();
      expect(estimateSecondsRemaining(100, 1000)).toBeNull();
    });

    test('estimates remaining seconds from elapsed and percent', () => {
      const sec = estimateSecondsRemaining(50, 5000);
      expect(sec).not.toBeNull();
      expect(sec!).toBeGreaterThan(0);
    });
  });
});
