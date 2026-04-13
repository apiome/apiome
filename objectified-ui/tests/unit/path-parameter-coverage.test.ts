import {
  extractPathParameters,
  getPathParameterCoverageError,
  getPathTemplateValidationError,
} from '../../lib/utils/path-params';

describe('getPathParameterCoverageError', () => {
  it('returns null when template has no segments and no path params', () => {
    expect(getPathParameterCoverageError('/api/users', [])).toBeNull();
  });

  it('errors when template has {id} but no path parameter', () => {
    const msg = getPathParameterCoverageError('/users/{id}', []);
    expect(msg).toContain('{id}');
    expect(msg).toContain('no path parameter');
  });

  it('errors when path parameter exists but is not in the template', () => {
    const msg = getPathParameterCoverageError('/users', [
      { name: 'id', in_location: 'path' },
    ]);
    expect(msg).toContain('not in the URL template');
  });

  it('returns null when template and path params align', () => {
    expect(
      getPathParameterCoverageError('/users/{id}', [
        { name: 'id', in_location: 'path' },
        { name: 'page', in_location: 'query' },
      ])
    ).toBeNull();
  });

  it('delegates to template validation first', () => {
    expect(getPathParameterCoverageError('no-slash', [])).toBe(getPathTemplateValidationError('no-slash'));
  });

  it('matches extractPathParameters names', () => {
    const path = '/a/{x}/b/{y}';
    expect(extractPathParameters(path)).toEqual(['x', 'y']);
    expect(
      getPathParameterCoverageError(path, [
        { name: 'x', in_location: 'path' },
        { name: 'y', in_location: 'path' },
      ])
    ).toBeNull();
  });
});
