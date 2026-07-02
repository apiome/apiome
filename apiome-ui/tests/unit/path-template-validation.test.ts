import { describe, it, expect } from '@jest/globals';
import {
  getPathTemplateValidationError,
  isValidPath,
} from '../../lib/utils/path-params';

describe('getPathTemplateValidationError', () => {
  it('accepts simple and templated paths', () => {
    expect(getPathTemplateValidationError('/users')).toBeNull();
    expect(getPathTemplateValidationError('/users/{id}')).toBeNull();
    expect(getPathTemplateValidationError('/v1/a/{b}/c/{d}')).toBeNull();
  });

  it('rejects empty or missing leading slash', () => {
    expect(getPathTemplateValidationError('')).not.toBeNull();
    expect(getPathTemplateValidationError('users')).not.toBeNull();
  });

  it('rejects duplicate template variable names', () => {
    const err = getPathTemplateValidationError('/users/{id}/posts/{id}');
    expect(err).toContain('Duplicate');
  });

  it('rejects unbalanced braces', () => {
    expect(getPathTemplateValidationError('/users/{id')).not.toBeNull();
  });

  it('isValidPath matches null error', () => {
    expect(isValidPath('/x')).toBe(true);
    expect(isValidPath('/users/{id}/posts/{id}')).toBe(false);
  });
});
