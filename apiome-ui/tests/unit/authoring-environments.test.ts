/**
 * Authoring delivery environments and read-only derivation (UXE-1.2).
 */

import {
  AUTHORING_ENVIRONMENTS,
  DEFAULT_AUTHORING_ENVIRONMENT_ID,
  getAuthoringEnvironment,
  isAuthoringEnvironmentId,
} from '../../lib/authoring/environments';
import { isAuthoringScopeReadOnly } from '../../lib/authoring/scope-client';

describe('AUTHORING_ENVIRONMENTS', () => {
  it('declares preview and production, in that order', () => {
    expect(AUTHORING_ENVIRONMENTS.map((environment) => environment.id)).toEqual([
      'preview',
      'production',
    ]);
  });

  it('defaults to the editable lane', () => {
    expect(DEFAULT_AUTHORING_ENVIRONMENT_ID).toBe('preview');
    expect(getAuthoringEnvironment('preview').readOnly).toBe(false);
  });

  it('treats production as read-only, because it serves a promoted release', () => {
    expect(getAuthoringEnvironment('production').readOnly).toBe(true);
  });

  it('gives every lane a label and an explanation', () => {
    for (const environment of AUTHORING_ENVIRONMENTS) {
      expect(environment.label.length).toBeGreaterThan(0);
      expect(environment.description.length).toBeGreaterThan(0);
    }
  });
});

describe('isAuthoringEnvironmentId', () => {
  it.each([
    ['preview', true],
    ['production', true],
    ['canary', false],
    ['', false],
    [null, false],
    [42, false],
  ])('%s → %s', (value, expected) => {
    expect(isAuthoringEnvironmentId(value)).toBe(expected);
  });
});

describe('getAuthoringEnvironment', () => {
  it('degrades an unknown lane to the default rather than throwing', () => {
    expect(getAuthoringEnvironment('canary').id).toBe(DEFAULT_AUTHORING_ENVIRONMENT_ID);
    expect(getAuthoringEnvironment(undefined).id).toBe(DEFAULT_AUTHORING_ENVIRONMENT_ID);
  });
});

describe('isAuthoringScopeReadOnly', () => {
  const draft = { id: 'v1', versionId: '1.0.0', description: null, published: false };
  const published = { ...draft, published: true };

  it('is false for a draft version on the preview lane', () => {
    expect(isAuthoringScopeReadOnly(draft, false)).toBe(false);
  });

  it('is true for a published version, whose contents are frozen', () => {
    expect(isAuthoringScopeReadOnly(published, false)).toBe(true);
  });

  it('is true on a read-only lane even for a draft version', () => {
    expect(isAuthoringScopeReadOnly(draft, true)).toBe(true);
  });

  it('is false when no version has resolved yet on an editable lane', () => {
    expect(isAuthoringScopeReadOnly(undefined, false)).toBe(false);
  });
});
