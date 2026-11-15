/**
 * The suggested-changes rule set (COL-4.2, #4526) — `lib/review-suggestions.ts`.
 */

import {
  buildFieldPatch,
  currentFieldValue,
  fieldInputText,
  fieldPointer,
  parseFieldInput,
  suggestionActions,
  suggestionOutcome,
  suggestionStatusLabel,
  targetsFromClasses,
  type ReviewSuggestion,
  type SuggestionTarget,
} from '../lib/review-suggestions';

const PROP: SuggestionTarget = {
  type: 'property',
  id: 'p1',
  label: 'Pet.name',
  element: { description: "The pet's name", data: { type: 'string', maxLength: 50 } },
};

const suggestion = (over: Partial<ReviewSuggestion> = {}): ReviewSuggestion => ({
  id: 's1',
  review_id: 'r1',
  version_id: 'v1',
  author_id: 'rex',
  author_name: 'Rex',
  target_type: 'property',
  target_id: 'p1',
  target_label: 'Pet.name',
  note: null,
  base: PROP.element,
  patch: [],
  proposed: PROP.element,
  status: 'open',
  conflict_paths: [],
  stale: false,
  decided_by: null,
  decided_by_name: null,
  decided_at: null,
  reason: null,
  created_at: '',
  ...over,
});

describe('pointers and values', () => {
  it('points at the description or into the body', () => {
    expect(fieldPointer('property', 'description')).toBe('/description');
    expect(fieldPointer('class', 'required')).toBe('/schema/required');
    expect(fieldPointer('property', 'a/b~c')).toBe('/data/a~1b~0c');
  });
  it('reads current values', () => {
    expect(currentFieldValue(PROP, 'maxLength')).toBe(50);
    expect(currentFieldValue(PROP, 'format')).toBeUndefined();
    expect(fieldInputText(['a', 'b'])).toBe('["a","b"]');
  });
  it('parses JSON where it parses, text otherwise, empty as remove', () => {
    expect(parseFieldInput('maxLength', '100')).toEqual({ remove: false, value: 100 });
    expect(parseFieldInput('format', 'uuid')).toEqual({ remove: false, value: 'uuid' });
    expect(parseFieldInput('description', '42')).toEqual({ remove: false, value: '42' });
    expect(parseFieldInput('format', '  ')).toEqual({ remove: true });
  });
});

describe('buildFieldPatch', () => {
  it('tests then replaces an existing value', () => {
    expect(buildFieldPatch(PROP, 'maxLength', '100')).toEqual([
      { op: 'test', path: '/data/maxLength', value: 50 },
      { op: 'replace', path: '/data/maxLength', value: 100 },
    ]);
  });
  it('adds a new field and removes an existing one', () => {
    expect(buildFieldPatch(PROP, 'format', 'uuid')).toEqual([{ op: 'add', path: '/data/format', value: 'uuid' }]);
    expect(buildFieldPatch(PROP, 'maxLength', '')).toEqual([
      { op: 'test', path: '/data/maxLength', value: 50 },
      { op: 'remove', path: '/data/maxLength' },
    ]);
  });
  it('clears a description to null rather than removing the key', () => {
    expect(buildFieldPatch(PROP, 'description', '')).toEqual([
      { op: 'test', path: '/description', value: "The pet's name" },
      { op: 'replace', path: '/description', value: null },
    ]);
  });
  it('is null for no change', () => {
    expect(buildFieldPatch(PROP, 'maxLength', '50')).toBeNull();
    expect(buildFieldPatch(PROP, 'format', '')).toBeNull();
  });
});

describe('actions and labels', () => {
  it('lets the requester or an editor apply, never the author, and the author withdraw', () => {
    expect(suggestionActions(suggestion(), 'rita', true)).toEqual({ apply: true, applyEnabled: true, reject: true, rejectLabel: 'Reject' });
    expect(suggestionActions(suggestion(), 'rex', true)).toEqual({ apply: false, applyEnabled: true, reject: true, rejectLabel: 'Withdraw' });
    expect(suggestionActions(suggestion(), 'olga', false)).toEqual({ apply: false, applyEnabled: true, reject: false, rejectLabel: 'Reject' });
    expect(suggestionActions(suggestion({ status: 'applied' }), 'rita', true).apply).toBe(false);
  });
  it('disables Apply on a stale suggestion and explains why', () => {
    const stale = suggestion({ stale: true, conflict_paths: ['data.maxLength'] });
    expect(suggestionActions(stale, 'rita', true).applyEnabled).toBe(false);
    expect(suggestionStatusLabel(stale)).toBe('Stale');
    expect(suggestionOutcome(stale)).toContain('changed since: data.maxLength');
    expect(suggestionOutcome(suggestion({ status: 'stale', conflict_paths: ['<deleted>'] }))).toContain('the element was deleted');
  });
  it('records who decided', () => {
    expect(suggestionOutcome(suggestion({ status: 'rejected', decided_by_name: 'Rita', reason: 'Keep 50' }))).toBe('Rejected by Rita: Keep 50');
    expect(suggestionOutcome(suggestion({ status: 'applied', decided_by_name: 'Rita' }))).toBe('Applied by Rita');
    expect(suggestionOutcome(suggestion())).toBeNull();
  });
});

describe('targetsFromClasses', () => {
  it('lists classes and their top-level properties', () => {
    const targets = targetsFromClasses([
      {
        id: 'c1',
        name: 'Pet',
        description: null,
        schema: '{"type":"object"}',
        properties: [
          { id: 'p1', name: 'name', description: 'n', data: { type: 'string' } },
          { id: 'p2', name: 'nested', parent_id: 'p1', data: {} },
        ],
      },
      { bogus: true },
    ]);
    expect(targets.map((t) => [t.type, t.label])).toEqual([
      ['class', 'Pet'],
      ['property', 'Pet.name'],
    ]);
    expect(targets[0].element).toEqual({ description: null, schema: { type: 'object' } });
  });
  it('is empty for anything else', () => {
    expect(targetsFromClasses(null)).toEqual([]);
  });
});
