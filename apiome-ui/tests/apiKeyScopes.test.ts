/**
 * Unit tests for workspace API key scope helpers (CTG-2.3 / #4473).
 */

import {
  API_KEY_SCOPE_PRESETS,
  formatApiKeyScopes,
  normalizeApiKeyScopes,
  presetFromScopes,
} from '../src/app/utils/apiKeyScopes';

describe('apiKeyScopes', () => {
  test('normalizeApiKeyScopes defaults to full access', () => {
    expect(normalizeApiKeyScopes(null)).toEqual(['*']);
    expect(normalizeApiKeyScopes(undefined)).toEqual(['*']);
    expect(normalizeApiKeyScopes([])).toEqual(['*']);
  });

  test('normalizeApiKeyScopes accepts CI scopes', () => {
    expect(normalizeApiKeyScopes(['diff:read'])).toEqual(['diff:read']);
    expect(normalizeApiKeyScopes('lint:read,diff:read')).toEqual([
      'lint:read',
      'diff:read',
    ]);
  });

  test('normalizeApiKeyScopes rejects invalid and mixed star', () => {
    expect(() => normalizeApiKeyScopes(['write'])).toThrow(/Invalid/);
    expect(() => normalizeApiKeyScopes(['*', 'diff:read'])).toThrow(/stand alone/);
  });

  test('presets map to expected scope arrays', () => {
    expect(API_KEY_SCOPE_PRESETS.full).toEqual(['*']);
    expect(API_KEY_SCOPE_PRESETS.diff).toEqual(['diff:read']);
    expect(API_KEY_SCOPE_PRESETS.lint).toEqual(['lint:read']);
    expect(API_KEY_SCOPE_PRESETS.ci_both).toEqual(['diff:read', 'lint:read']);
  });

  test('formatApiKeyScopes labels full access', () => {
    expect(formatApiKeyScopes(['*'])).toBe('Full access');
    expect(formatApiKeyScopes(['diff:read', 'lint:read'])).toBe(
      'diff:read, lint:read',
    );
  });

  test('presetFromScopes round-trips', () => {
    expect(presetFromScopes(['*'])).toBe('full');
    expect(presetFromScopes(['diff:read'])).toBe('diff');
    expect(presetFromScopes(['lint:read'])).toBe('lint');
    expect(presetFromScopes(['lint:read', 'diff:read'])).toBe('ci_both');
  });
});
