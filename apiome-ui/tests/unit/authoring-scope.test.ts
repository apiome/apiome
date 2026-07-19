/**
 * Authoring scope URL persistence (UXE-1.2).
 *
 * Covers the acceptance criterion that a copied URL restores the same
 * authorized scope, and that a scope change never leaves stale selections
 * behind.
 */

import {
  applyAuthoringScope,
  authoringUrlScopesEqual,
  buildAuthoringHref,
  isAuthoringScopeResolved,
  parseAuthoringScope,
  serializeAuthoringScope,
  AUTHORING_ENVIRONMENT_PARAM,
  AUTHORING_PROJECT_PARAM,
  AUTHORING_VERSION_PARAM,
  EMPTY_AUTHORING_URL_SCOPE,
  type AuthoringUrlScope,
} from '../../lib/authoring/scope';

const FULL_SCOPE: AuthoringUrlScope = {
  projectId: 'proj-1',
  versionId: 'ver-1',
  environmentId: 'production',
};

describe('parseAuthoringScope', () => {
  it('reads project, version and environment from the query string', () => {
    const params = new URLSearchParams('projectId=proj-1&versionId=ver-1&env=production');
    expect(parseAuthoringScope(params)).toEqual(FULL_SCOPE);
  });

  it('falls back to the default lane when no environment is present', () => {
    const params = new URLSearchParams('projectId=proj-1');
    expect(parseAuthoringScope(params).environmentId).toBe('preview');
  });

  it('falls back to the default lane for an unknown environment', () => {
    const params = new URLSearchParams('projectId=proj-1&env=canary');
    expect(parseAuthoringScope(params).environmentId).toBe('preview');
  });

  it('treats blank and whitespace-only ids as absent', () => {
    const params = new URLSearchParams('projectId=%20%20&versionId=');
    expect(parseAuthoringScope(params)).toEqual(EMPTY_AUTHORING_URL_SCOPE);
  });

  it('discards a version that arrives without its owning project', () => {
    const params = new URLSearchParams('versionId=ver-1');
    expect(parseAuthoringScope(params).versionId).toBeNull();
  });

  it('trims surrounding whitespace from ids', () => {
    const params = new URLSearchParams('projectId=%20proj-1%20');
    expect(parseAuthoringScope(params).projectId).toBe('proj-1');
  });
});

describe('applyAuthoringScope', () => {
  it('preserves unrelated parameters so surface state survives a scope change', () => {
    const params = new URLSearchParams('tab=checks&sort=desc&projectId=old');
    const next = applyAuthoringScope(params, FULL_SCOPE);

    expect(next.get('tab')).toBe('checks');
    expect(next.get('sort')).toBe('desc');
    expect(next.get(AUTHORING_PROJECT_PARAM)).toBe('proj-1');
  });

  it('removes scope parameters that are no longer selected', () => {
    const params = new URLSearchParams('projectId=proj-1&versionId=ver-1&env=production');
    const next = applyAuthoringScope(params, EMPTY_AUTHORING_URL_SCOPE);

    expect(next.get(AUTHORING_PROJECT_PARAM)).toBeNull();
    expect(next.get(AUTHORING_VERSION_PARAM)).toBeNull();
    expect(next.get(AUTHORING_ENVIRONMENT_PARAM)).toBeNull();
  });

  it('omits the default lane so an unscoped URL stays clean', () => {
    const next = applyAuthoringScope(new URLSearchParams(), {
      ...FULL_SCOPE,
      environmentId: 'preview',
    });
    expect(next.get(AUTHORING_ENVIRONMENT_PARAM)).toBeNull();
  });

  it('never serializes a version without its project', () => {
    const next = applyAuthoringScope(new URLSearchParams(), {
      projectId: null,
      versionId: 'ver-1',
      environmentId: 'preview',
    });
    expect(next.get(AUTHORING_VERSION_PARAM)).toBeNull();
  });
});

describe('round trip', () => {
  it('restores an identical scope from its own serialization', () => {
    const restored = parseAuthoringScope(new URLSearchParams(serializeAuthoringScope(FULL_SCOPE)));
    expect(authoringUrlScopesEqual(restored, FULL_SCOPE)).toBe(true);
  });

  it('restores the default lane from an empty scope', () => {
    const restored = parseAuthoringScope(
      new URLSearchParams(serializeAuthoringScope(EMPTY_AUTHORING_URL_SCOPE))
    );
    expect(restored).toEqual(EMPTY_AUTHORING_URL_SCOPE);
  });
});

describe('buildAuthoringHref', () => {
  it('appends the scope query string', () => {
    expect(buildAuthoringHref('/ade/authoring/scribe', FULL_SCOPE)).toBe(
      '/ade/authoring/scribe?projectId=proj-1&versionId=ver-1&env=production'
    );
  });

  it('returns a bare path when there is nothing to encode', () => {
    expect(buildAuthoringHref('/ade/authoring', EMPTY_AUTHORING_URL_SCOPE)).toBe('/ade/authoring');
  });
});

describe('authoringUrlScopesEqual', () => {
  it('distinguishes scopes that differ only by lane', () => {
    expect(
      authoringUrlScopesEqual(FULL_SCOPE, { ...FULL_SCOPE, environmentId: 'preview' })
    ).toBe(false);
  });
});

describe('isAuthoringScopeResolved', () => {
  it('is true only when both project and version are selected', () => {
    expect(isAuthoringScopeResolved(FULL_SCOPE)).toBe(true);
    expect(isAuthoringScopeResolved({ ...FULL_SCOPE, versionId: null })).toBe(false);
    expect(isAuthoringScopeResolved(EMPTY_AUTHORING_URL_SCOPE)).toBe(false);
  });
});
