/**
 * Authoring secondary navigation model (UXE-1.2).
 */

import {
  AUTHORING_SURFACES,
  getAuthoringSurface,
  isAuthoringPathname,
  isAuthoringSurfaceActive,
  isAuthoringSurfaceEntitled,
  resolveAuthoringSurface,
} from '../../lib/authoring/surfaces';
import { UI_AUTHORING_ROUTES } from '../../lib/studio-routes';

describe('AUTHORING_SURFACES', () => {
  it('mirrors the five suite dropdown destinations, in order', () => {
    expect(AUTHORING_SURFACES.map((surface) => surface.id)).toEqual([
      'overview',
      'scribe',
      'slate',
      'releases',
      'insights',
    ]);
  });

  it('reuses the shared route constants rather than restating paths', () => {
    expect(AUTHORING_SURFACES.map((surface) => surface.path)).toEqual([
      UI_AUTHORING_ROUTES.root,
      UI_AUTHORING_ROUTES.scribe,
      UI_AUTHORING_ROUTES.slate,
      UI_AUTHORING_ROUTES.releases,
      UI_AUTHORING_ROUTES.insights,
    ]);
  });

  it('gives every planned surface the ticket that delivers it', () => {
    for (const surface of AUTHORING_SURFACES) {
      if (surface.status === 'planned') expect(surface.plannedIn).toBeTruthy();
    }
  });

  it('leaves Overview ungated so it can always explain the rest', () => {
    expect(getAuthoringSurface('overview')?.featureFlag).toBeUndefined();
  });
});

describe('isAuthoringPathname', () => {
  it.each([
    ['/ade/authoring', true],
    ['/ade/authoring/scribe', true],
    ['/ade/authoring/scribe/doc-1', true],
    ['/ade/studio/editor', false],
    ['/ade', false],
    ['/ade/authoring-archive', false],
    [null, false],
    [undefined, false],
  ])('%s → %s', (pathname, expected) => {
    expect(isAuthoringPathname(pathname as string | null)).toBe(expected);
  });
});

describe('resolveAuthoringSurface', () => {
  it('resolves the root to Overview', () => {
    expect(resolveAuthoringSurface('/ade/authoring')?.id).toBe('overview');
  });

  it('resolves a child surface', () => {
    expect(resolveAuthoringSurface('/ade/authoring/slate')?.id).toBe('slate');
  });

  it('resolves a nested route to its owning surface', () => {
    expect(resolveAuthoringSurface('/ade/authoring/scribe/doc-1')?.id).toBe('scribe');
  });

  it('returns undefined outside the route group', () => {
    expect(resolveAuthoringSurface('/ade/studio')).toBeUndefined();
  });
});

describe('isAuthoringSurfaceActive', () => {
  it('marks Overview active only on the root, not on its children', () => {
    const overview = getAuthoringSurface('overview')!;
    expect(isAuthoringSurfaceActive(overview, '/ade/authoring')).toBe(true);
    expect(isAuthoringSurfaceActive(overview, '/ade/authoring/releases')).toBe(false);
  });

  it('marks exactly one surface active for any route in the group', () => {
    const active = AUTHORING_SURFACES.filter((surface) =>
      isAuthoringSurfaceActive(surface, '/ade/authoring/insights')
    );
    expect(active.map((surface) => surface.id)).toEqual(['insights']);
  });
});

describe('isAuthoringSurfaceEntitled', () => {
  it('always entitles an ungated surface', () => {
    expect(isAuthoringSurfaceEntitled(getAuthoringSurface('overview')!, new Set())).toBe(true);
  });

  it('requires the declared flag for a gated surface', () => {
    const scribe = getAuthoringSurface('scribe')!;
    expect(isAuthoringSurfaceEntitled(scribe, new Set())).toBe(false);
    expect(isAuthoringSurfaceEntitled(scribe, new Set(['scribe']))).toBe(true);
  });

  it('gates Releases and Insights behind the hosted plan', () => {
    const hosted = new Set(['hosted']);
    expect(isAuthoringSurfaceEntitled(getAuthoringSurface('releases')!, hosted)).toBe(true);
    expect(isAuthoringSurfaceEntitled(getAuthoringSurface('insights')!, new Set())).toBe(false);
  });
});
