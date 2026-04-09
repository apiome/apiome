import { classifyMergeDiff } from '../lib/version-merge';
import type { DiffSummary } from '../lib/schema-diff';

describe('classifyMergeDiff', () => {
  test('treats modified and removed paths as blocking conflicts', () => {
    const summary: DiffSummary = {
      added: [],
      removed: [{ type: 'removed', path: 'schemas.Gone', itemType: 'schema' }],
      modified: [{ type: 'modified', path: 'schemas.Pet', itemType: 'schema', changes: ['type'] }],
      unchanged: [],
    };
    const c = classifyMergeDiff(summary);
    expect(c.canAutoMerge).toBe(false);
    expect(c.conflictPaths).toContain('schemas.Pet');
    expect(c.conflictPaths).toContain('schemas.Gone');
  });

  test('extracts added schema names from added entries', () => {
    const summary: DiffSummary = {
      added: [{ type: 'added', path: 'schemas.NewThing', itemType: 'schema' }],
      removed: [],
      modified: [],
      unchanged: [],
    };
    const c = classifyMergeDiff(summary);
    expect(c.canAutoMerge).toBe(true);
    expect(c.addedSchemaNames).toContain('NewThing');
  });
});
