import { describe, test, expect } from '@jest/globals';
import {
  PROJECT_START_TEMPLATES,
  applyProjectStartTemplate,
  getProjectStartTemplate,
} from '../src/app/utils/project-templates';

describe('project-templates', () => {
  test('template ids are unique', () => {
    const ids = PROJECT_START_TEMPLATES.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  test('blank template has empty metadata', () => {
    const blank = getProjectStartTemplate('blank');
    expect(blank).toBeDefined();
    expect(blank!.metadata).toEqual({});
  });

  test('applyProjectStartTemplate returns a deep copy of metadata', () => {
    const a = applyProjectStartTemplate('public-rest');
    const b = applyProjectStartTemplate('public-rest');
    expect(a.metadata).toEqual(b.metadata);
    expect(a.metadata).not.toBe(b.metadata);
    a.metadata.summary = 'mutated';
    expect(b.metadata.summary).toBe('Public REST API for external consumers.');
  });

  test('public-rest includes MIT license', () => {
    const applied = applyProjectStartTemplate('public-rest');
    expect(applied.metadata.license?.identifier).toBe('MIT');
    expect(applied.metadata.contact?.email).toContain('@');
  });

  test('unknown id falls back to blank', () => {
    const applied = applyProjectStartTemplate('does-not-exist');
    expect(applied.metadata).toEqual({});
    expect(applied.suggestedDescription).toBe('');
  });

  test('every template has label and hint', () => {
    for (const t of PROJECT_START_TEMPLATES) {
      expect(t.label.trim().length).toBeGreaterThan(0);
      expect(t.hint.trim().length).toBeGreaterThan(0);
    }
  });
});
