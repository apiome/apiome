/**
 * Unit tests for group tag picker normalization (#2526).
 */

import { describe, test, expect } from '@jest/globals';

import {
  mapProjectTagToGroupOption,
  normalizeStoredGroupTags,
} from '../src/app/utils/tag-color-tokens';

describe('mapProjectTagToGroupOption', () => {
  test('maps getTagsForProject shape (name, color)', () => {
    expect(
      mapProjectTagToGroupOption({ id: '1', name: 'API', color: 'primary' })
    ).toEqual({ id: '1', name: 'API', color: 'primary' });
  });

  test('maps class-tag join shape (tag_name, tag_color)', () => {
    expect(
      mapProjectTagToGroupOption({ id: '1', tag_name: 'Core', tag_color: 'success' })
    ).toEqual({ id: '1', name: 'Core', color: 'success' });
  });

  test('prefers tag_name over name when both present', () => {
    expect(
      mapProjectTagToGroupOption({
        id: '1',
        name: 'Wrong',
        tag_name: 'Right',
        color: 'default',
      })
    ).toEqual({ id: '1', name: 'Right', color: 'default' });
  });
});

describe('normalizeStoredGroupTags', () => {
  test('fills missing labels from project catalog', () => {
    const projectTags = [{ id: 'a', name: 'Alpha', color: 'info' }];
    expect(
      normalizeStoredGroupTags([{ id: 'a' }], projectTags)
    ).toEqual([{ id: 'a', name: 'Alpha', color: 'info' }]);
  });

  test('keeps stored name when present', () => {
    const projectTags = [{ id: 'a', name: 'Catalog', color: 'info' }];
    expect(
      normalizeStoredGroupTags([{ id: 'a', name: 'Saved', color: 'warning' }], projectTags)
    ).toEqual([{ id: 'a', name: 'Saved', color: 'warning' }]);
  });
});
