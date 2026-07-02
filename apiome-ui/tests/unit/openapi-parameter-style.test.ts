import {
  defaultStyleForIn,
  normalizeStyleForLocation,
  PARAM_STYLE_OPTIONS,
} from '../../lib/utils/openapi-parameter-style';

describe('openapi-parameter-style', () => {
  it('defaults styles per OpenAPI parameter location', () => {
    expect(defaultStyleForIn('path')).toBe('simple');
    expect(defaultStyleForIn('query')).toBe('form');
    expect(defaultStyleForIn('header')).toBe('simple');
    expect(defaultStyleForIn('cookie')).toBe('form');
  });

  it('normalizes invalid stored style for the current location', () => {
    expect(normalizeStyleForLocation('header', 'form')).toBe('simple');
    expect(normalizeStyleForLocation('cookie', 'simple')).toBe('form');
    expect(normalizeStyleForLocation('query', 'deepObject')).toBe('deepObject');
  });

  it('lists OAS-appropriate options per location', () => {
    expect(PARAM_STYLE_OPTIONS.header.map((o) => o.value)).toEqual(['simple']);
    expect(PARAM_STYLE_OPTIONS.cookie.map((o) => o.value)).toEqual(['form']);
    expect(PARAM_STYLE_OPTIONS.path.length).toBe(3);
    expect(PARAM_STYLE_OPTIONS.query.length).toBe(4);
  });
});
