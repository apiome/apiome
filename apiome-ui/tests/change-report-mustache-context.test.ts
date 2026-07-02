import * as fs from 'fs';
import * as path from 'path';
import { describe, it, expect } from '@jest/globals';
import {
  buildMustacheContext,
  changeModelTotalChanges,
  isNoOpChangeModel,
} from '../lib/change-report-mustache-context';

const EMPTY_MODEL: Record<string, unknown> = {
  schemaVersion: '1.0',
  schemas: { added: [], removed: [], modified: [] },
  properties: [],
  references: [],
  relationships: [],
  documentation: [],
  warnings: [],
  skipped: [],
};

const sampleFixture = JSON.parse(
  fs.readFileSync(
    path.join(__dirname, '../lib/change-report-sample-fixture.json'),
    'utf8',
  ),
) as Record<string, unknown>;

describe('buildMustacheContext', () => {
  it('merges counts and schema buckets for preview', () => {
    const ctx = buildMustacheContext(sampleFixture as Record<string, unknown>, {
      productName: 'P',
      fromVersionLabel: 'a',
      toVersionLabel: 'b',
    });
    expect(ctx.schemaCounts).toEqual({ added: 1, removed: 1, modified: 1 });
    expect(ctx.propertyCount).toBe(1);
    expect(ctx.generatorVersion).toBe('apiome-ui/preview');
    expect(ctx.schemaSection).toBe(true);
    expect(ctx.noChangesSection).toBe(false);
  });
});

describe('isNoOpChangeModel / changeModelTotalChanges (RAR-4.3)', () => {
  it('treats an empty diff as a no-op', () => {
    expect(changeModelTotalChanges(EMPTY_MODEL)).toBe(0);
    expect(isNoOpChangeModel(EMPTY_MODEL)).toBe(true);
    expect(buildMustacheContext(EMPTY_MODEL).noChangesSection).toBe(true);
  });

  it('ignores warning-only diffs when deciding no-op', () => {
    const warnOnly = {
      ...EMPTY_MODEL,
      warnings: [{ code: 'external_ref_not_followed', message: 'x', path: '/' }],
    };
    expect(isNoOpChangeModel(warnOnly)).toBe(true);
    expect(buildMustacheContext(warnOnly).noChangesSection).toBe(true);
  });

  it('counts substantive schema and property changes', () => {
    const changed = {
      ...EMPTY_MODEL,
      schemas: { added: [{ name: 'New' }], removed: [], modified: [] },
      properties: [{ schemaName: 'S', path: '/x', changeKind: 'added' }],
    };
    expect(changeModelTotalChanges(changed)).toBe(2);
    expect(isNoOpChangeModel(changed)).toBe(false);
    expect(buildMustacheContext(changed).noChangesSection).toBe(false);
  });

  it('honors an explicit noChanges flag stamped by the refresh pipeline', () => {
    const flagged = {
      ...EMPTY_MODEL,
      schemas: { added: [{ name: 'New' }], removed: [], modified: [] },
      noChanges: true,
    };
    // Flag wins over recomputation.
    expect(isNoOpChangeModel(flagged)).toBe(true);
  });
});
