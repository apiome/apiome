import { describe, test, expect } from '@jest/globals';
import {
  PROJECT_DOMAIN_CATEGORIES,
  PROJECT_DOMAIN_CATEGORY_NONE,
  getProjectDomainCategory,
  getProjectDomainCategoryLabel,
} from '../src/app/utils/project-domain-categories';

describe('project-domain-categories', () => {
  test('ids are unique', () => {
    const ids = PROJECT_DOMAIN_CATEGORIES.map((c) => c.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  test('every category has label and hint', () => {
    for (const c of PROJECT_DOMAIN_CATEGORIES) {
      expect(c.label.trim().length).toBeGreaterThan(0);
      expect(c.hint.trim().length).toBeGreaterThan(0);
    }
  });

  test('getProjectDomainCategory resolves known ids', () => {
    expect(getProjectDomainCategory('iot')?.label).toBe('IoT device schemas');
    expect(getProjectDomainCategory('gaming')?.label).toContain('Gaming');
    expect(getProjectDomainCategory('ecommerce')?.label).toContain('E-commerce');
    expect(getProjectDomainCategory('logistics')?.label).toContain('Logistics');
  });

  test('getProjectDomainCategory returns undefined for unknown or empty', () => {
    expect(getProjectDomainCategory(undefined)).toBeUndefined();
    expect(getProjectDomainCategory('')).toBeUndefined();
    expect(getProjectDomainCategory(PROJECT_DOMAIN_CATEGORY_NONE)).toBeUndefined();
    expect(getProjectDomainCategory('not-a-real-id')).toBeUndefined();
  });

  test('getProjectDomainCategoryLabel is a thin label helper', () => {
    expect(getProjectDomainCategoryLabel('travel')).toBe('Travel & hospitality');
    expect(getProjectDomainCategoryLabel(undefined)).toBeUndefined();
  });
});
